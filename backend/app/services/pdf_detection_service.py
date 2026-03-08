from pdfminer.high_level import extract_text


def pdf_has_text(pdf_path: str) -> bool:
    """
    Detect if a PDF contains embedded text.
    Returns True if text exists, False if it is likely a scanned document.
    """

    try:
        text = extract_text(pdf_path, maxpages=1)

        if text and text.strip():
            return True

        return False

    except Exception:
        # If parsing fails assume scanned
        return False