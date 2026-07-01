"""Parent-side bridge to the isolated code-execution worker.

Spawns :mod:`abax.console_worker` as a child process and exchanges
length-prefixed JSON frames over its stdin/stdout. Pure subprocess/json (no Qt),
so it's testable headless. The worker runs user code out-of-process — a crash
there can't take down the GUI; the bridge just reports it and respawns next time.

The bridge is the parent half of the sandbox (Phases 1–2): every execution op
(console command, script file, command macro) goes through :meth:`_roundtrip`,
the worker is resource-limited (POSIX rlimits applied in the child; on Windows
the bridge assigns a **Job Object** with memory/CPU/process caps and
kill-on-job-close), and an optional wall-clock ``timeout`` arms a watchdog that
kills a hung worker. This is crash and resource isolation with the user's
privileges — **not** a security boundary (that is Phase 3, strict mode).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

from ...console_worker import _read_frame, _write_frame
from ...proclimits import assign_windows_job, close_windows_job

_BOOT = "from abax.console_worker import main; main()"


class ConsoleBridge:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._job = None  # Windows Job Object handle (keeps the limits alive)

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> None:
        env = dict(os.environ)
        # Replicate the parent's import path so the child finds `abax` — including
        # when running from a .pyz (whose path is on sys.path).
        paths = [p for p in sys.path if p]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _BOOT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, bufsize=0, **kwargs,
        )
        # Sandbox Phase 2 (Windows): cap the worker's memory / CPU time /
        # process count via a Job Object; kill-on-job-close ties the worker's
        # lifetime to this handle, so it dies with the GUI no matter what.
        if sys.platform == "win32":
            self._job = assign_windows_job(int(self._proc._handle))  # noqa: SLF001

    def _roundtrip(self, payload: dict, timeout: "float | None" = None) -> dict:
        """Send one request frame, read one response frame.

        On a worker death (crash, kill, resource-limit termination, watchdog
        timeout) returns ``{"crashed": True, ...}`` with the original envelope
        unchanged, so the caller leaves the workbook as-is.
        """
        if not self._alive():
            self._spawn()
        watchdog = None
        if timeout is not None and timeout > 0:
            watchdog = threading.Timer(timeout, self.interrupt)
            watchdog.daemon = True
            watchdog.start()
        try:
            _write_frame(self._proc.stdin, json.dumps(payload).encode("utf-8"))
            data = _read_frame(self._proc.stdout)
        except (BrokenPipeError, OSError):
            data = None
        finally:
            if watchdog is not None:
                watchdog.cancel()
        if data is None:
            reason = self._dead_reason()
            self._close_job()
            self._proc = None
            return {"output": "", "error": "the console process exited",
                    "envelope": payload.get("envelope", {}), "crashed": True,
                    "stderr": reason}
        return json.loads(data)

    def execute(self, source: str, envelope: dict,
                timeout: "float | None" = None) -> dict:
        """Run a console command in the worker against ``envelope``."""
        return self._roundtrip({"op": "exec", "code": source, "envelope": envelope},
                               timeout)

    def execute_script(self, source: str, path: str, envelope: dict,
                       timeout: "float | None" = None) -> dict:
        """Run a whole script file in the worker (fresh namespace)."""
        return self._roundtrip({"op": "script", "code": source, "path": path,
                                "envelope": envelope}, timeout)

    def execute_macro(self, name: str, files: list, cursor, envelope: dict,
                      timeout: "float | None" = None) -> dict:
        """Load ``files`` into a fresh registry in the worker and run a macro."""
        return self._roundtrip({"op": "macro", "macro": name, "files": list(files),
                                "cursor": list(cursor) if cursor else None,
                                "envelope": envelope}, timeout)

    def interrupt(self) -> None:
        """Kill the current worker to stop a runaway command. A blocked
        ``execute()`` then returns a crashed response (its read hits EOF), and the
        next call respawns a fresh worker. Safe to call from another thread."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def _dead_reason(self) -> str:
        proc = self._proc
        if proc is None:
            return ""
        try:
            proc.wait(timeout=1)
            if proc.stderr is not None:
                return proc.stderr.read().decode("utf-8", "replace").strip()
        except Exception:
            pass
        return ""

    def _close_job(self) -> None:
        job, self._job = self._job, None
        close_windows_job(job)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            self._close_job()
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        finally:
            self._close_job()
