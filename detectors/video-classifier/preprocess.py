from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Union, Any

import cv2
import numpy as np
try:
    import torch
    HAS_TORCH = True
except Exception:
    torch = None
    HAS_TORCH = False


logger = logging.getLogger(__name__)

# Try importing MTCNN from facenet_pytorch
try:
    from facenet_pytorch import MTCNN
    HAS_MTCNN = True
except ImportError:
    MTCNN = None
    HAS_MTCNN = False
    logger.warning("facenet-pytorch MTCNN not found. Fallback face cropping will be used.")


class VideoPreprocessor:
    """Preprocesses video files for Xception/FaceForensics++ frame classification."""

    def __init__(self, target_size: tuple[int, int] = (299, 299), device: Optional[str] = None):
        self.target_size = target_size
        if HAS_TORCH:
            self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
            self.mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
            self.std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        else:
            self.device = "cpu"
            self.mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
            self.std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


        self.mtcnn = None
        if HAS_MTCNN:
            try:
                self.mtcnn = MTCNN(keep_all=False, select_largest=True, device=self.device)
            except Exception as e:
                logger.warning(f"Failed to initialize MTCNN detector: {e}. Fallback crop will be used.")

    def extract_frames(self, video_path: Union[str, Path], sample_n: int = 10) -> List[np.ndarray]:
        """Extracts frames from video input file, sampling every N-th frame.

        Args:
            video_path: Path to the input video file.
            sample_n: Frame sampling interval (extract 1 frame every sample_n frames). Default N=10.

        Returns:
            List of RGB numpy arrays of extracted frames.
        """
        video_path_str = str(video_path)
        cap = cv2.VideoCapture(video_path_str)

        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path_str}")

        frames: List[np.ndarray] = []
        frame_idx = 0

        try:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % sample_n == 0:
                    # Convert BGR (OpenCV format) to RGB
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frames.append(rgb_frame)

                frame_idx += 1
        finally:
            cap.release()

        logger.info(f"Extracted {len(frames)} frames from video (sampled every {sample_n} frames, total frames: {frame_idx}).")
        return frames

    def crop_face(self, frame: np.ndarray) -> np.ndarray:
        """Crops face from frame using MTCNN if available, otherwise falls back to center square.

        Args:
            frame: RGB numpy image array of shape (H, W, 3).

        Returns:
            Cropped RGB image array.
        """
        if self.mtcnn is not None:
            try:
                boxes, _ = self.mtcnn.detect(frame)
                if boxes is not None and len(boxes) > 0:
                    box = boxes[0].astype(int)
                    h, w, _ = frame.shape
                    x1, y1, x2, y2 = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
                    if x2 > x1 and y2 > y1:
                        return frame[y1:y2, x1:x2]
            except Exception as e:
                logger.debug(f"MTCNN detection error: {e}. Falling back to center crop.")

        # TODO: MTCNN fallback used. Replace with proper face detector when facenet-pytorch is available/configured.
        return self._crop_center_square(frame)

    def _crop_center_square(self, frame: np.ndarray) -> np.ndarray:
        """Fallback center square crop."""
        h, w, _ = frame.shape
        crop_dim = min(h, w)
        start_x = (w - crop_dim) // 2
        start_y = (h - crop_dim) // 2
        return frame[start_y : start_y + crop_dim, start_x : start_x + crop_dim]

    def normalize_frame(self, crop_img: np.ndarray) -> Union[torch.Tensor, np.ndarray]:
        """Resizes frame to target size (299x299) and applies ImageNet normalization.

        Args:
            crop_img: RGB image numpy array.

        Returns:
            Normalized PyTorch tensor or NumPy array of shape (3, 299, 299).
        """
        resized = cv2.resize(crop_img, self.target_size, interpolation=cv2.INTER_LINEAR)
        if HAS_TORCH:
            # Convert HWC in [0, 255] to CHW float tensor in [0.0, 1.0]
            tensor = torch.from_numpy(resized).permute(2, 0, 1).float() / 255.0
            # ImageNet normalization: (tensor - mean) / std
            normalized_tensor = (tensor - self.mean) / self.std
            return normalized_tensor
        else:
            # Fallback to NumPy array normalization
            array = np.transpose(resized, (2, 0, 1)).astype(np.float32) / 255.0
            normalized_array = (array - self.mean) / self.std
            return normalized_array


    def preprocess_video(self, video_path: Union[str, Path], sample_n: int = 10) -> List[torch.Tensor]:
        """Runs complete preprocessing pipeline: frame extraction -> face crop -> resize & normalize.

        Args:
            video_path: Path to video file.
            sample_n: Frame sampling interval. Default 10.

        Returns:
            List of normalized frame tensors of shape (3, 299, 299).
        """
        raw_frames = self.extract_frames(video_path, sample_n=sample_n)
        processed_tensors: List[torch.Tensor] = []

        for frame in raw_frames:
            face_crop = self.crop_face(frame)
            norm_tensor = self.normalize_frame(face_crop)
            processed_tensors.append(norm_tensor)

        return processed_tensors
