"""
Perturbation library for the AEGIS robustness harness (Week 10 Cyber Task 2)
===========================================================================

Every perturbation is deterministic given ``seed`` and parameterised by a single
strength. Strengths were chosen to differ from anything the detectors saw during
fine-tuning or in the team's existing evaluation variants, so the matrix is not
inflated by train/test overlap:

* Image fine-tuning (``detectors/image/finetune.py``): resize to 384 only.
  Video fine-tuning (``finetune_efficientnet.py`` / ``finetune_mobilenetv3.py``):
  horizontal flip + ColorJitter(0.2, 0.2, 0.1). Existing image eval variants
  (``eval/DATA.md``): ``jpeg75``, ``jpeg50``, ``resize0.5``.
  → JPEG {90, 60, 40, 25}, resize {0.75, 0.4, 0.25}, blur sigma {0.8, 1.6, 2.4},
    Gaussian noise sigma {4, 8, 14}, centre crop {0.9, 0.7, 0.5}. No flips or
    colour jitter (those *are* training augmentations).
* Text fine-tuning (``finetune_desklib.py``): no augmentation.
  → homoglyph rate {0.03, 0.10, 0.25}, zero-width rate {0.03, 0.10, 0.25},
    rule-based paraphrase rate {0.15, 0.35, 0.60}; plus real GPT-4 paraphrases
    from MAGE as a natural (non-synthetic) paraphrase condition.
* Audio (AASIST): codec simulation — telephone band (8 kHz mu-law), low-bitrate
  quantisation {8, 6, 4} bits; ffmpeg MP3/Opus round-trips when ffmpeg is on PATH.
"""

from __future__ import annotations

import io
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# Image (PIL in, PIL out)
# ─────────────────────────────────────────────────────────────────────────────


def img_jpeg(img, quality: float, seed: int = 0):
    from PIL import Image

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=int(quality))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def img_resize(img, scale: float, seed: int = 0):
    """Down-scale then up-scale back (detail loss at the original geometry)."""
    from PIL import Image

    w, h = img.size
    small = img.resize((max(8, int(w * scale)), max(8, int(h * scale))), Image.BICUBIC)
    return small.resize((w, h), Image.BICUBIC)


def img_blur(img, sigma: float, seed: int = 0):
    from PIL import ImageFilter

    return img.filter(ImageFilter.GaussianBlur(radius=float(sigma)))


def img_noise(img, sigma: float, seed: int = 0):
    from PIL import Image

    rng = np.random.default_rng(seed)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    arr = arr + rng.normal(0.0, float(sigma), arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def img_crop(img, keep: float, seed: int = 0):
    """Centre crop keeping ``keep`` of each side (the detector then resizes as usual)."""
    w, h = img.size
    cw, ch = int(w * keep), int(h * keep)
    x, y = (w - cw) // 2, (h - ch) // 2
    return img.crop((x, y, x + cw, y + ch))


IMAGE_PERTURBATIONS: Dict[str, Tuple[Callable, Sequence[float]]] = {
    "jpeg": (img_jpeg, (90, 60, 40, 25)),
    "resize": (img_resize, (0.75, 0.4, 0.25)),
    "blur": (img_blur, (0.8, 1.6, 2.4)),
    "noise": (img_noise, (4, 8, 14)),
    "crop": (img_crop, (0.9, 0.7, 0.5)),
}

# ─────────────────────────────────────────────────────────────────────────────
# Text (str in, str out)
# ─────────────────────────────────────────────────────────────────────────────
# Latin -> Cyrillic/Greek visual confusables (NFKC does not fold these).
HOMOGLYPHS = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "i": "і", "j": "ј", "s": "ѕ", "A": "Α", "B": "Β", "C": "С", "E": "Ε",
    "H": "Η", "K": "Κ", "M": "Μ", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ",
}
ZERO_WIDTH = ("​", "‌", "‍", "⁠")


def txt_homoglyph(text: str, rate: float, seed: int = 0) -> str:
    rng = random.Random(seed)
    return "".join(HOMOGLYPHS[ch] if ch in HOMOGLYPHS and rng.random() < rate else ch for ch in text)


def txt_zero_width(text: str, rate: float, seed: int = 0) -> str:
    rng = random.Random(seed)
    out = []
    for ch in text:
        out.append(ch)
        if ch.isalpha() and rng.random() < rate:
            out.append(rng.choice(ZERO_WIDTH))
    return "".join(out)


# Small, meaning-preserving substitution table (common LLM-register words -> plainer variants).
SYNONYMS = {
    "additionally": "also", "furthermore": "also", "moreover": "besides", "however": "but", "therefore": "so",
    "consequently": "as a result", "significant": "big", "significantly": "greatly", "utilize": "use",
    "utilizes": "uses", "demonstrate": "show", "demonstrates": "shows", "numerous": "many", "various": "several",
    "crucial": "key", "essential": "needed", "ensure": "make sure", "enhance": "improve", "approximately": "about",
    "individuals": "people", "obtain": "get", "require": "need", "requires": "needs", "assist": "help",
    "commence": "start", "purchase": "buy", "sufficient": "enough", "regarding": "about", "facilitate": "help",
    "important": "major", "overall": "on the whole", "particularly": "especially", "increase": "rise",
    "decrease": "drop", "illustrate": "show", "indicates": "suggests", "indicate": "suggest", "comprehensive": "thorough",
    "fundamental": "basic", "potential": "possible", "currently": "now", "previously": "before", "subsequently": "later",
    "ultimately": "in the end", "nevertheless": "still", "notably": "in particular", "vital": "key", "robust": "strong",
    "innovative": "new", "challenging": "hard", "beneficial": "useful", "impact": "effect", "impacts": "effects",
    "experience": "go through", "environment": "setting", "community": "local area", "residents": "locals",
    "stated": "said", "announced": "said", "revealed": "showed", "according": "as per", "large": "big",
    "small": "little", "rapidly": "quickly", "commonly": "often", "frequently": "often", "difficult": "hard",
    "attempt": "try", "assistance": "help", "remain": "stay", "remains": "stays", "begin": "start",
    "provide": "give", "provides": "gives", "allow": "let", "allows": "lets", "however,": "but,",
}
_WORD_RE = re.compile(r"\b([A-Za-z]+)\b")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def txt_paraphrase(text: str, rate: float, seed: int = 0) -> str:
    """Rule-based light paraphrase: synonym swaps (rate of eligible words), contraction
    toggling, and swapping adjacent sentences with probability rate/2."""
    rng = random.Random(seed)

    def swap(m: re.Match) -> str:
        w = m.group(1)
        rep = SYNONYMS.get(w.lower())
        if rep is None or rng.random() >= rate:
            return w
        return rep.capitalize() if w[0].isupper() else rep

    out = _WORD_RE.sub(swap, text)
    for a, b in (("do not", "don't"), ("does not", "doesn't"), ("is not", "isn't"), ("it is", "it's"),
                 ("cannot", "can't"), ("will not", "won't"), ("they are", "they're")):
        if rng.random() < rate:
            out = out.replace(a, b)
    sents = _SENT_RE.split(out)
    for i in range(0, len(sents) - 1, 2):
        if rng.random() < rate / 2:
            sents[i], sents[i + 1] = sents[i + 1], sents[i]
    return " ".join(sents)


TEXT_PERTURBATIONS: Dict[str, Tuple[Callable, Sequence[float]]] = {
    "homoglyph": (txt_homoglyph, (0.03, 0.10, 0.25)),
    "zero_width": (txt_zero_width, (0.03, 0.10, 0.25)),
    "paraphrase": (txt_paraphrase, (0.15, 0.35, 0.60)),
}

# ─────────────────────────────────────────────────────────────────────────────
# Audio (float32 mono waveform in [-1, 1], sample rate)
# ─────────────────────────────────────────────────────────────────────────────


def _resample(wav: np.ndarray, sr: int, target: int) -> np.ndarray:
    from scipy.signal import resample_poly

    g = np.gcd(sr, target)
    return resample_poly(wav, target // g, sr // g).astype(np.float32)


def aud_telephone(wav: np.ndarray, sr: int, mu: float = 255.0, seed: int = 0) -> np.ndarray:
    """8 kHz band-limit + 8-bit mu-law companding (G.711-like), back to the original rate."""
    low = _resample(wav, sr, 8000)
    comp = np.sign(low) * np.log1p(mu * np.abs(np.clip(low, -1, 1))) / np.log1p(mu)
    q = np.round((comp + 1) / 2 * 255) / 255 * 2 - 1
    exp = np.sign(q) * (np.power(1 + mu, np.abs(q)) - 1) / mu
    return _resample(exp.astype(np.float32), 8000, sr)


def aud_quantize(wav: np.ndarray, sr: int, bits: float, seed: int = 0) -> np.ndarray:
    levels = 2 ** int(bits)
    return (np.round((np.clip(wav, -1, 1) + 1) / 2 * (levels - 1)) / (levels - 1) * 2 - 1).astype(np.float32)


def aud_ffmpeg(wav: np.ndarray, sr: int, bitrate_kbps: float, codec: str = "libmp3lame", seed: int = 0) -> np.ndarray:
    """Real lossy codec round-trip via ffmpeg (skipped by callers when ffmpeg is absent)."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    import soundfile as sf

    ext = ".mp3" if codec == "libmp3lame" else ".ogg"
    with tempfile.TemporaryDirectory() as d:
        src, enc, dec = Path(d) / "in.wav", Path(d) / f"enc{ext}", Path(d) / "out.wav"
        sf.write(src, wav, sr)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-c:a", codec, "-b:a", f"{int(bitrate_kbps)}k", str(enc)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(enc), "-ar", str(sr), "-ac", "1", str(dec)], check=True)
        out, _ = sf.read(dec, dtype="float32")
    return out


AUDIO_PERTURBATIONS: Dict[str, Tuple[Callable, Sequence[float]]] = {
    "telephone": (lambda w, sr, s, seed=0: aud_telephone(w, sr, seed=seed), (255,)),
    "quantize": (aud_quantize, (8, 6, 4)),
    "mp3": (lambda w, sr, s, seed=0: aud_ffmpeg(w, sr, s, "libmp3lame", seed), (64, 32, 16)),
}
