"""
bundle_parser.py
================
Parses a multipart/form-data request into a structured BundleRequest.

Supported fields:
  Files  : 'image'  (jpg/png)  → saved to temp dir
           'video'  (mp4/avi)  → saved to temp dir
           'audio'  (wav/mp3)  → saved to temp dir
  Text   : 'text'  OR  'caption'  OR  'transcript'  (plain string)
  Option : 'bundle_id'  (optional UUID, auto-generated if absent)
"""

import os
import uuid
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from fastapi import Request

FILE_MODALITIES = {"image", "video", "audio"}
TEXT_FIELD_ALIASES = ("text", "caption", "transcript")


@dataclass
class BundleItem:
    modality: str                    # "image" | "video" | "audio" | "text"
    file_path: Optional[str] = None  # set for file modalities
    text_content: Optional[str] = None  # set for text modality


@dataclass
class BundleRequest:
    bundle_id: str
    items: Dict[str, BundleItem] = field(default_factory=dict)
    # keys are modality strings: "image", "text", "video", "audio"


async def parse_bundle(request: Request, upload_dir: str) -> BundleRequest:
    """
    Parse an incoming multipart request into a BundleRequest.
    Saves uploaded files to upload_dir with safe, unique names.
    Raises ValueError if the request contains no recognisable modalities.
    """
    form = await request.form()
    bundle_id = str(form.get("bundle_id") or uuid.uuid4())
    bundle = BundleRequest(bundle_id=bundle_id)

    # ── Handle uploaded files ─────────────────────────────────────────────
    for modality in FILE_MODALITIES:
        file_field = form.get(modality)
        if file_field and hasattr(file_field, "filename") and file_field.filename:
            suffix = os.path.splitext(file_field.filename)[1].lower() or ".bin"
            safe_name = f"{bundle_id}_{modality}{suffix}"
            save_path = os.path.join(upload_dir, safe_name)
            with open(save_path, "wb") as out:
                shutil.copyfileobj(file_field.file, out)
            bundle.items[modality] = BundleItem(modality=modality, file_path=save_path)

    # ── Handle text field ────────────────────────────────────────────────
    text_content = None
    for alias in TEXT_FIELD_ALIASES:
        val = form.get(alias)
        if val and isinstance(val, str) and val.strip():
            text_content = val.strip()
            break

    if text_content:
        # Save text to a temp .txt file so dispatch.py can handle it uniformly
        txt_path = os.path.join(upload_dir, f"{bundle_id}_text.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text_content)
        bundle.items["text"] = BundleItem(modality="text",
                                          file_path=txt_path,
                                          text_content=text_content)

    if not bundle.items:
        raise ValueError(
            "Bundle contains no recognisable modalities. "
            "Send at least one of: image, video, audio file, or text/caption/transcript field."
        )

    return bundle