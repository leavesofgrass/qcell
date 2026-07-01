"""Strict-mode OS confinement for the code-execution worker (sandbox Phase 3).

Phases 1–2 (see :mod:`abax.console_worker`, :mod:`abax.proclimits`) gave crash
and resource isolation. Phase 3 adds the actual **security boundary**: an
opt-in *strict mode* that confines the worker's filesystem and network access
using the platform's OS sandbox primitive.

The design's non-negotiable rule — *a partial sandbox is worse than none* — is
enforced two ways:

1. **Feature-detect, refuse when absent.** Each platform strategy reports
   :meth:`Confinement.available`; if strict mode is requested and no strategy
   is available, we do **not** silently run unconfined — the caller refuses.
2. **Fail closed via a live self-test.** After confinement is applied, the
   worker runs :func:`selftest`, which *attempts real escapes* — writing a file
   outside the allowed scratch dir and opening an outbound socket. If any escape
   succeeds, the worker refuses to execute user code. So even a confinement
   this machine can't otherwise validate cannot silently ship as a fake
   sandbox: if it doesn't actually confine, the self-test catches it.

## The two confinement models

A platform strategy uses one of two mechanisms (a strategy may combine both):

* **Wrapper** — an external launcher wraps the worker's argv (Linux
  ``bwrap``, macOS ``sandbox-exec``). Applied by the parent
  (:meth:`Confinement.wrap_argv`) before spawning.
* **In-child** — a syscall-level restriction applied inside the worker after
  it boots but before it runs any user code (Linux Landlock/seccomp, Windows
  token/AppContainer finalization). Applied by :meth:`Confinement.apply_in_child`.

Platform strategies live in ``sandbox_linux`` / ``sandbox_macos`` /
``sandbox_windows`` and are imported lazily by :func:`select_confinement` so a
module for the wrong OS never loads.
"""

from __future__ import annotations

import os
import sys
from typing import Protocol, runtime_checkable

# The scratch directory the worker is permitted to write to under strict mode.
# Everything else is read-only or denied. Passed to the child via the
# environment so the wrapper profile and the self-test agree on it.
SCRATCH_ENV = "ABAX_SANDBOX_SCRATCH"
STRICT_ENV = "ABAX_SANDBOX_STRICT"


@runtime_checkable
class Confinement(Protocol):
    """A platform OS-confinement strategy. Stateless; safe to construct freely."""

    name: str

    def available(self) -> bool:
        """True if this platform primitive is present and usable *now*."""
        ...

    def wrap_argv(self, argv: "list[str]", scratch: str) -> "list[str]":
        """Wrap the worker's spawn command with an external launcher, or return
        ``argv`` unchanged for in-child strategies."""
        ...

    def child_env(self, env: "dict[str, str]", scratch: str) -> "dict[str, str]":
        """Adjust the child's environment (e.g. redirect TMPDIR into the
        scratch dir). Default strategies return it unchanged."""
        ...

    def apply_in_child(self, scratch: str) -> None:
        """Apply an in-child syscall restriction (Landlock/seccomp/token). A
        no-op for pure-wrapper strategies. Must raise on failure so the worker
        fails closed rather than running unconfined."""
        ...

    def describe(self) -> str:
        """One-line human description for the UI / logs."""
        ...

    # Optional: a strategy that cannot confine through a wrapped argv or an
    # in-child call (Windows AppContainer needs a bespoke ``CreateProcess``)
    # may define ``custom_spawn(argv, env, scratch, creationflags) -> proc``
    # returning a ``subprocess.Popen``-compatible object (``.stdin`` / ``.stdout``
    # / ``.stderr`` / ``.poll`` / ``.wait`` / ``.kill`` / ``.terminate`` /
    # ``._handle``). The bridge calls it in place of ``subprocess.Popen`` when
    # present. Strategies without it fall through to Popen(wrap_argv(argv)).


class _NullConfinement:
    """The 'no confinement available' sentinel — never runs user code."""

    name = "none"

    def available(self) -> bool:
        return False

    def wrap_argv(self, argv, scratch):
        return argv

    def child_env(self, env, scratch):
        return env

    def apply_in_child(self, scratch):
        return None

    def describe(self) -> str:
        return "no OS sandbox available on this platform"


def select_confinement() -> Confinement:
    """The best available confinement for this platform, or ``_NullConfinement``.

    Imports the platform module lazily so the wrong-OS module never loads.
    """
    try:
        if sys.platform == "win32":
            from . import sandbox_windows as mod
        elif sys.platform == "darwin":
            from . import sandbox_macos as mod
        elif sys.platform.startswith("linux"):
            from . import sandbox_linux as mod
        else:
            return _NullConfinement()
    except Exception:  # noqa: BLE001 - a broken platform module = no confinement
        return _NullConfinement()
    strat = mod.confinement()
    return strat if strat is not None and strat.available() else _NullConfinement()


def strict_requested() -> bool:
    """Whether strict mode is on for this process (env wins over the setting so
    the spawned worker inherits it)."""
    val = os.environ.get(STRICT_ENV)
    if val is not None:
        return val not in ("", "0", "false", "False")
    return False


# --- the fail-closed self-test ------------------------------------------------


class SandboxEscape(RuntimeError):
    """Raised when the confinement self-test detects an escape — the worker must
    refuse to run user code."""


def _can_write_outside(scratch: str) -> "str | None":
    """Attempt to write a file *outside* the scratch dir. Returns the path that
    was writable (an escape) or None if writing was denied everywhere tried."""
    candidates = []
    home = os.path.expanduser("~")
    if home and home != "~":
        candidates.append(os.path.join(home, ".abax_sandbox_escape_probe"))
    # The system temp dir (distinct from our scratch) and the CWD.
    for base in (os.environ.get("TMPDIR"), "/tmp", os.getcwd()):
        if base and os.path.abspath(base) != os.path.abspath(scratch or ""):
            candidates.append(os.path.join(base, ".abax_sandbox_escape_probe"))
    for path in candidates:
        try:
            with open(path, "w") as fh:
                fh.write("escape")
            os.remove(path)
            return path            # writing succeeded -> confinement failed
        except OSError:
            continue               # denied -> good
    return None


def _can_open_socket() -> bool:
    """Attempt an outbound network connection. True if the socket layer let us
    reach the connect() stage (an escape); False if creation/connect was denied
    by the sandbox."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False               # socket creation blocked -> confined
    try:
        s.settimeout(0.5)
        # A TEST-NET address (RFC 5737) that never answers: a *refused/timed out*
        # connect still means the network stack was reachable (escape); only an
        # OSError from the sandbox layer (EPERM/EACCES) at socket/connect means
        # confinement. Distinguish by errno.
        import errno

        try:
            s.connect(("192.0.2.1", 80))
        except OSError as exc:
            if exc.errno in (errno.EPERM, errno.EACCES):
                return False       # sandbox denied the connect -> confined
            return True            # reached the network (timeout/refused) -> escape
        return True                # connected (shouldn't happen) -> escape
    finally:
        s.close()


def selftest(scratch: str, *, check_network: bool = True) -> None:
    """Verify the active confinement actually confines. Raises
    :class:`SandboxEscape` on the first escape found.

    Called by the worker after :meth:`Confinement.apply_in_child`, before any
    user code runs. ``check_network=False`` is only for unit tests of the
    filesystem half.
    """
    escaped = _can_write_outside(scratch)
    if escaped is not None:
        raise SandboxEscape(f"filesystem not confined: wrote {escaped!r}")
    if check_network and _can_open_socket():
        raise SandboxEscape("network not confined: outbound socket reached the stack")
