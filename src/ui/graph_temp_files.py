"""Paths and lifecycle for generated graph pages in the system temp directory."""

import ctypes
import os
import re
import tempfile
from pathlib import Path


_PAGE_NAME = re.compile(r"echograph-(?:graph|tavern-placeholder)-(\d+)\.html\Z")


def graph_page_path(pid=None):
    return Path(tempfile.gettempdir()) / f"echograph-graph-{os.getpid() if pid is None else pid}.html"


def tavern_placeholder_path(pid=None):
    return Path(tempfile.gettempdir()) / f"echograph-tavern-placeholder-{os.getpid() if pid is None else pid}.html"


def _pid_running(pid):
    if pid == os.getpid():
        return True
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87  # Only ERROR_INVALID_PARAMETER proves absence.
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cleanup_stale_graph_pages():
    """Remove only app page files whose numeric PID has exited."""
    temp_dir = Path(tempfile.gettempdir())
    for path in temp_dir.iterdir():
        match = _PAGE_NAME.fullmatch(path.name)
        if match and path.is_file() and not _pid_running(int(match.group(1))):
            try:
                path.unlink()
            except OSError:
                pass


def cleanup_current_graph_pages():
    """Remove this process's generated pages during ordinary app cleanup."""
    for path in (graph_page_path(), tavern_placeholder_path()):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
