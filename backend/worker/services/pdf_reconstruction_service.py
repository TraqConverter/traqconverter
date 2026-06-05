from pdf2image import convert_from_path
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pathlib import Path
import pytesseract
from PIL import Image, ImageFilter, ImageOps
import logging
import re

logger = logging.getLogger(__name__)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

POPPLER_PATH = r"C:\poppler\poppler-25.12.0\Library\bin"
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Structured document OCR
CUSTOM_CONFIG = r'--oem 3 --psm 4'


# --------------------------------------------------
# IMAGE PREPROCESSING
# --------------------------------------------------

def preprocess_image(image):
    """
    Improve OCR quality for scanned documents.
    """
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.SHARPEN)

    # Binary threshold
    bw = gray.point(lambda x: 0 if x < 180 else 255, "1")

    return bw


# --------------------------------------------------
# OCR GARBAGE FILTER
# --------------------------------------------------

def is_garbage_text(text):
    """
    Remove OCR noise from logos, stamps, artifacts.
    """
    text = text.strip()

    if not text:
        return True

    if re.search(r"[?]{1,}", text):
        return True

    letters = sum(c.isalpha() for c in text)

    if len(text) > 3 and letters / max(len(text), 1) < 0.4:
        return True

    if len(text) <= 2:
        return True

    return False


# --------------------------------------------------
# OCR LINE EXTRACTION
# --------------------------------------------------

def extract_text_boxes(image):
    """
    Extract grouped OCR lines with confidence filtering.
    """
    processed = preprocess_image(image)

    data = pytesseract.image_to_data(
        processed,
        output_type=pytesseract.Output.DICT,
        config=CUSTOM_CONFIG
    )

    grouped = {}
    n = len(data["text"])

    for i in range(n):

        text = data["text"][i].strip()

        if not text:
            continue

        try:
            conf = float(data["conf"][i])
        except:
            conf = 0

        # Confidence threshold
        if conf < 55:
            continue

        if is_garbage_text(text):
            continue

        # Skip top logo garbage
        if data["top"][i] < 55 and len(text) < 8:
            continue

        key = (
            data["block_num"][i],
            data["par_num"][i],
            data["line_num"][i]
        )

        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]

        if key not in grouped:
            grouped[key] = {
                "words": [],
                "x1": x,
                "y1": y,
                "x2": x + w,
                "y2": y + h
            }

        grouped[key]["words"].append(text)

        grouped[key]["x1"] = min(grouped[key]["x1"], x)
        grouped[key]["y1"] = min(grouped[key]["y1"], y)
        grouped[key]["x2"] = max(grouped[key]["x2"], x + w)
        grouped[key]["y2"] = max(grouped[key]["y2"], y + h)

    boxes = []

    for line in grouped.values():

        combined = " ".join(line["words"]).strip()

        if is_garbage_text(combined):
            continue

        boxes.append({
            "text": combined,
            "x": line["x1"],
            "y": line["y1"],
            "w": line["x2"] - line["x1"],
            "h": line["y2"] - line["y1"]
        })

    # Natural reading order
    boxes.sort(key=lambda b: (round(b["y"] / 8), b["x"]))

    return boxes


# --------------------------------------------------
# FONT STYLE
# --------------------------------------------------

def choose_font(box):
    """
    Approximate font based on box height.
    """
    if box["h"] > 28:
        return "Helvetica-Bold"
    elif box["h"] > 18:
        return "Helvetica-Bold"
    return "Helvetica"


# --------------------------------------------------
# WRAP TEXT
# --------------------------------------------------

def wrap_text(c, text, max_width, font_name, font_size):
    """
    Wrap text to pixel width.
    """
    words = text.split()

    if not words:
        return []

    lines = []
    current = words[0]

    for word in words[1:]:

        candidate = current + " " + word

        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word

    lines.append(current)

    return lines


# --------------------------------------------------
# OVERLAP DETECTION
# --------------------------------------------------

def intersects(proposed_area, occupied_areas):
    """
    Check if rendered area overlaps previous text blocks.
    """
    x1, y1, x2, y2 = proposed_area

    for ox1, oy1, ox2, oy2 in occupied_areas:

        if not (x2 < ox1 or x1 > ox2 or y2 < oy1 or y1 > oy2):
            return True

    return False


# --------------------------------------------------
# SMART FONT SHRINK (OPTION B)
# --------------------------------------------------

def fit_text_without_overlap(
    c,
    translated,
    box,
    occupied_areas,
    page_height,
    font_name
):
    """
    Shrink font until:
    - Text fits width
    - Text fits height
    - Text does not overlap occupied zones
    """
    max_size = min(int(box["h"]), 32)

    for font_size in range(max_size, 4, -1):

        wrapped_lines = wrap_text(
            c,
            translated,
            box["w"],
            font_name,
            font_size
        )

        line_height = font_size + 2

        rendered_height = len(wrapped_lines) * line_height

        x = box["x"]
        y = page_height - box["y"] - box["h"]

        proposed_area = (
            x - 2,
            y - 2,
            x + box["w"] + 2,
            y + rendered_height + 2
        )

        # Must fit box reasonably
        if rendered_height > box["h"] * 3:
            continue

        # Must not overlap
        if intersects(proposed_area, occupied_areas):
            continue

        return font_size, wrapped_lines, rendered_height

    return None, None, None


# --------------------------------------------------
# MAIN PDF BUILDER
# --------------------------------------------------

def build_searchable_pdf(input_pdf, translated_texts):
    """
    Production rebuild with:
    - OCR cleanup
    - Block grouping
    - Dynamic shrink-to-fit
    - True post-wrap overlap prevention
    """
    logger.info("Generating searchable PDF")

    images = convert_from_path(
        input_pdf,
        poppler_path=POPPLER_PATH,
        dpi=400
    )

    output_path = Path(input_pdf).parent / "translated_searchable.pdf"

    c = canvas.Canvas(str(output_path))

    translation_index = 0

    for page in images:

        width, height = page.size

        c.setPageSize((width, height))

        # Draw original page
        c.drawImage(
            ImageReader(page),
            0,
            0,
            width=width,
            height=height
        )

        boxes = extract_text_boxes(page)

        occupied_areas = []

        for box in boxes:

            if translation_index >= len(translated_texts):
                break

            translated = translated_texts[translation_index].strip()

            translation_index += 1

            if not translated:
                continue

            x = box["x"]
            y = height - box["y"] - box["h"]

            # Skip crest/logo
            if x < 120 and box["y"] < 150:
                continue

            # Skip signature/stamp zone
            if x > width * 0.68 and box["y"] > height * 0.72:
                continue

            # Skip footer legal disclaimer
            if box["y"] > height * 0.92:
                continue

            font_name = choose_font(box)

            # OPTION B: SHRINK UNTIL SAFE
            font_size, wrapped_lines, rendered_height = fit_text_without_overlap(
                c,
                translated,
                box,
                occupied_areas,
                height,
                font_name
            )

            # If impossible, skip
            if not font_size:
                continue

            line_height = font_size + 2

            # Final rendered area
            proposed_area = (
                x - 2,
                y - 2,
                x + box["w"] + 2,
                y + rendered_height + 2
            )

            occupied_areas.append(proposed_area)

            # Whiteout actual final area
            c.setFillColorRGB(1, 1, 1)
            c.rect(
                x - 2,
                y - 2,
                box["w"] + 4,
                rendered_height + 4,
                fill=1,
                stroke=0
            )

            # Draw visible text
            c.setFillColorRGB(0, 0, 0)
            c.setFont(font_name, font_size)

            start_y = y + rendered_height - font_size

            for line in wrapped_lines:

                c.drawString(x, start_y, line)

                # Invisible searchable layer
                c.setFillAlpha(0)
                c.drawString(x, start_y, line)
                c.setFillAlpha(1)

                start_y -= line_height

        c.showPage()

    c.save()

    logger.info(f"Searchable PDF generated: {output_path}")

    return output_path