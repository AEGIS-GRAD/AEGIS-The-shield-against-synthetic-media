"""
Script to download and verify desklib/ai-text-detector-v1.01 from Hugging Face Hub.
"""
import os
import sys
import argparse
from huggingface_hub import snapshot_download

def download_desklib(target_dir=None):
    repo_id = "desklib/ai-text-detector-v1.01"
    if target_dir is None:
        target_dir = os.path.join(os.path.dirname(__file__), "models", "desklib-base")
    
    os.makedirs(target_dir, exist_ok=True)
    print(f"[*] Downloading {repo_id} snapshot to {target_dir}...")
    local_path = snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir,
        local_dir_use_symlinks=False,
        resume_download=True
    )
    print(f"[+] Download complete: {local_path}")
    
    # Verify snapshot contents
    files = os.listdir(target_dir)
    print(f"[*] Files in {target_dir}: {files}")
    return local_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Desklib AI Text Detector from Hugging Face")
    parser.add_argument("--target_dir", type=str, default=None, help="Target directory for weights")
    args = parser.parse_args()
    download_desklib(args.target_dir)
