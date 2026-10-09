import numpy as np
from facenet_pytorch import MTCNN

mtcnn = MTCNN(keep_all=True, device="cpu")

# Blank 480x640 frame: MTCNN should find no face
blank = np.zeros((480, 640, 3), dtype=np.uint8)
boxes, probs = mtcnn.detect(blank)
assert boxes is None, "Expected no face in blank frame"
print("PASS: blank frame -> no boxes")

# With a real face, boxes is an array of shape (N, 4): [x1, y1, x2, y2]
print("Face detection contract: boxes=None or ndarray shape (N,4)")