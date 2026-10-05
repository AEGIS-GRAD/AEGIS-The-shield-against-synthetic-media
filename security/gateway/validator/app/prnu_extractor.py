import numpy as np
import cv2
import pywt
import logging
from typing import List

logger = logging.getLogger(__name__)

class PRNUExtractor:
    """
    Photo-Response Non-Uniformity (PRNU) Extractor.
    Extracts high-frequency sensor noise from video frames to cryptographically
    identify the specific hardware camera sensor that captured the footage.
    """

    def __init__(self, level: int = 4, wavelet: str = "db4"):
        """
        Args:
            level: The depth of the discrete wavelet transform (DWT).
            wavelet: The type of wavelet to use for denoising.
        """
        self.level = level
        self.wavelet = wavelet

    def extract_noise_residual(self, image: np.ndarray) -> np.ndarray:
        """
        Isolates the sensor noise from a single image/frame using a Wiener filter
        and wavelet decomposition (Mihcak et al. denoising).
        
        Args:
            image: Grayscale numpy array of the frame.
        Returns:
            The extracted noise residual pattern (PRNU fingerprint fragment).
        """
        # Ensure image is grayscale and float32
        if len(image.shape) == 3:
            img_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            img_gray = image
            
        img_float = img_gray.astype(np.float32)

        # Apply Discrete Wavelet Transform (DWT)
        coeffs = pywt.wavedec2(img_float, self.wavelet, level=self.level)
        
        # We perform filtering on detail coefficients to isolate the noise 
        # (high frequency) from the actual image content (low frequency)
        denoised_coeffs = [coeffs[0]] # Keep the approximation coefficients intact
        
        for i in range(1, len(coeffs)):
            cH, cV, cD = coeffs[i]
            # Simple local variance filtering (simplified Wiener filter for PRNU)
            var_window = 3
            cH_var = cv2.blur(cH ** 2, (var_window, var_window)) - cv2.blur(cH, (var_window, var_window)) ** 2
            cV_var = cv2.blur(cV ** 2, (var_window, var_window)) - cv2.blur(cV, (var_window, var_window)) ** 2
            cD_var = cv2.blur(cD ** 2, (var_window, var_window)) - cv2.blur(cD, (var_window, var_window)) ** 2
            
            # Prevent division by zero
            noise_var = np.mean([np.var(cH), np.var(cV), np.var(cD)])
            cH_filter = np.maximum(0, cH_var - noise_var) / np.maximum(cH_var, 1e-6)
            cV_filter = np.maximum(0, cV_var - noise_var) / np.maximum(cV_var, 1e-6)
            cD_filter = np.maximum(0, cD_var - noise_var) / np.maximum(cD_var, 1e-6)
            
            denoised_coeffs.append((cH * cH_filter, cV * cV_filter, cD * cD_filter))
            
        # Reconstruct the denoised image
        denoised_img = pywt.waverec2(denoised_coeffs, self.wavelet)
        
        # The PRNU noise is the difference between the original image and the denoised image
        # Match dimensions if wavelet reconstruction adds a padding row/col
        denoised_img = denoised_img[:img_float.shape[0], :img_float.shape[1]]
        noise_residual = img_float - denoised_img
        
        # Zero-mean the residual
        noise_residual = noise_residual - np.mean(noise_residual)
        return noise_residual

    def generate_baseline(self, frames: List[np.ndarray]) -> np.ndarray:
        """
        Averages the noise residuals from multiple frames of the same camera
        to suppress random thermal noise and extract the persistent PRNU fingerprint.
        """
        if not frames:
            raise ValueError("No frames provided for baseline generation.")
            
        residuals = [self.extract_noise_residual(f) for f in frames]
        # Stack and average to compute the baseline PRNU
        baseline = np.mean(residuals, axis=0)
        return baseline

    def compute_pce(self, residual: np.ndarray, baseline: np.ndarray) -> float:
        """
        Computes Peak-to-Correlation Energy (PCE) between a frame's residual
        and the camera's enrolled baseline PRNU.
        """
        # Ensure identical shapes
        if residual.shape != baseline.shape:
            residual = cv2.resize(residual, (baseline.shape[1], baseline.shape[0]))

        # Normalized cross-correlation in frequency domain
        res_fft = np.fft.fft2(residual)
        base_fft = np.fft.fft2(baseline)
        
        # Phase correlation
        cross_power = res_fft * np.conj(base_fft)
        cross_power /= np.abs(cross_power) + 1e-6
        
        cc = np.fft.ifft2(cross_power).real
        
        # Calculate PCE
        peak_height = np.max(cc)
        peak_idx = np.unravel_index(np.argmax(cc), cc.shape)
        
        # Energy excluding the peak region (e.g., 11x11 square around the peak)
        r = 5
        energy_mask = np.ones_like(cc, dtype=bool)
        
        y, x = peak_idx
        h, w = cc.shape
        y_min, y_max = max(0, y - r), min(h, y + r + 1)
        x_min, x_max = max(0, x - r), min(w, x + r + 1)
        
        energy_mask[y_min:y_max, x_min:x_max] = False
        
        energy = np.mean(cc[energy_mask] ** 2)
        
        pce = (peak_height ** 2) / (energy + 1e-6)
        return float(pce)
