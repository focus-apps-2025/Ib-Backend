"""
File utilities.
"""
import os
import hashlib
from pathlib import Path
from typing import Optional, List
import shutil


def ensure_directory(path: str) -> None:
    """
    Ensure directory exists, create if not.
    """
    Path(path).mkdir(parents=True, exist_ok=True)


def safe_filename(filename: str) -> str:
    """
    Convert filename to safe version.
    """
    import re
    # Remove invalid characters
    safe = re.sub(r'[^\w\-_. ]', '', filename)
    # Replace spaces with underscores
    safe = safe.replace(' ', '_')
    return safe


def get_file_hash(file_path: str, algorithm: str = "md5") -> str:
    """
    Get hash of file content.
    """
    hash_func = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def get_file_size(file_path: str) -> int:
    """
    Get file size in bytes.
    """
    return os.path.getsize(file_path)


def get_file_extension(file_path: str) -> str:
    """
    Get file extension (without dot).
    """
    return Path(file_path).suffix.lower()[1:] if '.' in file_path else ''


def list_files(directory: str, extension: Optional[str] = None) -> List[str]:
    """
    List files in directory with optional extension filter.
    """
    path = Path(directory)
    if not path.exists():
        return []
        
    if extension:
        return [str(p) for p in path.glob(f"*.{extension}")]
    return [str(p) for p in path.iterdir() if p.is_file()]


def delete_file(file_path: str) -> bool:
    """
    Delete file if exists.
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception:
        pass
    return False


def copy_file(src: str, dst: str) -> bool:
    """
    Copy file from src to dst.
    """
    try:
        ensure_directory(os.path.dirname(dst))
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False


def read_file_content(file_path: str, mode: str = 'r') -> Optional[str]:
    """
    Read file content.
    """
    try:
        with open(file_path, mode) as f:
            return f.read()
    except Exception:
        return None


def write_file_content(file_path: str, content: str, mode: str = 'w') -> bool:
    """
    Write content to file.
    """
    try:
        ensure_directory(os.path.dirname(file_path))
        with open(file_path, mode) as f:
            f.write(content)
        return True
    except Exception:
        return False