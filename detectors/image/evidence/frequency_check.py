"""
FFT-based upsampling grid artifact detector.
AI generative models (GANs and diffusion decoders) introduce periodic
spatial repetitions due to transposed convolution or upsampling layers.
"""

import numpy as np
from PIL import Image


def check_frequency(image: Image.Image) -> dict:
    # Convert image to single-channel float array
    gray = np.array(image.convert("L"), dtype=np.float32)

    # 2D Fast Fourier Transform + Shift DC to center
    fft = np.fft.fft2(gray)
    fft_shift = np.fft.fftshift(fft)
    magnitude = np.log1p(np.abs(fft_shift))

    h, w = magnitude.shape
    cy, cx = h // 2, w // 2

    # Mask central DC region (10x10 window)
    mask = np.ones_like(magnitude, dtype=bool)
    mask[cy - 5:cy + 5, cx - 5:cx + 5] = False
    periphery = magnitude[mask]

    peak_val = periphery.max()
    mean_val = periphery.mean()
    std_val = periphery.std()

    # Peak-to-standard-deviation ratio
    peak_ratio = float((peak_val - mean_val) / (std_val + 1e-8))
    anomaly_detected = peak_ratio > 4.0

    return {
        "flag": anomaly_detected,
        "peak_ratio": round(peak_ratio, 4)
    }