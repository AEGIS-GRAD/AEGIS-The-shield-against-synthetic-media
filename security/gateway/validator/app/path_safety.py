"""
Path-traversal defenses for the upload endpoint.

Two distinct attack surfaces:

1. Client-supplied filenames (multipart video uploads) - never trusted for
   storage or forwarding. `safe_extension` pulls out only the extension and
   rejects anything with a path separator or traversal sequence in it.
2. Internal file-path payloads (the audio JSON contract's `payload` field
   may be "an absolute internal file path" per SCHEMA.md) - `is_confined_path`
   ensures such a path resolves inside SHARED_VOLUME_ROOT before it's ever
   opened.
"""

from __future__ import annotations

import os
import posixpath


def has_traversal_sequence(raw: str) -> bool:
    """Reject '..', absolute paths, and separators in a client filename."""
    if not raw:
        return True
    if ".." in raw:
        return True
    if "/" in raw or "\\" in raw:
        return True
    if raw.startswith("~"):
        return True
    return False


def safe_extension(filename: str | None) -> str | None:
    """
    Return the lowercase extension of `filename` if it is a bare filename
    with no path-traversal sequence, else None.
    """
    if not filename:
        return None
    if has_traversal_sequence(filename):
        return None
    _, ext = posixpath.splitext(filename)
    return ext.lower() or None


def is_confined_path(candidate: str, root: str) -> bool:
    """
    True if `candidate` is an absolute path that resolves strictly inside
    `root` (no '../' escape, no symlink pointing outside it).
    """
    if not os.path.isabs(candidate):
        return False
    real_root = os.path.realpath(root)
    real_candidate = os.path.realpath(candidate)
    return real_candidate == real_root or real_candidate.startswith(real_root + os.sep)
