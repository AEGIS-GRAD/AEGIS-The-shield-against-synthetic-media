import cv2

cap = cv2.VideoCapture("detectors/video-classifier/tests/fixtures/clean_sample.mp4")
print("Opened:", cap.isOpened())                        # must be True
print("FPS:", cap.get(cv2.CAP_PROP_FPS))                # e.g. 25.0 or 30.0
print("Frames:", cap.get(cv2.CAP_PROP_FRAME_COUNT))     # should be above 30
cap.release()