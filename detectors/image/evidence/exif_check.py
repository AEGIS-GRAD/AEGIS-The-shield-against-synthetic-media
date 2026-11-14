"""
EXIF and metadata provenance check.
Authentic photos from digital cameras or smartphones carry rich EXIF tables.
AI-generated images typically strip EXIF or leave synthetic software tags.
"""

from PIL import Image
from PIL.ExifTags import TAGS


def check_exif(image: Image.Image) -> dict:
    exif_data = None
    try:
        exif_data = image.getexif()
    except Exception:
        pass

    if not exif_data:
        return {
            "exif_missing": True,
            "software_tag_present": False,
            "software_value": None
        }

    decoded = {TAGS.get(tag_id, tag_id): val for tag_id, val in exif_data.items()}
    software = decoded.get("Software", None)
    software_str = str(software).strip() if software else None

    return {
        "exif_missing": False,
        "software_tag_present": software_str is not None,
        "software_value": software_str
    }