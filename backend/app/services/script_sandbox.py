"""Runs Claude-written python-docx scripts; the script is attacker-influenced because Claude read the upload."""
from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

ALLOWED_IMPORT_ROOTS = frozenset({
    "docx", "PIL",
    "io", "re", "math", "copy", "datetime", "json", "collections",
    "itertools", "functools", "typing", "string", "textwrap", "decimal",
    "fractions", "statistics", "enum", "dataclasses", "unicodedata",
    "os", "pathlib", "base64", "random",
})

BANNED_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr",
    "vars", "globals", "locals", "breakpoint", "input", "memoryview", "help",
    "exit", "quit", "__builtins__", "__loader__", "__spec__", "classmethod",
})

# lxml's C-level file I/O bypasses the child's audit hook, so its entry points are banned here
BANNED_ATTRS = frozenset({
    "etree", "lxml", "getroottree", "xinclude", "XInclude", "XSLT", "xslt",
    "write", "write_c14n", "parse", "iterparse", "XMLParser", "HTMLParser",
    "ElementTree", "set_default_parser", "resolvers", "docinfo",
    "gi_frame", "gi_code", "cr_frame", "cr_code", "ag_frame", "ag_code",
    "f_globals", "f_locals", "f_builtins", "f_back", "f_code", "tb_frame",
    "tb_next", "system", "popen", "fork", "forkpty", "kill", "killpg",
    "execv", "execve", "execl", "execle", "execlp", "execvp", "execvpe",
    "spawnl", "spawnv", "spawnve", "posix_spawn", "posix_spawnp",
    "environ", "putenv", "unsetenv", "setuid", "setgid", "chroot",
    "attrgetter", "methodcaller", "modules", "_getframe",
})

ALLOWED_DUNDERS = frozenset({"__init__"})

_RUNNER = Path(__file__).with_name("_sandbox_runner.py")
NOBODY_UID = 65534
NOBODY_GID = 65534


def validate_script(script: str) -> None:
    """Raise ValueError naming the first construct the sandbox won't run."""
    try:
        tree = ast.parse(script)
    except SyntaxError as e:
        raise ValueError(f"Script has a syntax error: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise ValueError("Relative imports are not allowed")
            _check_import(node.module or "")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            raise ValueError(f"Use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            _check_attr(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in node.decorator_list:
                if isinstance(d, ast.Name) and d.id in BANNED_NAMES:
                    raise ValueError(f"Use of '{d.id}' is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise ValueError("global/nonlocal statements are not allowed")


def _check_import(module: str) -> None:
    root = module.split(".", 1)[0]
    if root not in ALLOWED_IMPORT_ROOTS:
        raise ValueError(f"Import of '{module}' is not allowed")
    if any(part in BANNED_ATTRS for part in module.split(".")):
        raise ValueError(f"Import of '{module}' is not allowed")


def _check_attr(attr: str) -> None:
    if attr.startswith("__") and attr.endswith("__") and attr not in ALLOWED_DUNDERS:
        raise ValueError(f"Access to '{attr}' is not allowed")
    if attr in BANNED_ATTRS:
        raise ValueError(f"Access to '.{attr}' is not allowed")


def _library_paths() -> list[str]:
    paths = {sysconfig.get_paths()[k] for k in ("stdlib", "platstdlib", "purelib", "platlib")}
    prefixes = {os.path.realpath(sys.prefix), os.path.realpath(sys.base_prefix)}
    # Interpreter-owned entries only (stdlib, lib-dynload, site-packages); never the app directory.
    paths.update(
        p for p in sys.path
        if p and (
            "site-packages" in p
            or "dist-packages" in p
            or any(os.path.realpath(p).startswith(pre + os.sep) for pre in prefixes)
        )
    )
    return sorted({os.path.realpath(p) for p in paths if os.path.isdir(p)})


def _chown_tree(root: Path, uid: int, gid: int) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        os.chown(dirpath, uid, gid)
        for name in filenames:
            os.chown(os.path.join(dirpath, name), uid, gid)


def run_script(
    script: str,
    work_dir: Path,
    write_dirs: Iterable[Path],
    timeout_seconds: int,
) -> subprocess.CompletedProcess:
    """Validate and execute `script` with cwd=work_dir. Returns the completed process."""
    validate_script(script)

    work_dir = Path(work_dir)
    write_roots = sorted({os.path.realpath(str(p)) for p in [work_dir, *write_dirs]})
    lib_paths = _library_paths()

    script_path = work_dir / "rebuild.py"
    script_path.write_text(script + "\n", encoding="utf-8")
    config_path = work_dir / "sandbox.json"
    config_path.write_text(json.dumps({
        "script": str(script_path),
        "sys_path": lib_paths,
        "read_roots": lib_paths + [os.path.realpath(sys.base_prefix), os.path.realpath(sys.prefix)],
        "write_roots": write_roots,
        "cpu_seconds": timeout_seconds + 5,
    }), encoding="utf-8")

    drop_privileges = hasattr(os, "geteuid") and os.geteuid() == 0
    if drop_privileges:
        for root in write_roots:
            _chown_tree(Path(root), NOBODY_UID, NOBODY_GID)

    def _preexec() -> None:
        os.setsid()
        if drop_privileges:
            os.setgroups([])
            os.setgid(NOBODY_GID)
            os.setuid(NOBODY_UID)

    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": str(work_dir)}
    return subprocess.run(
        [sys.executable, "-I", "-S", str(_RUNNER), str(config_path)],
        capture_output=True,
        env=env,
        cwd=str(work_dir),
        timeout=timeout_seconds,
        preexec_fn=_preexec,
        close_fds=True,
    )
