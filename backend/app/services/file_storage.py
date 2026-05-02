import shutil
import hashlib
import re
from datetime import date
from pathlib import Path
from fastapi import UploadFile
from app.core.config import settings


class FileStorageService:
    VALUE_LINE_HASH_LENGTH = 12

    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_upload_file(self, upload_file: UploadFile, destination_filename: str) -> str:
        """
        Saves an uploaded file to the configured storage directory.
        Returns the relative path (key) to the saved file.
        """
        destination_path = self.upload_dir / destination_filename
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with destination_path.open("wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
        finally:
            upload_file.file.close()
            
        return str(destination_path)

    def get_file_path(self, file_key: str) -> Path:
        """
        Resolves the absolute path from a file key.
        """
        # In this simple local implementation, the key IS the absolute path 
        # or relative to root. Since we return str(destination_path) above 
        # which is absolute if UPLOAD_DIR is absolute, let's just return it.
        return Path(file_key)

    def sha256_file(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def value_line_pdf_path(
        self,
        *,
        exchange: str,
        ticker: str,
        report_date: date,
        content_hash: str,
    ) -> Path:
        safe_exchange = self._safe_path_segment(exchange).upper()
        safe_ticker = self._safe_path_segment(ticker).upper()
        short_hash = content_hash[: self.VALUE_LINE_HASH_LENGTH]
        return (
            self.upload_dir
            / "value_line"
            / safe_exchange
            / safe_ticker
            / f"{report_date.isoformat()}-{short_hash}.pdf"
        )

    def archive_value_line_pdf(
        self,
        source_path: Path,
        *,
        exchange: str,
        ticker: str,
        report_date: date,
    ) -> Path:
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(str(source_path))

        source_hash = self.sha256_file(source_path)
        canonical_path = self.value_line_pdf_path(
            exchange=exchange,
            ticker=ticker,
            report_date=report_date,
            content_hash=source_hash,
        )
        if source_path == canonical_path:
            return canonical_path

        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        if canonical_path.exists():
            existing_hash = self.sha256_file(canonical_path)
            if existing_hash != source_hash:
                raise FileExistsError(f"Canonical PDF path already exists with different content: {canonical_path}")
            source_path.unlink()
            return canonical_path

        source_path.replace(canonical_path)
        return canonical_path

    def _safe_path_segment(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
        cleaned = cleaned.strip("._-")
        if not cleaned:
            raise ValueError("Path segment cannot be empty")
        return cleaned
