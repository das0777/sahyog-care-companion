"""Read a PDF page by page. A page with a usable text layer uses it; any other page goes to OCR.

Runs entirely inside the boundary. A misread number can't always be detected, so every OCR page
carries its source and confidence for later stages to show.
"""

import io
import re
import threading
from dataclasses import dataclass

import pypdfium2
import pypdfium2.raw as pdfium_raw
import pytesseract
from PIL import Image
from pypdfium2 import PdfiumError

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
SCAN_TEXT_CHARS = 200  # a page with an image and less text than this is a scan
OCR_DPI = 300
OCR_TIMEOUT_S = 40
OCR_LANGUAGES = "eng+hin"


_DECIMAL_AS_COLON = re.compile(r"(?<=\d):(?=\d{1,2}\s*(?:%|[a-zA-Zµ]+/))")
_MIU = re.compile(r"\bml[Uu]/")

# PDFium is not thread-safe, and two workers using it at once crash the whole process
_PDFIUM = threading.Lock()


class Rejected(Exception):
    """The file can't be read, for a reason the patient can act on. Never retried."""


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    source: str  # text | ocr
    confidence: float | None = None


def check_pdf(data: bytes) -> int:
    """Refuse what can't be a usable report, and return the page count."""
    if not data:
        raise Rejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise Rejected("The file is larger than 20 MB.")
    if b"%PDF-" not in data[:1024]:
        raise Rejected("This is not a PDF file.")
    with _PDFIUM:
        try:
            pdf = pypdfium2.PdfDocument(data)
        except PdfiumError as e:
            if "password" in str(e).lower():
                raise Rejected("This PDF is password-protected. Please remove the password.") from e
            raise Rejected("This PDF is damaged and can't be read.") from e
        pages = len(pdf)
        pdf.close()
    if pages == 0:
        raise Rejected("This PDF has no pages.")
    if pages > MAX_PAGES:
        raise Rejected("This PDF has more than 50 pages.")
    return pages


def read_pages(data: bytes) -> list[PageText]:
    with _PDFIUM:
        pdf = pypdfium2.PdfDocument(data)
        count = len(pdf)
    try:
        out = []
        for i in range(count):
            with _PDFIUM:
                text, image = _extract(pdf, i)
            if image is None:
                out.append(PageText(i + 1, text, "text"))
            else:
                # Outside the lock: OCR is the slow part, and it doesn't touch PDFium
                ocr_text, confidence = _ocr(image)
                out.append(PageText(i + 1, ocr_text, "ocr", confidence))
        return out
    finally:
        with _PDFIUM:
            pdf.close()


def _extract(pdf, index: int) -> tuple[str, Image.Image | None]:
    """The page's text layer, and an image of the page when it needs OCR."""
    page = pdf[index]
    textpage = page.get_textpage()
    try:
        text = textpage.get_text_bounded().replace("\r\n", "\n").strip()
        chars = sum(ch.isalnum() for ch in text)
        has_image = any(True for _ in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE]))
        if chars >= SCAN_TEXT_CHARS or not has_image:
            return text, None
        bitmap = page.render(scale=OCR_DPI / 72, grayscale=True)
        image = bitmap.to_pil().copy()
        bitmap.close()
        return text, image
    finally:
        textpage.close()
        page.close()


def tidy_ocr(text: str) -> str:
    """Two confusions Tesseract makes on lab tables, fixed only where the context is unambiguous:
    a decimal point read as a colon, directly before a unit ("15:5 g/dL", never "10:30 am"), and
    the unit mIU read with a lower-case L."""
    text = _DECIMAL_AS_COLON.sub(".", text)
    return _MIU.sub("mIU/", text)


def _ocr(image) -> tuple[str, float]:
    data = pytesseract.image_to_data(
        image,
        lang=OCR_LANGUAGES,
        config="--psm 6",
        timeout=OCR_TIMEOUT_S,
        output_type=pytesseract.Output.DICT,
    )
    lines: dict[tuple, list[str]] = {}
    confidences = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confidences.append(float(data["conf"][i]))
    text = "\n".join(" ".join(words) for words in lines.values())
    return tidy_ocr(text), (sum(confidences) / len(confidences) if confidences else 0.0)


def pdf_stream(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)
