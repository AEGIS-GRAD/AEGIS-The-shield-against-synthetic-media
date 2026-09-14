#!/usr/bin/env python3
"""
make_audio_subset.py

Builds a stratified audio subset from the ASVspoof 2019 Logical Access (LA)
dataset into eval/data/audio_subset/{real,fake}/.

  real/ <- bonafide utterances
  fake/ <- spoof utterances

Protocol file format (verified from actual data):
  <speaker_id> <filename> - <attack_type|-> <label>
  e.g.  LA_0039 LA_E_2834763 - A11 spoof
        LA_0030 LA_E_5849185 - -   bonafide

The protocol file maps filenames to bonafide/spoof labels.  Attack type ("-"
for bonafide) and speaker_id are parsed but not used for sampling; only the
label column matters.

Reads config from eval/config/data_paths.yaml (audio: section).
"""

import argparse
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Protocol record
# ─────────────────────────────────────────────────────────────────────────────

class ProtocolEntry(NamedTuple):
    speaker_id: str
    filename: str   # bare stem, e.g. "LA_E_2834763" (no extension)
    attack_type: str  # e.g. "A11" or "-" for bonafide
    label: str      # "bonafide" | "spoof"


# ─────────────────────────────────────────────────────────────────────────────
# Config loading
# ─────────────────────────────────────────────────────────────────────────────

def load_config(config_path: Path) -> dict:
    """Load YAML config with PyYAML if available, simple fallback otherwise."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: '{config_path}'. "
            "Ensure eval/config/data_paths.yaml exists."
        )
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("Config YAML root must be a mapping.")
        return data
    except ImportError:
        pass

    # Minimal fallback: parse only the `audio:` block we care about.
    # Handles two-space YAML indentation used in data_paths.yaml.
    result: dict = {}
    current_top: str = ""
    current_sub: str = ""
    current_subsub: str = ""

    with open(config_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(stripped)
            key_val = stripped.split(":", 1)
            key = key_val[0].strip()
            val = key_val[1].strip().strip('"').strip("'") if len(key_val) > 1 else ""

            if indent == 0 and not stripped.startswith("-"):
                current_top = key
                current_sub = ""
                current_subsub = ""
                if val:
                    result[current_top] = val
                else:
                    result.setdefault(current_top, {})
            elif indent == 2 and current_top and not stripped.startswith("-"):
                current_sub = key
                current_subsub = ""
                if val:
                    result[current_top][current_sub] = val
                else:
                    result[current_top].setdefault(current_sub, {})
            elif indent == 4 and current_top and current_sub and not stripped.startswith("-"):
                current_subsub = key
                if val:
                    result[current_top][current_sub][current_subsub] = val
                else:
                    result[current_top][current_sub].setdefault(current_subsub, {})
            elif indent == 6 and current_top and current_sub and current_subsub:
                if val:
                    result[current_top][current_sub][current_subsub][key] = val

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Protocol parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_protocol(protocol_path: Path) -> List[ProtocolEntry]:
    """Parse an ASVspoof 2019 CM protocol file.

    Expected columns (whitespace-separated):
      speaker_id  filename  -  attack_type  label
      e.g.: LA_0039 LA_E_2834763 - A11 spoof
            LA_0030 LA_E_5849185 - -   bonafide

    Args:
        protocol_path: Path to .txt protocol file.

    Returns:
        List of ProtocolEntry namedtuples.

    Raises:
        FileNotFoundError: If the protocol file does not exist.
        ValueError: If a line cannot be parsed into exactly 5 columns.
    """
    if not protocol_path.exists():
        raise FileNotFoundError(f"Protocol file not found: {protocol_path}")

    entries: List[ProtocolEntry] = []
    with open(protocol_path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 5:
                raise ValueError(
                    f"Unexpected column count ({len(parts)}) on line {lineno} "
                    f"of '{protocol_path}': {line!r}"
                )
            speaker_id, filename, _dash, attack_type, label = parts
            label_lower = label.lower()
            if label_lower not in ("bonafide", "spoof"):
                raise ValueError(
                    f"Unknown label '{label}' on line {lineno} of '{protocol_path}'."
                )
            entries.append(ProtocolEntry(
                speaker_id=speaker_id,
                filename=filename,
                attack_type=attack_type,
                label=label_lower,
            ))

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Sampling helpers
# ─────────────────────────────────────────────────────────────────────────────

def stratified_sample(
    entries: List[ProtocolEntry],
    n_bonafide: int,
    n_spoof: int,
    seed: int,
) -> Tuple[List[ProtocolEntry], List[ProtocolEntry]]:
    """Randomly sample *n_bonafide* bonafide and *n_spoof* spoof entries.

    Args:
        entries: All parsed protocol entries.
        n_bonafide: Number of bonafide samples requested.
        n_spoof: Number of spoof samples requested.
        seed: Random seed for reproducibility.

    Returns:
        Tuple ``(bonafide_samples, spoof_samples)``.
    """
    bonafide = [e for e in entries if e.label == "bonafide"]
    spoof = [e for e in entries if e.label == "spoof"]

    rng_b = random.Random(seed)
    rng_s = random.Random(seed + 1)

    sampled_bonafide = rng_b.sample(bonafide, min(n_bonafide, len(bonafide)))
    sampled_spoof = rng_s.sample(spoof, min(n_spoof, len(spoof)))

    return sampled_bonafide, sampled_spoof


# ─────────────────────────────────────────────────────────────────────────────
# Main build logic
# ─────────────────────────────────────────────────────────────────────────────

def build_audio_subset(
    config_path: Path,
    output_dir: Path,
    split: str,
    n_real: int,
    n_fake: int,
    seed: int,
    clean: bool,
) -> None:
    """Run the full subset-creation pipeline.

    Args:
        config_path: Path to eval/config/data_paths.yaml.
        output_dir: Root output directory (default: eval/data/audio_subset).
        split: Which dataset split to sample from ("train", "dev", or "eval").
        n_real: Number of bonafide (real) utterances to copy.
        n_fake: Number of spoof (fake) utterances to copy.
        seed: Random seed.
        clean: If True, remove existing output_dir before running.
    """
    config = load_config(config_path)
    audio_cfg = config.get("audio")
    if not audio_cfg:
        print(
            "[ERROR] No 'audio:' section found in config. "
            "Ensure eval/config/data_paths.yaml has been updated.",
            file=sys.stderr,
        )
        sys.exit(1)

    raw_root = Path(audio_cfg["raw_data_root"])
    protocol_dir = audio_cfg["protocol_dir"]
    audio_subdir = audio_cfg.get("audio_subdir", "flac")
    splits_map: Dict[str, str] = audio_cfg["splits"]
    protocol_files_map: Dict[str, str] = audio_cfg["protocol_files"]

    if split not in splits_map:
        print(
            f"[ERROR] Unknown split '{split}'. Available splits: {list(splits_map.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)

    split_dir_name = splits_map[split]
    protocol_filename = protocol_files_map[split]

    audio_dir = raw_root / split_dir_name / audio_subdir
    protocol_path = raw_root / protocol_dir / protocol_filename

    # Validate paths
    if not raw_root.exists():
        print(
            f"[ERROR] Raw data root does not exist: {raw_root}\n"
            f"        Update 'audio.raw_data_root' in '{config_path}'.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not audio_dir.exists():
        print(
            f"[ERROR] Audio directory does not exist: {audio_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Raw data root  : {raw_root}")
    print(f"Split          : {split}  ({split_dir_name})")
    print(f"Audio dir      : {audio_dir}")
    print(f"Protocol file  : {protocol_path}")
    print(f"Output dir     : {output_dir}")
    print(f"Sampling plan  : {n_real} real (bonafide), {n_fake} fake (spoof) - seed {seed}")
    print()

    # Parse protocol
    print("Parsing protocol file...")
    entries = parse_protocol(protocol_path)
    total_bonafide = sum(1 for e in entries if e.label == "bonafide")
    total_spoof = sum(1 for e in entries if e.label == "spoof")
    print(f"  Total entries in protocol: {len(entries)}")
    print(f"    bonafide : {total_bonafide}")
    print(f"    spoof    : {total_spoof}")
    print()

    if n_real > total_bonafide:
        print(
            f"[WARNING] Requested {n_real} bonafide but only {total_bonafide} available. "
            "Will use all available."
        )
    if n_fake > total_spoof:
        print(
            f"[WARNING] Requested {n_fake} spoof but only {total_spoof} available. "
            "Will use all available."
        )

    # Sample
    sampled_real, sampled_fake = stratified_sample(entries, n_real, n_fake, seed)
    print(f"Sampled: {len(sampled_real)} bonafide, {len(sampled_fake)} spoof")
    print()

    # Prepare output directories
    real_out = output_dir / "real"
    fake_out = output_dir / "fake"

    if clean and output_dir.exists():
        print(f"Cleaning output directory '{output_dir}'...")
        shutil.rmtree(output_dir)

    real_out.mkdir(parents=True, exist_ok=True)
    fake_out.mkdir(parents=True, exist_ok=True)

    # Copy files
    def copy_entries(
        sample: List[ProtocolEntry],
        dest_dir: Path,
        label: str,
        ext: str = ".flac",
    ) -> int:
        copied = 0
        missing = 0
        for entry in sample:
            src = audio_dir / f"{entry.filename}{ext}"
            dest = dest_dir / f"{entry.filename}{ext}"
            if not src.exists():
                print(f"  [WARNING] Source file not found, skipping: {src}")
                missing += 1
                continue
            shutil.copy2(src, dest)
            copied += 1
        if missing:
            print(f"  [WARNING] {missing} {label} files were missing from disk and skipped.")
        return copied

    print("Copying bonafide (real) audio files...")
    n_copied_real = copy_entries(sampled_real, real_out, "bonafide")

    print("Copying spoof (fake) audio files...")
    n_copied_fake = copy_entries(sampled_fake, fake_out, "spoof")

    print()
    print("[SUCCESS] Audio subset generation complete.")
    print(f"  Real (bonafide) : {n_copied_real} files -> {real_out}")
    print(f"  Fake (spoof)    : {n_copied_fake} files -> {fake_out}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    default_config = repo_root / "eval" / "config" / "data_paths.yaml"
    default_output = repo_root / "eval" / "data" / "audio_subset"

    parser = argparse.ArgumentParser(
        description=(
            "Create a stratified audio subset from the ASVspoof 2019 LA dataset "
            "(bonafide/spoof) into eval/data/audio_subset/{real,fake}/."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config,
        help=f"Path to data_paths.yaml configuration file (default: {default_config})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Target directory for the output audio subset (default: {default_output})",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="eval",
        choices=["train", "dev", "eval"],
        help="Dataset split to sample from (default: eval)",
    )
    parser.add_argument(
        "--n-real",
        type=int,
        default=150,
        help="Number of bonafide (real) utterances to include (default: 150)",
    )
    parser.add_argument(
        "--n-fake",
        type=int,
        default=150,
        help="Number of spoof (fake) utterances to include (default: 150)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling reproducibility (default: 42)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing output directory before building subset",
    )

    args = parser.parse_args()
    build_audio_subset(
        config_path=args.config,
        output_dir=args.output_dir,
        split=args.split,
        n_real=args.n_real,
        n_fake=args.n_fake,
        seed=args.seed,
        clean=args.clean,
    )


if __name__ == "__main__":
    main()
