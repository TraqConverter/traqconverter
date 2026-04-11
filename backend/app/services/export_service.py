from docx import Document
from io import BytesIO
from datetime import datetime

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet


# ==============================
# CERTIFICATION BLOCK
# ==============================
def build_certification(user_email: str):
    return [
        "CERTIFIED TRANSLATION",
        "",
        "I hereby certify that this translation is accurate and complete.",
        "",
        f"Translator: {user_email}",
        f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "----------------------------------------",
        ""
    ]


# ==============================
# DOCX EXPORT
# ==============================
def generate_docx(segments, user_email: str):
    doc = Document()

    # 🔥 ADD CERTIFICATION FIRST
    for line in build_certification(user_email):
        doc.add_paragraph(line)

    # 🔥 ADD CONTENT
    for seg in segments:
        if seg.translated_text:
            doc.add_paragraph(seg.translated_text)

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    return buffer


# ==============================
# PDF EXPORT
# ==============================
def generate_pdf(segments, user_email: str):
    buffer = BytesIO()

    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    content = []

    # 🔥 ADD CERTIFICATION FIRST
    for line in build_certification(user_email):
        content.append(Paragraph(line, styles["Normal"]))
        content.append(Spacer(1, 10))

    # 🔥 ADD CONTENT
    for seg in segments:
        if seg.translated_text:
            content.append(Paragraph(seg.translated_text, styles["Normal"]))
            content.append(Spacer(1, 10))

    doc.build(content)

    buffer.seek(0)
    return buffer