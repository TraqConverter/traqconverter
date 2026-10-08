"""The project's original as page images: normalized to a PDF once, rendered per page and scale, cached on disk."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_MAX_AGE = timedelta(days=7)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")
MAX_RENDER_EDGE = 4000
MIN_SCALE, MAX_SCALE = 0.25, 4.0
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cache_root() -> Path:
    return Path(os.getenv("SOURCE_PAGE_CACHE") or Path(tempfile.gettempdir()) / "tq_source_pages")


def _dir(project) -> Path:
    digest = hashlib.sha1((project.file_path or "").encode()).hexdigest()[:16]
    return cache_root() / str(project.id) / digest


def drop(project_id) -> None:
    shutil.rmtree(cache_root() / str(project_id), ignore_errors=True)


def purge_stale(max_age: timedelta = CACHE_MAX_AGE, now: Optional[float] = None) -> int:
    """Remove project folders nothing was written to for max_age; each instance cleans its own disk."""
    root = cache_root()
    if not root.is_dir():
        return 0
    cutoff = (now or time.time()) - max_age.total_seconds()
    removed = 0
    for folder in root.iterdir():
        try:
            if not folder.is_dir():
                continue
            newest = max((p.stat().st_mtime for p in folder.rglob("*")), default=folder.stat().st_mtime)
            if newest < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        except OSError:
            logger.warning("Couldn't check cached pages in %s", folder)
    return removed


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def source_kind(file_name: str) -> str:
    name = (file_name or "").lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(IMAGE_EXTS):
        return "image"
    if name.endswith(".docx"):
        return "docx"
    return "other"


def _image_to_pdf(data: bytes) -> bytes:
    import fitz
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = fitz.open()
    # One point per pixel, so boxes read in image pixels are page coordinates as they are.
    page = doc.new_page(width=img.width, height=img.height)
    page.insert_image(page.rect, stream=buf.getvalue())
    out = doc.tobytes()
    doc.close()
    return out


def _build_pdf(project) -> Optional[bytes]:
    from app.services.document_editor import _download

    kind = source_kind(project.file_name)
    if kind == "other":
        return None
    data = _download(project.file_path)
    if kind == "pdf":
        import fitz

        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass or not len(doc):
                return None
        return data
    if kind == "image":
        return _image_to_pdf(data)
    from app.services.export_service import _convert_docx_to_pdf

    return _convert_docx_to_pdf(data)


def source_pdf(project) -> Optional[bytes]:
    folder = _dir(project)
    pdf_path, missing = folder / "source.pdf", folder / "unavailable"
    with _lock(str(folder)):
        if pdf_path.exists():
            return pdf_path.read_bytes()
        if missing.exists():
            return None
        folder.mkdir(parents=True, exist_ok=True)
        try:
            pdf = _build_pdf(project)
        except Exception:
            logger.exception("Couldn't prepare the source pages (project=%s)", project.id)
            return None
        if not pdf:
            missing.write_text("1")
            return None
        tmp = pdf_path.with_suffix(".tmp")
        tmp.write_bytes(pdf)
        tmp.replace(pdf_path)
        return pdf


def page_info(project) -> dict:
    """{"available", "count", "pages": [{"width", "height"}]} in PDF points."""
    folder = _dir(project)
    info_path = folder / "info.json"
    if info_path.exists():
        try:
            return json.loads(info_path.read_text())
        except ValueError:
            pass
    pdf = source_pdf(project)
    if not pdf:
        return {"available": False, "count": 0, "pages": []}
    import fitz

    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pages = [{"width": round(p.rect.width, 2), "height": round(p.rect.height, 2)} for p in doc]
    info = {"available": True, "count": len(pages), "pages": pages, "kind": source_kind(project.file_name)}
    folder.mkdir(parents=True, exist_ok=True)
    info_path.write_text(json.dumps(info))
    return info


def normalize_scale(scale: float) -> float:
    scale = min(MAX_SCALE, max(MIN_SCALE, float(scale or 1)))
    return round(scale * 4) / 4


def render_page(project, index: int, scale: float, fmt: str = "png") -> Optional[bytes]:
    """Page `index` (0-based) at `scale` pixels per point, capped so the long edge stays under MAX_RENDER_EDGE."""
    info = page_info(project)
    if not info["available"] or not 0 <= index < info["count"]:
        return None
    scale = normalize_scale(scale)
    size = info["pages"][index]
    scale = min(scale, MAX_RENDER_EDGE / max(size["width"], size["height"], 1))
    path = _dir(project) / f"page-{index}-{scale:.3f}.{fmt}"
    if path.exists():
        return path.read_bytes()
    pdf = source_pdf(project)
    if not pdf:
        return None
    import fitz

    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        data = pix.tobytes("png") if fmt == "png" else pix.tobytes("jpeg", jpg_quality=85)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data


def page_jpeg_for_model(project, index: int, long_edge: int = 1568, max_pixels: int = 1_150_000) -> Optional[tuple[bytes, int, int]]:
    """JPEG of a page sized for a vision call, with its pixel width and height."""
    info = page_info(project)
    if not info["available"] or not 0 <= index < info["count"]:
        return None
    size = info["pages"][index]
    # Larger images are downscaled server-side, and the model's pixel boxes then refer to that smaller frame.
    scale = min(long_edge / max(size["width"], size["height"], 1), (max_pixels / max(size["width"] * size["height"], 1)) ** 0.5)
    pdf = source_pdf(project)
    if not pdf:
        return None
    import fitz

    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("jpeg", jpg_quality=85), pix.width, pix.height


def text_layer(project) -> str:
    pdf = source_pdf(project)
    if not pdf:
        return ""
    import fitz

    with fitz.open(stream=pdf, filetype="pdf") as doc:
        return "\n".join(p.get_text() for p in doc)
