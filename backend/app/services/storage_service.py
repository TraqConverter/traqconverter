"""Local-disk storage helpers.

Audit CRIT-6 fix: filenames coming from the client are no longer trusted
verbatim. We strip directory components, allow only a conservative
character set, and cap length. This prevents path traversal
(`../../etc/passwd`) and weird filesystem surprises (NULs, control chars,
Windows reserved names) on every disk write.
"""
import os
import re
import uuid

BASE_UPLOAD_DIR = "uploads"

# Conservative allow-list for filenames after sanitisation.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
# Windows reserved device names — never allow as a bare filename.
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_filename(filename: str | None, fallback: str = "upload") -> str:
    """Return a path-safe basename for `filename`.

    - Strips any directory components (defeats `../` traversal).
    - Replaces every non-allowlist char with `_`.
    - Caps length at 200 chars.
    - Replaces Windows reserved names with `fallback`.
    - Always returns a non-empty string.
    """
    if not filename:
        return fallback
    # Drop everything before the last `/` or `\` so attackers can't pass
    # `../../foo`.
    base = os.path.basename(filename.replace("\\", "/")).strip()
    if not base or base in (".", ".."):
        return fallback
    # Replace anything outside the allow list with `_`.
    cleaned = _SAFE_NAME_RE.sub("_", base)
    # Strip leading dots so we don't produce hidden files.
    cleaned = cleaned.lstrip(".") or fallback
    # Cap length (Windows max path component is 255; be conservative).
    cleaned = cleaned[:200]
    # Reject Windows reserved names case-insensitively.
    stem = cleaned.split(".", 1)[0].upper()
    if stem in _WIN_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned or fallback


def save_file_locally(file, team_id: str):
    project_id = str(uuid.uuid4())
    safe_team = safe_filename(str(team_id), fallback="team")
    safe_name = safe_filename(file.filename, fallback="upload")

    directory = os.path.join(BASE_UPLOAD_DIR, safe_team, project_id)
    os.makedirs(directory, exist_ok=True)

    file_path = os.path.join(directory, safe_name)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return file_path, project_id


def save_certification_file(file, user_id: str):
    safe_user = safe_filename(str(user_id), fallback="user")
    safe_name = safe_filename(file.filename, fallback="certification")

    directory = os.path.join(BASE_UPLOAD_DIR, "certifications", safe_user)
    os.makedirs(directory, exist_ok=True)

    file_path = os.path.join(directory, safe_name)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return file_path
