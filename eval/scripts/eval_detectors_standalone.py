"""
eval_detectors_standalone.py
----------------------------
Evaluates video-classifier and AASIST directly — no services, no HTTP.
Loads each model from its local checkpoint and runs inference on the
full dataset so you can verify you are reproducing paper numbers.

Usage:
    # Run both detectors (default):
    python eval/scripts/eval_detectors_standalone.py

    # Run only one:
    python eval/scripts/eval_detectors_standalone.py --detector video-classifier
    python eval/scripts/eval_detectors_standalone.py --detector aasist

    # Limit to N files per class for a quick sanity check:
    python eval/scripts/eval_detectors_standalone.py --limit 10

    # Enable AASIST_DEBUG (tensor shape + raw logits per sample):
    python eval/scripts/eval_detectors_standalone.py --detector aasist --debug

Output:
    Prints a table to stdout. Optionally writes JSON with --out <path>.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import List

import numpy as np

# ── Repo paths ─────────────────────────────────────────────────────────────────
REPO_ROOT  = Path(__file__).resolve().parents[2]   # d:/DeepFake_Grad
VC_DIR     = REPO_ROOT / "detectors" / "video-classifier"
AASIST_DIR = REPO_ROOT / "detectors" / "aasist"
RPPG_DIR   = REPO_ROOT / "detectors" / "rppg"
SYNCNET_DIR= REPO_ROOT / "detectors" / "syncnet"

VIDEO_FAKE = REPO_ROOT / "eval" / "data" / "video_subset" / "fake"
VIDEO_REAL = REPO_ROOT / "eval" / "data" / "video_subset" / "real"
AUDIO_FAKE = REPO_ROOT / "eval" / "data" / "audio_subset" / "fake"
AUDIO_REAL = REPO_ROOT / "eval" / "data" / "audio_subset" / "real"

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}
AUDIO_EXTS = {".flac", ".wav", ".mp3", ".ogg"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eval_standalone")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _import_file(mod_name: str, file_path: Path):
    """Dynamically loads a python module from file path without static import errors."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {mod_name} from {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _collect(folder: Path, exts: set, limit: int | None) -> List[Path]:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in exts)
    return files[:limit] if limit else files


def _compute_metrics(scores: List[float], labels: List[int]) -> dict:
    """
    scores : float in [0,1] where 1.0 = FAKE
    labels : 1 = fake, 0 = real
    """
    from sklearn.metrics import roc_auc_score, roc_curve, accuracy_score

    arr_s = np.array(scores)
    arr_l = np.array(labels)
    preds = (arr_s >= 0.5).astype(int)
    acc = accuracy_score(arr_l, preds)

    auc = eer = float("nan")
    try:
        auc = roc_auc_score(arr_l, arr_s)
        fpr, tpr, _ = roc_curve(arr_l, arr_s)
        fnr = 1 - tpr
        idx = np.nanargmin(np.abs(fnr - fpr))
        eer = (fpr[idx] + fnr[idx]) / 2
    except Exception:
        pass

    fake_mask = arr_l == 1
    real_mask = arr_l == 0
    fake_acc = accuracy_score(arr_l[fake_mask], preds[fake_mask]) if fake_mask.any() else float("nan")
    real_acc = accuracy_score(arr_l[real_mask], preds[real_mask]) if real_mask.any() else float("nan")

    return dict(
        accuracy=acc, auc=auc, eer=eer,
        fake_acc=fake_acc, real_acc=real_acc,
        n_fake=int(fake_mask.sum()), n_real=int(real_mask.sum()), n_total=len(labels),
    )


def _print_results(name: str, m: dict, paper_note: str):
    print(f"\n{'='*58}")
    print(f"  {name}")
    print(f"{'='*58}")
    print(f"  Samples      : {m['n_total']}  (fake={m['n_fake']}, real={m['n_real']})")
    print(f"  Accuracy     : {m['accuracy']:.4f}  ({m['accuracy']*100:.1f}%)")
    print(f"  AUC          : {m['auc']:.4f}")
    if not np.isnan(m['eer']):
        print(f"  EER          : {m['eer']*100:.2f}%  (lower = better)")
    print(f"  Fake acc     : {m['fake_acc']:.4f}")
    print(f"  Real acc     : {m['real_acc']:.4f}")
    print(f"  {paper_note}")
    print(f"{'-'*58}")


# ── Video Classifier ───────────────────────────────────────────────────────────

def _load_vc_model(weights_path: Path):
    """Loads EfficientNet-B0 from local .pth — no HuggingFace call."""
    import torch
    import torch.nn as nn
    import torchvision.models as tv

    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        model = tv.efficientnet_b0(weights=tv.EfficientNet_B0_Weights.DEFAULT)
    except AttributeError:
        model = tv.efficientnet_b0(pretrained=True)

    in_feat = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_feat, 2)

    sd = torch.load(str(weights_path), map_location=device)
    if isinstance(sd, dict):
        sd = sd.get("state_dict", sd.get("model", sd))
    try:
        model.load_state_dict(sd)
    except RuntimeError:
        sd = {(k[7:] if k.startswith("module.") else k): v for k, v in sd.items()}
        model.load_state_dict(sd)

    model.to(device)
    model.eval()
    logger.info(f"[video-classifier] Loaded on {device}")
    return model, device


def run_video_classifier(limit: int | None):
    import torch
    vc_prep_mod = _import_file("vc_preprocess", VC_DIR / "preprocess.py")
    VideoPreprocessor = vc_prep_mod.VideoPreprocessor

    weights_path = VC_DIR / "efficientnet_b0_ffpp_c23.pth"
    if not weights_path.exists():
        logger.error(f"Weights not found at {weights_path}")
        logger.error("Place efficientnet_b0_ffpp_c23.pth inside detectors/video-classifier/")
        sys.exit(1)

    model, device = _load_vc_model(weights_path)
    preprocessor = VideoPreprocessor(target_size=(224, 224))

    fake_files = _collect(VIDEO_FAKE, VIDEO_EXTS, limit)
    real_files = _collect(VIDEO_REAL, VIDEO_EXTS, limit)
    logger.info(f"[video-classifier] {len(fake_files)} fake, {len(real_files)} real")

    scores, labels = [], []
    failed = 0

    for label_val, files, tag in [(1, fake_files, "FAKE"), (0, real_files, "REAL")]:
        for fpath in files:
            try:
                t0 = time.perf_counter()
                tensors = preprocessor.preprocess_video(str(fpath), sample_n=10)
                if not tensors:
                    raise ValueError("no frames extracted")

                frame_scores = []
                for t in tensors:
                    if t.ndim == 3:
                        t = t.unsqueeze(0)
                    t = t.to(device)
                    with torch.no_grad():
                        logits = model(t)
                        prob = torch.softmax(logits, dim=1)[0, 1].item()
                    frame_scores.append(prob)

                score = float(np.mean(frame_scores))
                elapsed = (time.perf_counter() - t0) * 1000
                verdict = "FAKE" if score >= 0.5 else "REAL"
                ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[FAIL]"
                print(f"  {ok} [{tag}] {fpath.name[:52]:<52s}  score={score:.4f}  {elapsed:6.0f}ms")
                scores.append(score)
                labels.append(label_val)
            except Exception as e:
                failed += 1
                print(f"  ! [{tag}] {fpath.name[:52]:<52s}  ERROR: {e}")

    if failed:
        logger.warning(f"[video-classifier] {failed} files failed and were skipped")

    m = _compute_metrics(scores, labels)
    _print_results(
        "VIDEO-CLASSIFIER  (EfficientNet-B0, FF++ C23)",
        m,
        "Paper target: Accuracy ~ 0.852 / AUC ~ 0.933  (FF++ c23 test set)"
    )
    return m


# ── AASIST ─────────────────────────────────────────────────────────────────────

def run_aasist(limit: int | None, debug: bool = False):
    import torch
    if debug:
        os.environ["AASIST_DEBUG"] = "1"

    weights_path = AASIST_DIR / "AASIST.pth"
    if not weights_path.exists():
        logger.error(f"Weights not found at {weights_path}")
        logger.error("Place AASIST.pth inside detectors/aasist/")
        sys.exit(1)

    aasist_mod = _import_file("aasist_model_arch", AASIST_DIR / "models" / "AASIST.py")
    Model = aasist_mod.Model
    prep_mod = _import_file("aasist_prep", AASIST_DIR / "preprocessing.py")
    preprocess_audio = prep_mod.preprocess_audio

    AASIST_CONFIG = {
        "architecture": "AASIST",
        "nb_samp": 64600,
        "first_conv": 128,
        "filts": [70, [1, 32], [32, 32], [32, 64], [64, 64]],
        "gat_dims": [64, 32],
        "pool_ratios": [0.5, 0.7, 0.5, 0.5],
        "temperatures": [2.0, 2.0, 100.0, 100.0],
    }

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"[AASIST] Loading weights from {weights_path} on {device}")
    model = Model(AASIST_CONFIG)
    model.load_state_dict(torch.load(str(weights_path), map_location=device))
    model.to(device)
    model.eval()
    logger.info("[AASIST] Weights loaded successfully")

    fake_files = _collect(AUDIO_FAKE, AUDIO_EXTS, limit)
    real_files = _collect(AUDIO_REAL, AUDIO_EXTS, limit)
    logger.info(f"[AASIST] {len(fake_files)} fake, {len(real_files)} real")

    scores, labels = [], []
    failed = 0

    for label_val, files, tag in [(1, fake_files, "FAKE"), (0, real_files, "REAL")]:
        for fpath in files:
            try:
                t0 = time.perf_counter()
                audio_tensor = preprocess_audio(str(fpath))  # → (1, 64600)

                if debug:
                    print(f"    [DEBUG] tensor.shape={audio_tensor.shape}  (want [1, 64600])")

                with torch.no_grad():
                    _, out = model(audio_tensor.to(device))  # out shape: (1, 2)

                probs = torch.softmax(out, dim=-1)[0]
                spoof_prob    = float(probs[0].item())   # class 0 = spoof/fake
                bonafide_prob = float(probs[1].item())   # class 1 = bonafide/real

                if debug:
                    print(
                        f"    [DEBUG] logits=[{float(out[0,0]):.4f}, {float(out[0,1]):.4f}]  "
                        f"softmax=[spoof={spoof_prob:.4f}, bonafide={bonafide_prob:.4f}]"
                    )

                elapsed = (time.perf_counter() - t0) * 1000
                verdict = "FAKE" if spoof_prob >= 0.5 else "REAL"
                ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[FAIL]"
                print(f"  {ok} [{tag}] {fpath.name[:52]:<52s}  spoof={spoof_prob:.4f}  {elapsed:6.0f}ms")
                scores.append(spoof_prob)
                labels.append(label_val)
            except Exception as e:
                failed += 1
                print(f"  ! [{tag}] {fpath.name[:52]:<52s}  ERROR: {e}")

    if failed:
        logger.warning(f"[AASIST] {failed} files failed and were skipped")

    m = _compute_metrics(scores, labels)
    _print_results(
        "AASIST  (Graph Attention Network, ASVspoof 2019 LA)",
        m,
        "Paper target: EER ~ 0.83%  (ASVspoof 2019 LA evaluation set)"
    )
    return m


# ── rPPG ───────────────────────────────────────────────────────────────────────

def run_rppg(limit: int | None):
    rppg_prep_mod = _import_file("rppg_preprocess", RPPG_DIR / "preprocess.py")
    RppgPreprocessor = rppg_prep_mod.RppgPreprocessor
    rppg_ext_mod = _import_file("rppg_extract_module", RPPG_DIR / "rppg_extract.py")
    extract_pulse_signal = rppg_ext_mod.extract_pulse_signal
    estimate_heart_rate = rppg_ext_mod.estimate_heart_rate
    signal_quality_score = rppg_ext_mod.signal_quality_score

    preprocessor = RppgPreprocessor()
    fake_files = _collect(VIDEO_FAKE, VIDEO_EXTS, limit)
    real_files = _collect(VIDEO_REAL, VIDEO_EXTS, limit)
    logger.info(f"[rPPG] {len(fake_files)} fake, {len(real_files)} real")

    scores, labels = [], []
    failed = 0

    for label_val, files, tag in [(1, fake_files, "FAKE"), (0, real_files, "REAL")]:
        for fpath in files:
            try:
                t0 = time.perf_counter()
                rgb_signals, fps, meta = preprocessor.preprocess_video(str(fpath))
                if meta.get("guardrail_triggered", False):
                    score = 0.5
                else:
                    lum = meta.get("luminance_confidence_factor", 1.0)
                    pulse = extract_pulse_signal(rgb_signals, fps, denoise=(lum < 1.0))
                    quality = signal_quality_score(pulse, fps=fps)
                    score = float(np.clip(1.0 - quality, 0.0, 1.0))

                elapsed = (time.perf_counter() - t0) * 1000
                verdict = "FAKE" if score >= 0.5 else "REAL"
                ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[FAIL]"
                print(f"  {ok} [{tag}] {fpath.name[:52]:<52s}  score={score:.4f}  {elapsed:6.0f}ms")
                scores.append(score)
                labels.append(label_val)
            except Exception as e:
                failed += 1
                print(f"  ! [{tag}] {fpath.name[:52]:<52s}  ERROR: {e}")

    if failed:
        logger.warning(f"[rPPG] {failed} files failed and were skipped")

    m = _compute_metrics(scores, labels)
    _print_results("RPPG  (CHROM Pulse Consistency)", m, "Classical physiological micro-vascular signal analysis")
    return m


# ── SyncNet ────────────────────────────────────────────────────────────────────

def run_syncnet(limit: int | None):
    if str(SYNCNET_DIR) not in sys.path:
        sys.path.insert(0, str(SYNCNET_DIR))
    sync_prep_mod = _import_file("syncnet_preprocess", SYNCNET_DIR / "preprocess.py")
    SyncNetPreprocessor = sync_prep_mod.SyncNetPreprocessor
    sync_infer_mod = _import_file("syncnet_infer", SYNCNET_DIR / "infer.py")
    SyncNetInference = sync_infer_mod.SyncNetInference

    weights_p = SYNCNET_DIR / "weights" / "syncnet_v2.model"
    if not weights_p.exists():
        logger.error(f"SyncNet weights not found at: {weights_p}")
        sys.exit(1)

    preprocessor = SyncNetPreprocessor()
    inference = SyncNetInference()

    fake_files = _collect(VIDEO_FAKE, VIDEO_EXTS, limit)
    real_files = _collect(VIDEO_REAL, VIDEO_EXTS, limit)
    logger.info(f"[SyncNet] {len(fake_files)} fake, {len(real_files)} real")

    scores, labels = [], []
    failed = 0

    for label_val, files, tag in [(1, fake_files, "FAKE"), (0, real_files, "REAL")]:
        for fpath in files:
            try:
                t0 = time.perf_counter()
                vid_seqs, aud_seqs, has_audio = preprocessor.preprocess(str(fpath))
                conf, raw_offset, ev = inference.score_video(vid_seqs, aud_seqs, has_audio)
                elapsed = (time.perf_counter() - t0) * 1000

                status = "[SILENT]" if "not_applicable" in (ev.flags or []) else "[A/V]"
                verdict = "FAKE" if conf >= 0.5 else "REAL"
                ok = "[OK]" if (verdict == "FAKE") == (label_val == 1) else "[--]"
                print(f"  {ok} {status} [{tag}] {fpath.name[:45]:<45s}  conf={conf:.4f}  offset={raw_offset:+4.1f}  {elapsed:6.0f}ms")
                scores.append(conf)
                labels.append(label_val)
            except Exception as e:
                failed += 1
                print(f"  ! [{tag}] {fpath.name[:52]:<52s}  ERROR: {e}")

    if failed:
        logger.warning(f"[SyncNet] {failed} files failed and were skipped")

    m = _compute_metrics(scores, labels)
    _print_results("SYNCNET  (Audio-Visual Lip-Sync)", m, "Lip-phoneme temporal cross-correlation analysis")
    return m


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Standalone detector eval — no services needed"
    )
    parser.add_argument(
        "--detector",
        choices=["video-classifier", "aasist", "rppg", "syncnet", "both", "all"],
        default="both",
        help="Which detector to evaluate: video-classifier, aasist, rppg, syncnet, both (vc+aasist), all",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Limit to N files per class for a quick check (default: all 150)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print AASIST tensor shape and raw logits for every sample",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional JSON file to write results summary to",
    )
    args = parser.parse_args()

    # Check scikit-learn is available
    try:
        import sklearn  # noqa: F401
    except ImportError:
        print("ERROR: scikit-learn not installed. Run: pip install scikit-learn")
        sys.exit(1)

    results = {}

    if args.detector in ("video-classifier", "both", "all"):
        print("\n" + "=" * 60)
        print("  EVALUATING: Video Classifier")
        print(f"  Dataset : {VIDEO_FAKE.parent}  (150 fake / 150 real)")
        print("  Model   : EfficientNet-B0  /  FF++ C23 checkpoint")
        print("=" * 60)
        results["video-classifier"] = run_video_classifier(args.limit)

    if args.detector in ("aasist", "both", "all"):
        print("\n" + "=" * 60)
        print("  EVALUATING: AASIST")
        print(f"  Dataset : {AUDIO_FAKE.parent}  (150 fake / 150 real)")
        print("  Model   : ClovaAI AASIST  /  ASVspoof 2019 LA eval")
        print("=" * 60)
        results["aasist"] = run_aasist(args.limit, debug=args.debug)

    if args.detector in ("rppg", "all"):
        print("\n" + "=" * 60)
        print("  EVALUATING: rPPG (CHROM Pulse Consistency)")
        print(f"  Dataset : {VIDEO_FAKE.parent}  (150 fake / 150 real)")
        print("  Method  : Remote Photoplethysmography CHROM")
        print("=" * 60)
        results["rppg"] = run_rppg(args.limit)

    if args.detector in ("syncnet", "all"):
        print("\n" + "=" * 60)
        print("  EVALUATING: SyncNet (Lip-Sync Consistency)")
        print(f"  Dataset : {VIDEO_FAKE.parent}  (150 fake / 150 real)")
        print("  Model   : SyncNet v2 Checkpoint")
        print("=" * 60)
        results["syncnet"] = run_syncnet(args.limit)

    if args.out:
        import json

        def _clean(d):
            return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in d.items()}

        Path(args.out).write_text(json.dumps({k: _clean(v) for k, v in results.items()}, indent=2))
        print(f"\nResults written to {args.out}")


if __name__ == "__main__":
    main()

