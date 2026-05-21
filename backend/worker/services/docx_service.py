from docx import Document


def extract_text_from_docx(file_path):
    """
    Extract paragraphs from DOCX files.
    """

    document = Document(file_path)

    paragraphs = []

    for p in document.paragraphs:
        text = p.text.strip()

        if text:
            paragraphs.append(text)

    return paragraphs