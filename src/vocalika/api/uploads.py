from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, UploadFile

SUPPORTED_UPLOAD_SUFFIXES = {
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def safe_upload_name(filename: str | None, role: str) -> str:
    original = Path(filename or f"{role}.audio").name
    suffix = Path(original).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_SUFFIXES))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {role} format {suffix or '(none)'}. Use one of: {supported}.",
        )
    stem = re.sub(r"[^\w .()-]+", "_", Path(original).stem, flags=re.UNICODE).strip()
    return f"{role}-{stem or role}{suffix}"


async def save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Audio upload exceeds the 2 GB limit.",
                    )
                target.write(chunk)
    finally:
        await upload.close()
