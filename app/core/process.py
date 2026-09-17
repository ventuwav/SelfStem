"""Cross-platform process liveness, shared by the parent-death watchdogs.

Lives here rather than in app/main.py so the demucs worker can use it without
importing FastAPI and the whole application: the worker is spawned per device
and its startup time is on the critical path of every separation.
"""

from __future__ import annotations

import os


def process_exists(pid: int) -> bool:
    """Whether a process with this pid is alive.

    Errs on the side of "alive": a permission error means the process is there
    but owned by someone else, and a watchdog must not shoot on ambiguity.
    """
    if pid <= 0:
        return False

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_INVALID_PARAMETER = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() != ERROR_INVALID_PARAMETER


_PARENT_POLL_SECONDS = 1.0


def _watch_parent(parent_pid: int) -> None:
    """Exit as soon as the process that spawned us is gone.

    A worker's stdin EOF only covers a parent that exits between jobs.
    Mid-inference the worker reads nothing, and the parent may have been killed
    in a way that ran no cleanup at all (SIGKILL, Force Quit, Task Manager, a
    crash). Without this the worker keeps running -- holding a GPU, in the
    demucs and vocal-split cases -- with nobody left to collect the result.

    os._exit rather than sys.exit: this runs on a daemon thread, and raising
    SystemExit there would not interrupt inference running in C code. Nothing
    here needs flushing.
    """
    import sys
    import time

    while True:
        if not process_exists(parent_pid):
            sys.stderr.write("@@ERROR@@parent process exited\n")
            sys.stderr.flush()
            os._exit(1)
        time.sleep(_PARENT_POLL_SECONDS)


def arm_parent_watchdog() -> None:
    """Start the parent-death watchdog if the parent asked for one.

    Shared by every long-running worker. It lived in demucs_worker.py, which is
    why vocal_split_worker and section_worker never had it: a Force-Quit during
    a vocal split orphaned an onnxruntime process holding the GPU, and a
    section pass outlived the parent whose TIMEOUT_SECTIONS was its only bound
    (#519).
    """
    import threading

    raw = os.environ.get("SELFSTEM_PARENT_PID", "").strip()
    if not raw:
        return
    try:
        parent_pid = int(raw)
    except ValueError:
        return
    if parent_pid <= 0 or parent_pid == os.getpid():
        return
    threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()
