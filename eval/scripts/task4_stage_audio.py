"""Stage the two small Task 6 sets: non-speech audio and dubbed clips.
  python eval/scripts/task4_stage_audio.py nonspeech
  python eval/scripts/task4_stage_audio.py dubbed
ESC-50 (CC BY-NC): download manually, set task4.raw.esc50_root.
Dubbed: put <id>.mp4 + dubbed_meta.csv (id,dub_language,original_language,source,license) in eval/data/edge_cases/dubbed/
"""
import csv, subprocess, sys
from pathlib import Path
from task4_common import ROOT, cfg, write_csv, sha256, rng

# skip ESC-50 classes with human vocalisations (they can legitimately resemble speech)
HUMAN = {"crying_baby", "sneezing", "clapping", "breathing", "coughing", "footsteps", "laughing",
         "brushing_teeth", "snoring", "drinking_sipping"}

def to_wav16k(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "16000", str(dst)], check=True)

def nonspeech():
    C = cfg(); c = C["audio_nonspeech"]; items = []
    esc = Path(C["raw"]["esc50_root"])
    if esc.exists():
        for r in csv.DictReader(open(esc / "meta/esc50.csv")):
            if r["category"] not in HUMAN:
                items.append((esc / "audio" / r["filename"], r["category"], "ESC-50", "CC BY-NC 3.0"))
    extra = Path(C["raw"]["music_noise_root"])
    if extra.exists():
        for p in extra.rglob("*"):
            if p.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg"}:
                items.append((p, p.parent.name, "extra:music_noise_root", "FILL IN per source"))
    assert items, "No source audio found - download ESC-50 / music-noise manually (see eval/DATA.md)."
    rng(1337).shuffle(items); rows = []
    for i, (p, cat, src, lic) in enumerate(items[: c["n_clips"]]):
        dst = ROOT / c["eval_dir"] / "wav" / f"ns_{i:04d}.wav"; to_wav16k(p, dst)
        rows.append(dict(sample_path=dst.relative_to(ROOT).as_posix(), modality="audio", true_label="non_speech", id=f"ns_{i:04d}", path=dst.relative_to(ROOT).as_posix(), category=cat, expected="not_applicable",
                         source=src, license=lic, sha256=sha256(dst)))
    write_csv(c["manifest"], rows, list(rows[0])); print(len(rows), "non-speech clips")

def dubbed():
    c = cfg()["audio_dubbed"]; src = ROOT / c["eval_dir"]; rows = []
    for m in csv.DictReader(open(src / "dubbed_meta.csv")):
        p = src / f"{m['id']}.mp4"
        has_a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
                                "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
        assert has_a, f"{p} has no audio stream"
        dst = p   # clips already live in eval/data/edge_cases/dubbed/
        rows.append(dict(sample_path=dst.relative_to(ROOT).as_posix(), modality="video", true_label="real_dubbed", id=m["id"], path=dst.relative_to(ROOT).as_posix(), dub_language=m["dub_language"],
                         original_language=m["original_language"], expected="syncnet_confidence_downweighted",
                         source=m["source"], license=m["license"], sha256=sha256(dst)))
    assert len(rows) >= c["min_clips"], f"only {len(rows)} dubbed clips (<{c['min_clips']})"
    write_csv(c["manifest"], rows, list(rows[0])); print(len(rows), "dubbed clips")

if __name__ == "__main__":
    {"nonspeech": nonspeech, "dubbed": dubbed}[sys.argv[1]]()
