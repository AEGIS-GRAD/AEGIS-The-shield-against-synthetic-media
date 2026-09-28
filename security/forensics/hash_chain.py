import cv2
import hashlib
import json
import os

class FrameHashChain:
    def __init__(self):
        # Genesis hash to start the chain
        self.genesis_hash = hashlib.sha256(b"AEGIS_GENESIS").hexdigest()

    def generate_manifest(self, video_path, output_manifest_path):
        """
        Reads a video, calculates a hash chain (SHA256(frame + previous_hash)),
        and writes the resulting manifest to disk.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(video_path)
        manifest = []
        current_hash = self.genesis_hash

        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            # Combine the current frame bytes with the previous hash
            hasher = hashlib.sha256()
            hasher.update(current_hash.encode('utf-8'))
            hasher.update(frame.tobytes())
            current_hash = hasher.hexdigest()
            
            manifest.append({
                "frame": frame_idx,
                "hash": current_hash
            })
            frame_idx += 1
            
        cap.release()
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_manifest_path)), exist_ok=True)
        with open(output_manifest_path, 'w') as f:
            json.dump({"genesis": self.genesis_hash, "chain": manifest}, f, indent=4)
            
        return manifest

    def validate_stream(self, video_path, manifest_path):
        """
        Re-computes hashes from the video and compares them against the manifest.
        Returns (True, -1, msg) if intact, (False, frame_idx, msg) if tampered.
        """
        if not os.path.exists(manifest_path):
             return False, -1, "Manifest not found"

        with open(manifest_path, 'r') as f:
            manifest_data = json.load(f)
            
        manifest = manifest_data["chain"]
        cap = cv2.VideoCapture(video_path)
        current_hash = self.genesis_hash
        
        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
                
            if frame_idx >= len(manifest):
                cap.release()
                return False, frame_idx, "Extra frames detected (Injection Attack)"
                
            hasher = hashlib.sha256()
            hasher.update(current_hash.encode('utf-8'))
            hasher.update(frame.tobytes())
            current_hash = hasher.hexdigest()
            
            if current_hash != manifest[frame_idx]["hash"]:
                cap.release()
                return False, frame_idx, f"Hash mismatch at frame {frame_idx} (Tampering Detected)"
                
            frame_idx += 1
            
        cap.release()
        
        if frame_idx < len(manifest):
            return False, frame_idx, f"Missing frames detected: expected {len(manifest)}, got {frame_idx}"
            
        return True, -1, "Intact"
