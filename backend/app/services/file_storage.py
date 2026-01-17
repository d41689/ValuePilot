import shutil
from pathlib import Path
from fastapi import UploadFile
from app.core.config import settings

class FileStorageService:
    def __init__(self):
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_upload_file(self, upload_file: UploadFile, destination_filename: str) -> str:
        """
        Saves an uploaded file to the configured storage directory.
        Returns the relative path (key) to the saved file.
        """
        destination_path = self.upload_dir / destination_filename
        
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
