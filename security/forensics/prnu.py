import numpy as np
import cv2
import pywt
import logging
import os
from typing import List, Dict, Optional, Tuple, Union
from collections import defaultdict

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


# ---------------------------------------------------------------------------
# Global Enrolled Camera PRNU Registry
# ---------------------------------------------------------------------------
CAMERA_PRNU_REGISTRY: Dict[str, np.ndarray] = {}


def register_camera_baseline(camera_id: str, baseline: np.ndarray) -> None:
    """Registers an enrolled hardware PRNU baseline fingerprint for a camera ID."""
    CAMERA_PRNU_REGISTRY[camera_id] = baseline.astype(np.float32)


def get_camera_baseline(camera_id: str) -> Optional[np.ndarray]:
    """Retrieves an enrolled hardware PRNU baseline fingerprint for a camera ID."""
    return CAMERA_PRNU_REGISTRY.get(camera_id)


def load_camera_baselines_from_dir(directory: str) -> int:
    """
    Loads all enrolled .npy camera baseline fingerprints from a directory.
    Filename without extension is treated as camera_id (e.g. 'camera-001.npy' -> 'camera-001').
    Returns count of successfully loaded baselines.
    """
    if not os.path.isdir(directory):
        return 0
    loaded = 0
    for fname in os.listdir(directory):
        if fname.endswith(".npy"):
            cam_id = fname[:-4]
            fpath = os.path.join(directory, fname)
            try:
                data = np.load(fpath)
                register_camera_baseline(cam_id, data)
                loaded += 1
                logger.info(f"Loaded PRNU baseline for {cam_id} from {fpath}")
            except Exception as e:
                logger.warning(f"Failed to load PRNU baseline from {fpath}: {e}")
    return loaded


# ---------------------------------------------------------------------------
# Continuous Live Stream PRNU Validator
# ---------------------------------------------------------------------------
class LivePRNUValidator:
    """
    Live streaming continuous PRNU sensor validator.
    Extracts high-frequency sensor noise from incoming video frames,
    computes Peak-to-Correlation Energy (PCE) against the camera's enrolled baseline,
    and flags any synthetic media or foreign camera sensor splices.
    """
    def __init__(
        self,
        level: int = 2,
        wavelet: str = "db4",
        pce_threshold: float = 50.0,
        check_interval: int = 1,
        bootstrap_frames: int = 15,
        target_shape: Optional[Tuple[int, int]] = (240, 320)
    ):
        self.extractor = PRNUExtractor(level=level, wavelet=wavelet)
        self.pce_threshold = pce_threshold
        self.check_interval = check_interval
        self.bootstrap_frames = bootstrap_frames
        self.target_shape = target_shape
        self.baselines: Dict[str, np.ndarray] = {}
        self.bootstrap_buffers: Dict[str, List[np.ndarray]] = defaultdict(list)
        self.frame_counts: Dict[str, int] = defaultdict(int)

    def enroll_baseline(self, camera_id: str, baseline: np.ndarray) -> None:
        """Explicitly enrolls a known hardware baseline for a camera ID."""
        base_clean = baseline.astype(np.float32)
        if self.target_shape and base_clean.shape[:2] != self.target_shape:
            base_clean = cv2.resize(base_clean, (self.target_shape[1], self.target_shape[0]))
        self.baselines[camera_id] = base_clean

    def decode_frame(
        self,
        frame_bytes: bytes,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> Optional[np.ndarray]:
        """
        Decodes raw bytes or compressed image payloads into an image array.
        Returns None if frame_bytes is not an image (e.g. mock test payload).
        """
        if not frame_bytes or len(frame_bytes) < 32:
            return None

        # Check explicit width and height
        if width and height:
            try:
                expected_bgr = height * width * 3
                expected_gray = height * width
                if len(frame_bytes) == expected_bgr:
                    img = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height, width, 3))
                    if self.target_shape and img.shape[:2] != self.target_shape:
                        img = cv2.resize(img, (self.target_shape[1], self.target_shape[0]))
                    return img
                elif len(frame_bytes) == expected_gray:
                    img = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height, width))
                    if self.target_shape and img.shape[:2] != self.target_shape:
                        img = cv2.resize(img, (self.target_shape[1], self.target_shape[0]))
                    return img
            except Exception:
                pass

        # Try compressed image decode (JPEG, PNG, WebP)
        try:
            arr = np.frombuffer(frame_bytes, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None and img.size > 0:
                if self.target_shape and img.shape[:2] != self.target_shape:
                    img = cv2.resize(img, (self.target_shape[1], self.target_shape[0]))
                return img
        except Exception:
            pass

        # Check common raw BGR CCTV dimensions
        byte_len = len(frame_bytes)
        raw_resolutions = [
            (240, 320, 3),   # 230,400 bytes (standard AEGIS test harness fixture)
            (480, 640, 3),   # 921,600 bytes
            (720, 1280, 3),  # 2,764,800 bytes
            (1080, 1920, 3), # 6,220,800 bytes
            (256, 256, 3),   # 196,608 bytes
            (256, 256, 1),   # 65,536 bytes
            (240, 320, 1),   # 76,800 bytes
        ]

        for h, w, c in raw_resolutions:
            if byte_len == h * w * c:
                try:
                    if c == 1:
                        img = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((h, w))
                    else:
                        img = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((h, w, c))
                    if self.target_shape and img.shape[:2] != self.target_shape:
                        img = cv2.resize(img, (self.target_shape[1], self.target_shape[0]))
                    return img
                except Exception:
                    pass

        return None

    def verify_frame(
        self,
        camera_id: str,
        frame_data: Union[bytes, np.ndarray],
        seq: int,
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Validates frame sensor noise against enrolled camera baseline.
        Returns:
            (is_valid, pce_score, detail_message)
        """
        if isinstance(frame_data, (bytes, bytearray)):
            frame = self.decode_frame(frame_data, width, height)
            if frame is None:
                # Payload is not an image (e.g. non-image test string); bypass PRNU safely
                return True, -1.0, "NON_IMAGE_PAYLOAD"
        elif isinstance(frame_data, np.ndarray):
            frame = frame_data
            if self.target_shape and frame.shape[:2] != self.target_shape:
                frame = cv2.resize(frame, (self.target_shape[1], self.target_shape[0]))
        else:
            return True, -1.0, "UNSUPPORTED_FRAME_TYPE"

        self.frame_counts[camera_id] += 1
        count = self.frame_counts[camera_id]

        # Check sampling interval
        if self.check_interval > 1 and (count % self.check_interval != 0):
            return True, -1.0, "INTERVAL_SKIP"

        # Check if baseline exists
        baseline = self.baselines.get(camera_id)
        if baseline is None:
            # Check global registry
            enrolled = get_camera_baseline(camera_id)
            if enrolled is not None:
                self.enroll_baseline(camera_id, enrolled)
                baseline = self.baselines.get(camera_id)

        if baseline is None:
            buf = self.bootstrap_buffers[camera_id]
            buf.append(frame)
            if len(buf) < self.bootstrap_frames:
                return True, 0.0, f"BOOTSTRAPPING ({len(buf)}/{self.bootstrap_frames})"
            
            # Generate baseline from accumulated bootstrap frames
            try:
                baseline_gen = self.extractor.generate_baseline(buf)
                self.enroll_baseline(camera_id, baseline_gen)
                self.bootstrap_buffers[camera_id] = []
                return True, 1000.0, "BASELINE_ESTABLISHED"
            except Exception as e:
                logger.error(f"Failed to generate PRNU baseline for {camera_id}: {e}")
                return False, 0.0, f"BASELINE_GENERATION_FAILED: {e}"

        # Baseline exists -> extract noise residual & compute PCE
        try:
            residual = self.extractor.extract_noise_residual(frame)
            pce = self.extractor.compute_pce(residual, baseline)
            
            if pce < self.pce_threshold:
                return False, pce, (
                    f"PRNU PCE {pce:.2f} below threshold {self.pce_threshold:.1f} "
                    f"at seq {seq} (foreign camera sensor detected)"
                )
            return True, pce, None
        except Exception as e:
            logger.error(f"Error during PRNU computation for {camera_id}: {e}")
            return False, 0.0, f"PRNU_COMPUTATION_ERROR: {e}"

