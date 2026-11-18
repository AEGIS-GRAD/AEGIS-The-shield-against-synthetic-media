"""
Script to download and verify desklib/ai-text-detector-v1.01 from Hugging Face Hub.
"""
import argparse
import hashlib
import os
from huggingface_hub import snapshot_download

DESKLIB_REPO_ID = "desklib/ai-text-detector-v1.01"
DESKLIB_REVISION = "5fdea974cd4287c61674951ec78803aa274e2fb7"
DESKLIB_SAFETENSORS_SHA256 = "c024a1704c65f5a4bffeda58745c58fc0ed67d6ca07b158b068a257238815265"


def verify_sha256(file_path: str, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected_sha256.lower():
        raise RuntimeError(
            f"Desklib SHA-256 verification failed for {file_path}: "
            f"expected {expected_sha256}, got {actual}"
        )


def download_desklib(target_dir=None, revision: str = DESKLIB_REVISION):
    repo_id = DESKLIB_REPO_ID
    if target_dir is None:
        target_dir = os.path.join(os.path.dirname(__file__), "models", "desklib-base")

    os.makedirs(target_dir, exist_ok=True)
    print(f"[*] Downloading {repo_id}@{revision} snapshot to {target_dir}...")
    local_path = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=target_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
    )
    safetensors_path = os.path.join(local_path, "model.safetensors")
    if os.path.exists(safetensors_path):
        verify_sha256(safetensors_path, DESKLIB_SAFETENSORS_SHA256)
    print(f"[+] Download complete & SHA-256 verified: {local_path}")

    files = os.listdir(target_dir)
    print(f"[*] Files in {target_dir}: {files}")
    return local_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Desklib AI Text Detector from Hugging Face")
    parser.add_argument("--target_dir", type=str, default=None, help="Target directory for weights")
    parser.add_argument("--revision", type=str, default=DESKLIB_REVISION, help="Pinned Hugging Face commit SHA")
    args = parser.parse_args()
    download_desklib(args.target_dir, revision=args.revision)
