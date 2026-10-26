"""The "Trial" watermark on every page a trial account downloads, and who gets a clean file."""
import math
from io import BytesIO

import fitz
from docx import Document
from docx.oxml import parse_xml
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.roles import is_staff
from app.models.credit import CreditTransaction
from app.models.user import User

WATERMARK_TEXT = "Trial – OnlineDocTranslator.ai"

CLEAN = "clean"
WATERMARKED = "watermarked"

# Not Word's "PowerPlusWaterMarkObject", so Design > Watermark > Remove doesn't find it.
_SHAPE_ID = "OdtTrialMark"


def paid_with_purchased_credits(db: Session, project) -> bool:
    """True when real money (a credit pack) paid for at least one page of this translation, and it wasn't refunded."""
    ref = str(project.id)
    charged = (
        db.query(CreditTransaction.id)
        .filter(
            CreditTransaction.reference_id == ref,
            CreditTransaction.type == "USAGE",
            CreditTransaction.from_purchased > 0,
        )
        .first()
    )
    if not charged:
        return False
    refunded = db.query(CreditTransaction.id).filter(CreditTransaction.reference_id == f"refund:{ref}").first()
    return not refunded


def export_mode(db: Session, project, user: User):
    """CLEAN, WATERMARKED, or None when the caller can't download this project at all."""
    from app.dependencies.feature_guard import effective_plan, plan_allows

    if is_staff(user):
        return CLEAN
    plan = effective_plan(db, user)
    # A page bought with a pack stays downloadable after the balance runs out.
    if plan_allows(plan, "clean_download") or paid_with_purchased_credits(db, project):
        return CLEAN
    if plan_allows(plan, "download_translation"):
        return WATERMARKED
    return None


def require_export(db: Session, project, user: User) -> str:
    from app.dependencies.feature_guard import upgrade_message

    mode = export_mode(db, project, user)
    if mode is None:
        raise HTTPException(status_code=403, detail=upgrade_message("download_translation"))
    return mode


def require_clean_export(db: Session, project, user: User) -> None:
    """403 unless the caller gets unwatermarked files; for routes that hand out the stored file as it is."""
    if require_export(db, project, user) != CLEAN:
        raise HTTPException(
            status_code=403,
            detail="On the trial, download the DOCX or PDF export; it carries a trial watermark. "
            "Subscribe or buy a page pack for clean files.",
        )


def finish(data: bytes, fmt: str, mode: str) -> bytes:
    """The bytes to send: as they are for CLEAN, stamped for WATERMARKED."""
    if mode == CLEAN:
        return data
    return watermark_docx(data) if fmt == "docx" else watermark_pdf(data)


def watermark_pdf(data: bytes, text: str = WATERMARK_TEXT) -> bytes:
    """Writes the text diagonally into every page's content stream, over the page, three times."""
    font = fitz.Font("hebo")
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            # Stamped on the unrotated page, so a rotated one gets the same diagonal.
            rotation = page.rotation
            if rotation:
                page.set_rotation(0)
            rect = page.rect
            diagonal = (rect.width ** 2 + rect.height ** 2) ** 0.5
            size = max(12.0, 0.75 * diagonal / max(font.text_length(text, fontsize=1), 1))
            small = size * 0.4
            centre = fitz.Point(rect.x0 + rect.width / 2, rect.y0 + rect.height / 2)
            writer = fitz.TextWriter(rect)
            width = font.text_length(text, fontsize=size)
            writer.append(fitz.Point(centre.x - width / 2, centre.y + size / 3), text, font=font, fontsize=size)
            small_width = font.text_length(text, fontsize=small)
            gap = min(rect.width, rect.height) * 0.28
            for offset in (-gap, gap):
                writer.append(
                    fitz.Point(centre.x - small_width / 2, centre.y + offset + small / 3),
                    text, font=font, fontsize=small,
                )
            writer.write_text(
                page,
                color=(0.55, 0.55, 0.55),
                opacity=0.35,
                # Bottom-left to top-right along the page's own diagonal.
                morph=(centre, fitz.Matrix(math.degrees(math.atan2(rect.height, rect.width)))),
                overlay=True,
            )
            if rotation:
                page.set_rotation(rotation)
        return doc.tobytes(garbage=3, deflate=True)


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = (
    f'xmlns:w="{_W}" xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w10="urn:schemas-microsoft-com:office:word"'
)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _watermark_paragraph(text: str, n: int):
    """A header paragraph holding a WordArt shape centred on the page, behind the text, rotated 315 degrees."""
    return parse_xml(
        f'<w:p {_NS}><w:pPr><w:pStyle w:val="Header"/></w:pPr><w:r><w:rPr><w:noProof/></w:rPr><w:pict>'
        '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800" '
        'path="m@7,l@8,m@5,21600l@6,21600e">'
        '<v:formulas><v:f eqn="sum #0 0 10800"/><v:f eqn="prod #0 2 1"/><v:f eqn="sum 21600 0 @1"/>'
        '<v:f eqn="sum 0 0 @2"/><v:f eqn="sum 21600 0 @3"/><v:f eqn="if @0 @3 0"/>'
        '<v:f eqn="if @0 21600 @1"/><v:f eqn="if @0 0 @2"/><v:f eqn="if @0 @4 21600"/>'
        '<v:f eqn="mid @5 @6"/><v:f eqn="mid @8 @5"/><v:f eqn="mid @7 @8"/><v:f eqn="mid @6 @7"/>'
        '<v:f eqn="sum @6 0 @5"/></v:formulas>'
        '<v:path textpathok="t" o:connecttype="custom" '
        'o:connectlocs="@9,0;@10,10800;@11,21600;@12,10800" o:connectangles="270,180,90,0"/>'
        '<v:textpath on="t" fitshape="t"/><v:handles><v:h position="#0,bottomRight" xrange="6629,14971"/></v:handles>'
        '<o:lock v:ext="edit" text="t" shapetype="t"/></v:shapetype>'
        f'<v:shape id="{_SHAPE_ID}{n}" o:spid="_x0000_s{2049 + n}" type="#_x0000_t136" '
        'style="position:absolute;margin-left:0;margin-top:0;width:468pt;height:78pt;rotation:315;'
        'z-index:-251654144;mso-position-horizontal:center;mso-position-horizontal-relative:margin;'
        'mso-position-vertical:center;mso-position-vertical-relative:margin" '
        'o:allowincell="f" fillcolor="#8c8c8c" stroked="f">'
        '<v:fill opacity=".35"/>'
        f'<v:textpath style="font-family:&quot;Arial&quot;;font-size:1pt;font-weight:bold" string="{_xml_escape(text)}"/>'
        '<w10:wrap anchorx="margin" anchory="margin"/>'
        '</v:shape></w:pict></w:r></w:p>'
    )


def _stamp(header, text: str, n: int) -> None:
    header._element.insert(0, _watermark_paragraph(text, n))


def watermark_docx(data: bytes, text: str = WATERMARK_TEXT) -> bytes:
    """Puts the WordArt watermark in every header a page can show: each section's default, first-page and even-page header."""
    doc = Document(BytesIO(data))
    even_pages = bool(doc.settings.odd_and_even_pages_header_footer)
    stamped = {"default": False, "first": False, "even": False}
    n = 0
    for section in doc.sections:
        headers = {
            "default": (section.header, True),
            "first": (section.first_page_header, section.different_first_page_header_footer),
            "even": (section.even_page_header, even_pages),
        }
        for kind, (header, shown) in headers.items():
            if header.is_linked_to_previous:
                # A linked header shows the previous section's, already stamped; with none before, make one.
                if not shown or stamped[kind]:
                    continue
                header.is_linked_to_previous = False
            _stamp(header, text, n)
            n += 1
            stamped[kind] = True
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
