"""Watermarked, partly blurred page images of a protected link's snapshot, shown to the client until it's unlocked."""
from __future__ import annotations

import io
import logging
import math
import re
import shutil
import tempfile
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.delivery_link import DeliveryLink
from app.services import cert_locale

logger = logging.getLogger(__name__)

DPI = 90
_SCALE = DPI / 72
_PAD = 3
_WORD_BLUR = 8
_PAGE_BLUR = 12

# Words that are capitalised for reasons other than being a name: headings, labels, function words.
COMMON_WORDS = frozenset(
    """
    a an the this that these those i we you he she it they my our your his her its their
    in on at of for to from by with and or as if is was are were be been not no yes all any
    mr mrs ms dr sig sig.ra signor signora dott prof
    date name names surname first last given page pages document documents certificate certificates
    certified certification certify translation translations translator translated original copy true
    birth death marriage divorce place born died married residence resident address citizen citizenship
    nationality sex male female father mother son daughter husband wife spouse child children parents
    republic kingdom state states united city town municipality province region county country
    office registry register registrar civil status official officer government ministry department
    court council authority embassy consulate police school university faculty degree diploma
    signature signed seal stamp issued issue extract act number no reference ref code series section
    part year day month time notes note annotations remarks total amount
    january february march april may june july august september october november december
    monday tuesday wednesday thursday friday saturday sunday
    source target language languages statement declaration translator's accuracy
    il lo la le gli un una uno di da del della dei delle nel nella per con su tra fra e o che
    comune provincia regione repubblica italiana italiano stato civile ufficio ufficiale anagrafe
    atto atti estratto certificato certificata certificazione traduzione traduttore traduttrice
    documento originale copia pagina pagine firma timbro data nome cognome nascita luogo nato nata
    morte matrimonio padre madre sesso cittadinanza residenza indirizzo sindaco registro numero
    anno mese giorno note annotazioni
    italy italia france germany spain portugal greece romania poland albania ukraine russia china india
    brazil america england britain ireland scotland wales europe european union
    gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre
    """.split()
) | frozenset(n.lower() for names in cert_locale._NAMES.values() for n in names)

_EDGE_PUNCT = ".,;:!?()[]{}\"'«»“”‘’<>*"
_SENTENCE_END = (".", "!", "?")
_SHORT_BLOCK = 4
_EXTRA_CERT_TITLES = (
    "CERTIFICATE OF TRANSLATION",
    "CERTIFICATE OF ACCURACY",
    "TRANSLATOR'S DECLARATION",
    "TRANSLATOR’S DECLARATION",
    "DICHIARAZIONE DEL TRADUTTORE",
)


def _bare(word: str) -> str:
    return word.strip(_EDGE_PUNCT)


def _capitalised(word: str) -> bool:
    """'Rossi', 'ROSSI', 'De-Luca', "D'Amico"; not 'rossi', 'iPhone' or single letters."""
    letters = word.replace("-", "").replace("'", "").replace("’", "")
    if len(letters) < 2 or not letters.isalpha() or not word[0].isupper():
        return False
    return letters[1:].islower() or letters.isupper() or all(p[:1].isupper() for p in re.split(r"[-'’]", word) if p)


def sensitive_words(words: list) -> set[int]:
    """Indices of the words to blur in PyMuPDF `get_text("words")` tuples (x0, y0, x1, y1, text, block, line, word).

    - any word with a digit (dates, numbers, codes, amounts);
    - runs of 2+ capitalised, non-common words on one line, likely names. A sentence's first word doesn't
      count, since its capital says nothing, unless its block is a short label-like cell ("Mario Rossi");
    - ALL-CAPS words of 4+ letters that aren't common document words.
    """
    hits: set[int] = set()
    run: list[int] = []
    block_sizes: dict = {}
    for w in words:
        block_sizes[w[5]] = block_sizes.get(w[5], 0) + 1

    def close_run():
        if len(run) >= 2:
            hits.update(run)
        run.clear()

    prev_block, prev_line, prev_text = None, None, ""
    for i, w in enumerate(words):
        text, block, line = w[4], w[5], w[6]
        bare = _bare(text)
        if any(c.isdigit() for c in text):
            hits.add(i)
        if (block, line) != (prev_block, prev_line):
            close_run()
        common = bare.lower() in COMMON_WORDS
        sentence_start = block != prev_block or prev_text.endswith(_SENTENCE_END)
        name_like = _capitalised(bare) and not common
        if sentence_start and block_sizes[block] > _SHORT_BLOCK and not bare.isupper():
            name_like = False
        if name_like:
            run.append(i)
        else:
            close_run()
        if bare.isupper() and bare.isalpha() and len(bare) >= 4 and not common:
            hits.add(i)
        # A run doesn't carry across a sentence end ("... Rossi. Born ...").
        if text.endswith(_SENTENCE_END):
            close_run()
        prev_block, prev_line, prev_text = block, line, text
    close_run()
    return hits


def _cert_titles() -> tuple[str, ...]:
    return tuple(t["title"] for t in cert_locale.TEXT.values()) + _EXTRA_CERT_TITLES


def certification_title_rects(page) -> list | None:
    """Rects of the certification title when this is the certification page, else None."""
    text = page.get_text().upper()
    for title in _cert_titles():
        if title in text:
            return page.search_for(title) or []
    return None


def split_pages(pdf: bytes) -> tuple[int, int]:
    """(translation pages shown in the preview, the original's pages left out) of a delivery PDF."""
    import fitz

    separators = {v.strip().lower() for v in cert_locale.ORIGINAL_COPY.values()}
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        total = len(doc)
        for i, page in enumerate(doc):
            if page.get_text().strip().lower() in separators:
                return i, total - i - 1
    return total, 0


@lru_cache(maxsize=2)
def _font_bytes(name: str) -> bytes:
    import fitz

    return fitz.Font(name).buffer


def _font(size: int, text: str):
    """MuPDF's built-in Helvetica (has the dashes Pillow's default lacks); its CJK fallback for other scripts."""
    import fitz
    from PIL import ImageFont

    try:
        helv = fitz.Font("helv")
        name = "helv" if all(helv.has_glyph(ord(c)) for c in text if not c.isspace()) else "cjk"
        return ImageFont.truetype(io.BytesIO(_font_bytes(name)), size)
    except Exception:
        return ImageFont.load_default(size=size)


def watermark_text(day: date) -> str:
    return f"PREVIEW – NOT VALID – UNPAID · {day.strftime('%d %b %Y')}"


def _watermark(img, text: str):
    """A diagonal grid of the text over the whole page, so cropping can't remove it."""
    from PIL import Image, ImageDraw

    w, h = img.size
    size = max(12, w // 40)
    font = _font(size, text)
    side = int(math.hypot(w, h)) + 2 * size
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    phrase = text + "      "
    phrase_w = max(1, int(draw.textlength(phrase, font=font)))
    for row, y in enumerate(range(0, side, size * 4)):
        offset = (row % 2) * phrase_w // 2
        for x in range(-phrase_w + offset, side, phrase_w):
            draw.text((x, y), phrase, font=font, fill=(150, 30, 30, 95))
    layer = layer.rotate(32, resample=Image.BICUBIC)
    left, top = (side - w) // 2, (side - h) // 2
    overlay = layer.crop((left, top, left + w, top + h))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _blur_box(img, box: tuple[int, int, int, int]) -> None:
    from PIL import ImageFilter

    x0, y0, x1, y1 = box
    radius = max(_WORD_BLUR, int((y1 - y0) * 0.6))
    # Blur a wider area than is pasted back, so the edges are as blurred as the middle.
    m = radius * 2
    W, H = img.size
    ox0, oy0, ox1, oy1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
    blurred = img.crop((ox0, oy0, ox1, oy1)).filter(ImageFilter.GaussianBlur(radius))
    inner = blurred.crop((x0 - ox0, y0 - oy0, x1 - ox0, y1 - oy0))
    img.paste(inner, (x0, y0))


def _pixel_box(rect, size) -> tuple[int, int, int, int] | None:
    W, H = size
    x0 = max(0, int(rect[0] * _SCALE) - _PAD)
    y0 = max(0, int(rect[1] * _SCALE) - _PAD)
    x1 = min(W, math.ceil(rect[2] * _SCALE) + _PAD)
    y1 = min(H, math.ceil(rect[3] * _SCALE) + _PAD)
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def render_page(page, watermark: str) -> bytes:
    from PIL import Image, ImageFilter

    pix = page.get_pixmap(dpi=DPI, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    titles = certification_title_rects(page)
    if titles is not None:
        # The certification page: only its title stays readable.
        clean = img.copy()
        img = img.filter(ImageFilter.GaussianBlur(_PAGE_BLUR))
        for rect in titles:
            box = _pixel_box(rect, img.size)
            if box:
                img.paste(clean.crop(box), box[:2])
    else:
        words = page.get_text("words", sort=False)
        for i in sorted(sensitive_words(words)):
            box = _pixel_box(words[i][:4], img.size)
            if box:
                _blur_box(img, box)
    img = _watermark(img, watermark)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def render_preview(pdf: bytes, day: date) -> list[bytes]:
    """PNGs of the translation pages; the separator and the original's pages are left out."""
    import fitz

    shown, _ = split_pages(pdf)
    text = watermark_text(day)
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        return [render_page(doc[i], text) for i in range(shown)]


def _upload(data: bytes, link_id, n: int) -> str:
    from app.services import s3_service

    tmp = Path(tempfile.mkdtemp(prefix="preview_"))
    try:
        path = tmp / f"{n}.png"
        path.write_bytes(data)
        return s3_service.upload_file_to_s3(path, prefix=f"delivery/preview/{link_id}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _download(key: str) -> bytes:
    from app.services import s3_service

    tmp = Path(tempfile.mkdtemp(prefix="preview_src_"))
    try:
        path = tmp / "snapshot.pdf"
        s3_service.download_file_from_s3(key, path)
        return path.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ensure(db: Session, link: DeliveryLink) -> list[str]:
    """The preview's storage keys, rendering and storing them on first view."""
    if link.preview_keys:
        return list(link.preview_keys)
    # Row lock: the client's page asks for every image at once, and only one request should render.
    row = (
        db.query(DeliveryLink)
        .filter(DeliveryLink.id == link.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if row.preview_keys:
        db.commit()
        return list(row.preview_keys)
    try:
        day = row.created_at.date() if row.created_at else date.today()
        pages = render_preview(_download(row.file_key), day)
        keys = [_upload(png, row.id, n) for n, png in enumerate(pages, start=1)]
    except Exception:
        db.rollback()
        raise
    row.preview_keys = keys
    db.commit()
    return keys


def delete(db: Session, link: DeliveryLink) -> None:
    """Drop the rendered preview; it's re-rendered if the link is still locked and viewed again."""
    from app.services import s3_service

    keys = list(link.preview_keys or [])
    if not keys:
        return
    link.preview_keys = None
    db.commit()
    s3_service.delete_objects_from_s3(keys)
