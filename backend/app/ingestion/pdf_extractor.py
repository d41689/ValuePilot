import pdfplumber
from pathlib import Path
from typing import List, Tuple, Any

class PdfExtractor:
    @staticmethod
    def extract_text(file_path: Path) -> str:
        """
        Extracts all text from a PDF file using native text layer.
        Returns the concatenated text.
        """
        full_text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)
        return "\n".join(full_text)

    @staticmethod
    def extract_pages(file_path: Path) -> List[Tuple[int, str]]:
        """
        Extracts text per page.
        Returns a list of tuples (page_number, text).
        Page numbers are 1-based.
        """
        pages_content = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                pages_content.append((i + 1, text or ""))
        return pages_content

    @staticmethod
    def extract_pages_with_words(file_path: Path) -> List[Tuple[int, str, list[dict[str, Any]]]]:
        """
        Extracts text + word-level layout per page.
        Returns a list of tuples (page_number, text, words).
        """
        pages_content: List[Tuple[int, str, list[dict[str, Any]]]] = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                words = page.extract_words(x_tolerance=1, y_tolerance=1, use_text_flow=True) or []
                pages_content.append((i + 1, text, words))
        return pages_content
