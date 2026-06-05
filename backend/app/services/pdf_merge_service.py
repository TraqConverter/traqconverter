from pathlib import Path
from pypdf import PdfReader, PdfWriter


class PdfMergeError(Exception):
    pass


class PdfMergeService:

    @staticmethod
    def append_pdf(
        original_pdf: Path,
        append_pdf: Path,
        output_pdf: Path,
    ) -> None:
        """
        Appends append_pdf to original_pdf and writes to output_pdf.
        """

        try:
            reader_original = PdfReader(str(original_pdf))
            reader_append = PdfReader(str(append_pdf))

            writer = PdfWriter()

            for page in reader_original.pages:
                writer.add_page(page)

            for page in reader_append.pages:
                writer.add_page(page)

            with open(output_pdf, "wb") as f:
                writer.write(f)

        except Exception as e:
            raise PdfMergeError(str(e))