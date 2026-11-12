"""POSIX seams, sealed for Windows.

Three things the pipeline leans on do not exist on Windows: an advisory
``flock`` over a lock file, ``preexec_fn`` / ``os.nice`` for job priority, and
``resource.getrusage`` for the JOB_CPU line. Each is used for exactly one
purpose here, so each gets a direct Windows equivalent rather than a stub:

* ``try_lock`` / ``unlock`` / ``try_lock_fd`` — ``msvcrt.locking`` on one byte
  at offset 0. The OS releases it when the handle closes, which is the same
  crash safety ``flock`` gives a dead process. Same contract as before:
  non-blocking, ``False`` means "somebody else holds it".
* ``child_priority_kwargs`` — ``preexec_fn`` is not a Popen argument on
  Windows; ``BELOW_NORMAL_PRIORITY_CLASS`` is the same intent (the job yields
  to the API answering a user).
* ``cpu_times`` — process CPU seconds, children included where the OS can
  report them.

Everything falls back to the POSIX implementation on Linux/macOS, so the same
source file runs in the Docker image and on the host.
"""
import os
import subprocess
import time

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:  # pragma: no cover - exercised only on Windows
    import msvcrt


# --------------------------------------------------------------------------- #
# Lock files (was: fcntl.flock)
# --------------------------------------------------------------------------- #
def try_lock(fh):
    """Exclusive non-blocking lock on an open file object. False = busy."""
    if IS_WINDOWS:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, ValueError):
            return False
    import fcntl
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def unlock(fh):
    """Release a lock taken by :func:`try_lock`. Never raises."""
    if IS_WINDOWS:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except (OSError, ValueError):
            pass
        return
    import fcntl
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        pass


def try_lock_fd(fd):
    """Exclusive non-blocking lock on a raw file descriptor. False = busy."""
    if IS_WINDOWS:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Child process priority (was: preexec_fn + os.nice)
# --------------------------------------------------------------------------- #
def child_priority_kwargs(nice_value):
    """Popen kwargs that make a job yield to interactive work.

    ``nice_value`` 0 (or unset) means "normal priority": nothing is passed.
    """
    try:
        nice_value = int(nice_value or 0)
    except (TypeError, ValueError):
        nice_value = 0
    if nice_value <= 0:
        return {}
    if IS_WINDOWS:
        return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {"preexec_fn": lambda: os.nice(nice_value)}


def lower_priority(nice_value):
    """Lower THIS process's priority (Windows: priority class, POSIX: nice)."""
    if IS_WINDOWS:
        try:
            import ctypes
            BELOW_NORMAL = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL)
        except Exception:
            pass
        return
    try:
        os.nice(int(nice_value or 0))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# CPU accounting (was: resource.getrusage)
# --------------------------------------------------------------------------- #
def cpu_times():
    """(own_cpu_seconds, children_cpu_seconds) for the JOB_CPU log line."""
    if IS_WINDOWS:
        # time.process_time() is this process only; Windows cannot aggregate
        # child CPU without a job object, and the number is diagnostic only.
        return time.process_time(), 0.0
    import resource
    own = resource.getrusage(resource.RUSAGE_SELF)
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (own.ru_utime + own.ru_stime), (kids.ru_utime + kids.ru_stime)


# --------------------------------------------------------------------------- #
# File replace / unlink (POSIX lets you rename an open file; Windows does not)
# --------------------------------------------------------------------------- #
def replace_with_retry(src, dst, tries=20, delay=0.15):
    """``os.replace`` with a short retry window.

    On Windows a just-exited writer (ffmpeg) or the AV scanner can still hold
    a handle for a moment, and the rename fails with WinError 32. POSIX never
    shows this, so the pipeline never needed the retry.
    """
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)


def unlink_with_retry(path, tries=20, delay=0.15):
    """``os.remove`` with the same retry window. Missing file is success."""
    for attempt in range(tries):
        try:
            os.remove(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)

