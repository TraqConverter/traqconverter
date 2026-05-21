from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


class CertificationGenerationError(Exception):
    pass


class CertificationService:

    @staticmethod
    def generate_certification_pdf(
        output_path: Path,
        user_name: str,
        source_language: str,
        target_language: str,
        override_text: str | None = None,
    ) -> None:
        """
        Generates a certification PDF page.

        Raises CertificationGenerationError on failure.
        """

        try:
            c = canvas.Canvas(str(output_path), pagesize=A4)
            width, height = A4

            y = height - 40 * mm

            c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(width / 2, y, "Certification of Translation")

            y -= 15 * mm

            c.setFont("Helvetica", 12)

            today = datetime.utcnow().strftime("%d %B %Y")

            if override_text:
                text_block = override_text
            else:
                text_block = (
                    f"I, {user_name}, hereby certify that the attached document "
                    f"translated from {source_language} to {target_language} "
                    f"is a true and accurate translation of the original document.\n\n"
                    f"Certified on {today}."
                )

            text_obj = c.beginText(25 * mm, y)
            text_obj.setLeading(16)

            for line in text_block.split("\n"):
                text_obj.textLine(line)

            c.drawText(text_obj)

            y -= 50 * mm

            c.drawString(25 * mm, 30 * mm, f"Name: {user_name}")
            c.drawString(25 * mm, 22 * mm, f"Date: {today}")

            c.showPage()
            c.save()

        except Exception as e:
            raise CertificationGenerationError(str(e))