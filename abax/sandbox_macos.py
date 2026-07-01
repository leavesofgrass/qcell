"""macOS OS-confinement strategy for the code-execution worker (sandbox Phase 3).

This module implements the **wrapper** model of :mod:`abax.sandbox` on macOS
using Apple's ``sandbox-exec`` and the **Sandbox Profile Language (SBPL)** — a
Scheme-like DSL evaluated by the kernel's TrustedBSD MAC sandbox (Seatbelt).

``sandbox-exec`` is the only confinement primitive on macOS that needs **no
entitlements** and no code-signing: any process can launch a child under an
SBPL profile. Apple has marked ``sandbox-exec`` and the ``-p`` inline-profile
flag *deprecated* since macOS 10.10, but they remain present and functional on
every current macOS (through at least macOS 15), and there is no supported
no-entitlement replacement. We accept the deprecation with eyes open because
Phase 3's fail-closed :func:`abax.sandbox.selftest` runs inside the confined
worker and will refuse to execute user code if the profile ever stops
confining — so a broken/removed ``sandbox-exec`` degrades to "refuse", never to
"run unconfined".

The strategy is a *pure wrapper*: the parent prepends
``/usr/bin/sandbox-exec -p <profile> ...`` to the worker's argv
(:meth:`Confinement.wrap_argv`); nothing is applied inside the child
(:meth:`Confinement.apply_in_child` is a no-op).

Design of the emitted profile (see :func:`build_profile`):

* ``(deny default)`` — start from a total-deny baseline. Anything we do not
  explicitly ``allow`` is denied, including **all** network operations. We
  never emit ``(allow network-* ...)``, so outbound sockets are blocked.
* Broad ``(allow file-read* ...)`` — reading is *not* the threat model here;
  data **exfiltration via the network** is, and that is denied above. Allowing
  broad reads is what lets CPython import the stdlib, ``abax``, and any
  installed packages from arbitrary prefixes (system Python, Homebrew,
  pyenv, venvs) without enumerating every path. This is a deliberate
  simplicity/robustness trade-off, documented here.
* Narrow ``(allow file-write* (subpath "<scratch>"))`` plus a short allowlist
  of harmless device/ipc writes — the worker may write **only** under its
  scratch dir (and ``/dev/null`` etc.). Every other write is denied by the
  baseline.

This module imports cleanly on **any** OS (it is imported during test
collection on Windows/Linux); all darwin-specific work is guarded inside
methods via :meth:`MacSandboxExec.available`.
"""

from __future__ import annotations

import os
import sys

# Canonical path to the launcher. It has lived here on every macOS release; we
# also feature-detect its presence in `available()` rather than trusting this.
SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _sbpl_string(path: str) -> str:
    """Escape *path* for embedding inside an SBPL double-quoted string literal.

    SBPL string literals are C-like: backslash and double-quote must be
    escaped. Scratch paths are app-controlled (a temp dir) rather than
    attacker-controlled, but we escape defensively so a path containing a quote
    or backslash cannot break out of the string and inject profile syntax.
    """
    return path.replace("\\", "\\\\").replace('"', '\\"')


def build_profile(scratch: str) -> str:
    """Build the SBPL profile string that confines the worker.

    Returns a complete ``(version 1)`` profile that denies everything by
    default, permits the reads/process ops CPython needs to boot and import,
    permits writes **only** under *scratch* (plus a few harmless devices), and
    — by never allowing any ``network-*`` operation — denies all network
    access. Pure string building; safe to call and unit-test on any OS.
    """
    scratch_abs = os.path.abspath(scratch) if scratch else scratch
    s = _sbpl_string(scratch_abs)
    # Each clause is commented with what it permits and why it is required.
    # Mechanism: Apple SBPL / sandbox-exec (Seatbelt / TrustedBSD MAC).
    return f"""\
(version 1)

;; Total-deny baseline. Anything not explicitly allowed below is denied,
;; including ALL network operations (no network allow rule is ever emitted),
;; so outbound sockets — the exfiltration path — are blocked.
(deny default)

;; --- process lifecycle: let the interpreter start and manage itself --------
;; CPython forks (multiprocessing/subprocess machinery) and execs helpers.
(allow process-fork)
(allow process-exec)
;; The worker may signal only itself (e.g. faulthandler / timeouts), not others.
(allow signal (target self))

;; --- interpreter bring-up --------------------------------------------------
;; sysctl reads: CPython probes CPU count, page size, etc. at startup.
(allow sysctl-read)
;; Mach lookups to core system services are needed just to reach main(): the
;; dynamic loader and libSystem talk to these before any user code runs.
(allow mach-lookup)
;; POSIX shared-memory / IPC status reads used by parts of libSystem.
(allow ipc-posix-shm)

;; --- filesystem: read broadly, write only into the scratch dir -------------
;; Broad READ is intentional. Reading is not the threat model — exfiltration
;; over the (denied) network is. Allowing all reads lets CPython import the
;; stdlib, abax, and site-packages from ANY prefix (system / Homebrew / pyenv /
;; venv) without enumerating paths. Nothing read can leave the sandbox.
(allow file-read*)
;; Metadata-only ops are covered by file-read* but spelled out for clarity.
(allow file-read-metadata)

;; WRITE is confined to the scratch subtree — the one place the worker may
;; persist anything. Every other write is denied by (deny default) above.
(allow file-write* (subpath "{s}"))

;; A tiny allowlist of harmless device/pipe writes the interpreter needs:
;;  - /dev/null, /dev/zero: discard/zero sinks used pervasively.
;;  - /dev/random, /dev/urandom: os.urandom / secrets entropy source.
;;  - stdout/stderr are pipes handed to us by the parent; ttys cover the
;;    interactive case. This does not widen the FS surface beyond devices.
(allow file-write* (literal "/dev/null"))
(allow file-write* (literal "/dev/zero"))
(allow file-write* (literal "/dev/random"))
(allow file-write* (literal "/dev/urandom"))
(allow file-write* (regex #"^/dev/tty"))
(allow file-write-data (literal "/dev/stdout"))
(allow file-write-data (literal "/dev/stderr"))
(allow file-ioctl (regex #"^/dev/"))
"""


class MacSandboxExec:
    """macOS confinement via ``sandbox-exec`` + an inline SBPL profile.

    Pure wrapper strategy: :meth:`wrap_argv` prepends the launcher and profile;
    :meth:`apply_in_child` is a no-op. See the module docstring for the
    ``sandbox-exec`` deprecation caveat and why it is acceptable under Phase 3's
    fail-closed self-test.
    """

    name = "macos-sandbox-exec"

    def available(self) -> bool:
        """True only on macOS with the ``sandbox-exec`` binary present.

        Real feature detection: we check the actual binary is an executable
        file, not merely that we are on darwin.
        """
        if sys.platform != "darwin":
            return False
        return os.path.isfile(SANDBOX_EXEC) and os.access(SANDBOX_EXEC, os.X_OK)

    def wrap_argv(self, argv: "list[str]", scratch: str) -> "list[str]":
        """Prepend ``sandbox-exec -p <profile>`` to *argv*.

        The profile is passed **inline** via ``-p`` (supported by
        ``sandbox-exec``) rather than written to a file: no temp file to create,
        secure, and clean up, and no window where a partial file could be read.
        """
        profile = build_profile(scratch)
        return [SANDBOX_EXEC, "-p", profile, *argv]

    def child_env(self, env: "dict[str, str]", scratch: str) -> "dict[str, str]":
        """Point ``TMPDIR`` at the scratch dir so temp files land where writes
        are permitted rather than in the (write-denied) system temp dir."""
        out = dict(env)
        if scratch:
            out["TMPDIR"] = scratch
        return out

    def apply_in_child(self, scratch: str) -> None:
        """No-op: this is a pure wrapper strategy (confinement is applied by the
        parent via :meth:`wrap_argv`, before the worker's ``main`` runs)."""
        return None

    def describe(self) -> str:
        return (
            "macOS sandbox-exec (SBPL): confines filesystem writes to the "
            "scratch dir and denies all network access"
        )


def confinement() -> "MacSandboxExec | None":
    """Module-level entry point used by :func:`abax.sandbox.select_confinement`.

    Returns the strategy instance on all platforms (the caller checks
    :meth:`MacSandboxExec.available`), so importing this module never fails on a
    non-darwin host.
    """
    return MacSandboxExec()
