"""Cloudinary video hosting — upload local MP4s and get public URLs."""
from __future__ import annotations

import os
from pathlib import Path

import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

_configured = False


def _ensure_config():
    global _configured
    if _configured:
        return
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        secure=True,
    )
    _configured = True


def upload_video(video_path: Path, folder: str = "stocksbrew-shorts") -> str:
    """Upload a local MP4 to Cloudinary and return the public URL."""
    _ensure_config()
    result = cloudinary.uploader.upload(
        str(video_path),
        resource_type="video",
        folder=folder,
        overwrite=True,
    )
    return result["secure_url"]


def smoke_test() -> dict:
    """Verify Cloudinary credentials work."""
    _ensure_config()
    try:
        result = cloudinary.api.ping()
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
