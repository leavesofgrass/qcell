"""Out-of-process worker for isolated code execution (console, scripts, macros).

Spawned by :mod:`abax.gui.console.console_bridge` as a child process
(``python -c "from abax.console_worker import main; main()"``). It runs user code
in a separate process — crash isolation plus OS resource limits (see
:mod:`abax.proclimits`), and the seam for OS-level confinement later. The live
workbook is shipped in and out as an envelope each command, so the child never
touches the GUI.

This is the **single execution choke point** (sandbox Phase 1): the console
REPL, the script runner, and command macros all run here, each as its own op.

Wire protocol (length-prefixed JSON, 4-byte big-endian length):
  request  = {"op": "exec",   "code": str, "envelope": dict}            (default)
           | {"op": "script", "code": str, "path": str, "envelope": dict}
           | {"op": "macro",  "macro": str, "files": [str], "cursor": [r, c]|None,
              "envelope": dict}
  response = {"output": str, "error": str|None, "envelope": dict}
"""

from __future__ import annotations

import builtins
import code
import contextlib
import io
import json
import struct
import sys
import traceback

from .core.console_ns import build_namespace
from .core.richdisplay import best_text
from .core.workbook import Workbook


def _displayhook(value) -> None:
    """Echo an expression result using the rich-display protocol, so objects with
    ``_repr_markdown_`` / ``_repr_html_`` (e.g. a Sheet) print a readable table
    instead of an opaque ``repr``. Mirrors the stdlib hook otherwise (``None`` is
    silent; the result is bound to ``_``)."""
    if value is None:
        return
    builtins._ = value
    sys.stdout.write(best_text(value) + "\n")


class Worker:
    """Holds the persistent console namespace + interpreter across commands.

    ``handle`` is pure (no I/O), so it is unit-testable without a subprocess: the
    workbook arrives/returns as an envelope, user vars persist in ``ns``, and the
    workbook-facing helpers are rebound to each command's workbook.
    """

    def __init__(self) -> None:
        self.ns: dict = {}
        self.interp = code.InteractiveInterpreter(self.ns)

    def handle(self, source: str, envelope: dict) -> dict:
        wb = Workbook.from_envelope(envelope)
        self.ns.update(build_namespace(wb))     # rebind workbook helpers; keep user vars
        buf = io.StringIO()
        prev_hook = sys.displayhook
        sys.displayhook = _displayhook
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                self.interp.runsource(source, "<console>")
        except SystemExit:
            buf.write("(exit() is ignored in the console)\n")
        except BaseException:                    # never let user code kill the worker
            buf.write(traceback.format_exc())
        finally:
            sys.displayhook = prev_hook
        return {"output": buf.getvalue(), "error": None, "envelope": wb.to_envelope()}

    def handle_script(self, source: str, path: str, envelope: dict) -> dict:
        """Run a whole script file against the workbook, in a fresh namespace
        (scripts don't share the console's persistent variables)."""
        wb = Workbook.from_envelope(envelope)
        ns = build_namespace(wb, refresh=lambda: None)  # parent refreshes after
        ns["__name__"] = "abax_script"
        ns["__file__"] = path
        buf = io.StringIO()
        error = None
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exec(compile(source, path or "<script>", "exec"), ns)  # noqa: S102
        except BaseException:                    # report, never die
            error = traceback.format_exc()
        return {"output": buf.getvalue(), "error": error, "envelope": wb.to_envelope()}

    def handle_macro(self, name: str, files: list, cursor, envelope: dict) -> dict:
        """Load the given macro files into a fresh registry and run one macro
        against the workbook. The macro's ctx.log messages join the output."""
        from .macros import MacroError, MacroRegistry, load_macro_file, run_macro

        wb = Workbook.from_envelope(envelope)
        buf = io.StringIO()
        error = None
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                registry = MacroRegistry()
                for f in files or []:
                    load_macro_file(f, registry)
                at = tuple(cursor) if cursor else None
                ctx = run_macro(registry, name, wb, cursor=at)
                for message in ctx.messages:
                    buf.write(message + "\n")
        except MacroError as exc:
            error = str(exc)
        except BaseException:                    # report, never die
            error = traceback.format_exc()
        return {"output": buf.getvalue(), "error": error, "envelope": wb.to_envelope()}

    def dispatch(self, msg: dict) -> dict:
        op = msg.get("op", "exec")
        if op == "script":
            return self.handle_script(msg.get("code", ""), msg.get("path", ""),
                                      msg.get("envelope", {}))
        if op == "macro":
            return self.handle_macro(msg.get("macro", ""), msg.get("files", []),
                                     msg.get("cursor"), msg.get("envelope", {}))
        return self.handle(msg.get("code", ""), msg.get("envelope", {}))


def _read_frame(stream) -> bytes | None:
    header = stream.read(4)
    if not header or len(header) < 4:
        return None
    (length,) = struct.unpack(">I", header)
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            return None
        data += chunk
    return bytes(data)


def _write_frame(stream, payload: bytes) -> None:
    stream.write(struct.pack(">I", len(payload)))
    stream.write(payload)
    stream.flush()


def main() -> None:
    # Reserve the real stdout pipe for framing; discard stray prints (e.g. from
    # imports) so they can't corrupt the frame stream. (User code's own output is
    # captured per-command in handle().) Real errors still go to stderr.
    import os

    out = sys.stdout.buffer
    inp = sys.stdin.buffer
    sys.stdout = open(os.devnull, "w")

    # Sandbox Phase 2: cap memory / CPU / file size / process count so a
    # runaway is killed by the OS. (On Windows the parent assigns a Job
    # Object instead — see abax.proclimits and the console bridge.)
    from .proclimits import apply_posix_limits
    apply_posix_limits()

    worker = Worker()
    while True:
        raw = _read_frame(inp)
        if raw is None:
            break
        msg: dict = {}
        try:
            msg = json.loads(raw)
            resp = worker.dispatch(msg)
        except Exception:
            resp = {"output": traceback.format_exc(), "error": "worker error",
                    "envelope": msg.get("envelope", {})}
        _write_frame(out, json.dumps(resp).encode("utf-8"))


if __name__ == "__main__":
    main()
