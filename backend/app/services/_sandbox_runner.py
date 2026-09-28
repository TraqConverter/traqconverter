"""Child-process entry point for script_sandbox; run as `python -I -S _sandbox_runner.py config.json`."""
import json
import os
import resource
import sys

with open(sys.argv[1], encoding="utf-8") as _f:
    CONFIG = json.load(_f)

for _limit, _value in (
    (resource.RLIMIT_CPU, CONFIG["cpu_seconds"]),
    (resource.RLIMIT_FSIZE, 200 * 1024 * 1024),
    (resource.RLIMIT_NOFILE, 256),
    (resource.RLIMIT_CORE, 0),
    (getattr(resource, "RLIMIT_AS", None), 3 * 1024 * 1024 * 1024),
):
    if _limit is None:
        continue
    try:
        resource.setrlimit(_limit, (_value, _value))
    except (ValueError, OSError):
        pass

sys.path[:] = CONFIG["sys_path"]
sys.dont_write_bytecode = True

# Import everything a script normally needs before the hook is armed, so
# lazy imports don't have to be policed.
import docx  # noqa: E402,F401
import docx.enum.section  # noqa: E402,F401
import docx.enum.style  # noqa: E402,F401
import docx.enum.table  # noqa: E402,F401
import docx.enum.text  # noqa: E402,F401
import docx.oxml  # noqa: E402,F401
import docx.oxml.ns  # noqa: E402,F401
import docx.shared  # noqa: E402,F401

try:
    import PIL.Image  # noqa: E402,F401
except ImportError:
    pass

with open(CONFIG["script"], encoding="utf-8") as _f:
    CODE = compile(_f.read(), "rebuild.py", "exec")

READ_ROOTS = tuple(CONFIG["read_roots"])
WRITE_ROOTS = tuple(CONFIG["write_roots"])

DENIED_EVENT_PREFIXES = (
    "socket.", "subprocess.", "os.system", "os.exec", "os.posix_spawn",
    "os.spawn", "os.fork", "os.forkpty", "os.kill", "os.killpg", "os.setuid",
    "ctypes.", "pty.", "mmap.", "sys._getframe", "sys._current_frames",
    "sys.setprofile", "sys.settrace", "urllib.", "webbrowser.", "sqlite3.",
    "code.__new__", "function.__new__", "pickle.",
    "cpython.remote_debugger",
)
DENIED_IMPORTS = frozenset({
    "ctypes", "_ctypes", "cffi", "_cffi_backend", "_posixsubprocess",
    "socket", "_socket", "ssl", "_ssl", "subprocess", "multiprocessing",
    "_multiprocessing", "pty", "mmap", "gc", "_testcapi", "_testinternalcapi",
    "_xxsubinterpreters", "resource", "signal", "urllib.request", "http.client",
})
PATH_WRITE_EVENTS = frozenset({
    "os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate",
    "os.utime", "os.chflags", "os.lchown", "os.lchmod", "os.lchflags",
    "shutil.rmtree", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
})
PATH_WRITE_PAIR_EVENTS = frozenset({"os.rename", "os.link", "os.symlink", "shutil.move"})
PATH_READ_EVENTS = frozenset({"os.listdir", "os.scandir", "os.chdir", "glob.glob", "os.startfile"})
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _resolve(path):
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str):
        return None
    return os.path.realpath(path)


def _inside(path, roots):
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def _require(path, roots, event):
    resolved = _resolve(path)
    if resolved is None:
        if isinstance(path, int):
            return
        raise PermissionError(f"sandbox: {event} on unsupported path type")
    if not _inside(resolved, roots):
        raise PermissionError(f"sandbox: {event} outside allowed directories: {resolved}")


_IN_HOOK = False


def _hook(event, args):
    global _IN_HOOK
    if _IN_HOOK:
        return
    _IN_HOOK = True
    try:
        if event == "open":
            path, mode, flags = args
            writing = (mode is not None and any(c in mode for c in "wax+")) or (
                mode is None and isinstance(flags, int) and flags & WRITE_FLAGS
            )
            _require(path, WRITE_ROOTS if writing else READ_ROOTS + WRITE_ROOTS, "open")
        elif event == "import":
            name = args[0]
            if name in DENIED_IMPORTS or name.split(".", 1)[0] in DENIED_IMPORTS:
                raise ImportError(f"sandbox: import of {name} is blocked")
        elif event in PATH_WRITE_EVENTS:
            _require(args[0], WRITE_ROOTS, event)
        elif event in PATH_WRITE_PAIR_EVENTS:
            _require(args[0], WRITE_ROOTS, event)
            _require(args[1], WRITE_ROOTS, event)
        elif event in PATH_READ_EVENTS:
            if args and args[0] is not None:
                _require(args[0], READ_ROOTS + WRITE_ROOTS, event)
        elif event.startswith(DENIED_EVENT_PREFIXES):
            raise PermissionError(f"sandbox: {event} is blocked")
    finally:
        _IN_HOOK = False


sys.addaudithook(_hook)
exec(CODE, {"__name__": "__main__"})
