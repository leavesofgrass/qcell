"""OS resource limits for the code-execution worker (sandbox Phase 2).

Caps the worker process's memory, CPU time, file size and process count so a
runaway command, allocation bomb, or fork bomb is killed by the OS instead of
wedging the machine. Two halves, both best-effort:

* :func:`apply_posix_limits` — called **inside the child** right after it
  starts (POSIX only): ``resource.setrlimit`` for ``RLIMIT_AS`` /
  ``RLIMIT_CPU`` / ``RLIMIT_FSIZE`` / ``RLIMIT_NPROC``.
* :func:`assign_windows_job` — called **from the parent** right after spawn
  (Windows only): a Job Object with a per-process memory cap, a user-mode CPU
  time cap, an active-process cap, and *kill-on-job-close* — so the worker
  (and anything it spawned) dies with the bridge, even if the GUI crashes.

Limits come from environment variables so tests and power users can tune them
(``ABAX_WORKER_MEM_MB``, ``ABAX_WORKER_CPU_S``, ``ABAX_WORKER_PROCS``); the
defaults are deliberately generous — this is a workstation that legitimately
crunches data, and the caps only need to stop *unbounded* runaways.

Per the sandbox design's honesty clause: resource limits are crash/hang
containment, **not** a security boundary — the worker still runs with the
user's privileges. Filesystem/network confinement is Phase 3.
"""

from __future__ import annotations

import os
import sys

# Generous defaults: big enough for real data-science work, small enough that
# an unbounded runaway is stopped long before the machine swaps to death.
DEFAULT_MEM_MB = 4096       # address-space / committed-memory cap
DEFAULT_CPU_S = 600         # user-mode CPU seconds per command process
DEFAULT_FSIZE_MB = 1024     # largest file the worker may write (POSIX only)
DEFAULT_PROCS = 16          # active processes in the job (Windows only)
DEFAULT_NPROC = 4096        # per-user process cap while the worker runs (POSIX)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return default


def limits_from_env() -> "dict[str, int]":
    return {
        "mem_mb": _env_int("ABAX_WORKER_MEM_MB", DEFAULT_MEM_MB),
        "cpu_s": _env_int("ABAX_WORKER_CPU_S", DEFAULT_CPU_S),
        "fsize_mb": _env_int("ABAX_WORKER_FSIZE_MB", DEFAULT_FSIZE_MB),
        "procs": _env_int("ABAX_WORKER_PROCS", DEFAULT_PROCS),
        "nproc": _env_int("ABAX_WORKER_NPROC", DEFAULT_NPROC),
    }


# --- POSIX: rlimits applied in the child -------------------------------------


def _set_rlimit(res, want: int) -> None:
    """Lower a limit to ``want`` (never above the current hard limit)."""
    import resource

    soft, hard = resource.getrlimit(res)
    cap = want if hard == resource.RLIM_INFINITY else min(want, hard)
    try:
        resource.setrlimit(res, (cap, hard if hard != resource.RLIM_INFINITY else cap))
    except (ValueError, OSError):
        pass  # best-effort: an unsupported/privileged limit is skipped


def apply_posix_limits() -> bool:
    """Apply rlimits in the current (child) process. Returns True if applied.

    A zero/negative value from the environment disables that limit.
    """
    if sys.platform == "win32":
        return False
    try:
        import resource
    except ImportError:  # pragma: no cover - resource is POSIX-only
        return False
    lim = limits_from_env()
    if lim["mem_mb"] > 0:
        _set_rlimit(resource.RLIMIT_AS, lim["mem_mb"] * 1024 * 1024)
    if lim["cpu_s"] > 0:
        # soft = the cap (SIGXCPU); hard slightly above so the signal can land.
        _set_rlimit(resource.RLIMIT_CPU, lim["cpu_s"])
    if lim["fsize_mb"] > 0:
        _set_rlimit(resource.RLIMIT_FSIZE, lim["fsize_mb"] * 1024 * 1024)
    if lim["nproc"] > 0 and hasattr(resource, "RLIMIT_NPROC"):
        _set_rlimit(resource.RLIMIT_NPROC, lim["nproc"])
    return True


# --- Windows: a Job Object assigned from the parent ---------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
    _JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    _JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def assign_windows_job(process_handle: int) -> "int | None":
        """Create a Job Object with the env-configured limits and assign the
        process to it. Returns the job handle (keep it alive; closing it kills
        the job because of KILL_ON_JOB_CLOSE), or None if anything failed."""
        lim = limits_from_env()
        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if lim["mem_mb"] > 0:
            flags |= _JOB_OBJECT_LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = lim["mem_mb"] * 1024 * 1024
        if lim["cpu_s"] > 0:
            flags |= _JOB_OBJECT_LIMIT_PROCESS_TIME
            # user-mode time, in 100-nanosecond ticks
            info.BasicLimitInformation.PerProcessUserTimeLimit = lim["cpu_s"] * 10_000_000
        if lim["procs"] > 0:
            flags |= _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = lim["procs"]
        info.BasicLimitInformation.LimitFlags = flags
        ok = kernel32.SetInformationJobObject(
            job, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if ok:
            ok = kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process_handle))
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return job

    def close_windows_job(job: "int | None") -> None:
        if job:
            try:
                ctypes.windll.kernel32.CloseHandle(job)
            except Exception:
                pass
else:  # POSIX: the job-object API is a no-op

    def assign_windows_job(process_handle: int) -> "int | None":  # noqa: ARG001
        return None

    def close_windows_job(job: "int | None") -> None:  # noqa: ARG001
        return None
