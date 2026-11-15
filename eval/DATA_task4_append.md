
---

# Task 4 Evaluation Sets (Image, Text, Audio Guardrails)

Evaluation and fine-tuning data are kept **separate**. Following the storage policy above, raw data is downloaded **manually** to a path **outside** the repo and registered under `task4:` in `eval/config/data_paths.yaml`. Staged sets go to `eval/data/` (gitignored).

| Set | Staged to | Source | License / access | Notes |
|---|---|---|---|---|
| Image real vs generated | `eval/data/image_eval/` | OpenFake subset (manual download) | Mixed - **non-commercial subsets exist**; confirm per subset | Whole generators held out of fine-tuning; clean + `jpeg75`/`jpeg50`/`resize0.5` variants |
| Image in-the-wild | `eval/data/image_eval/reddit/` | OpenFake Reddit split | As above | Never used for fine-tuning |
| Text human vs LLM | `eval/data/text_eval/` | Human: CNN/DailyMail (verify license). LLM: freshly generated for this eval | Dataset terms / our own output | short + long, clean + paraphrased |
| Non-speech audio (Task 6) | `eval/data/audio_nonspeech/` | ESC-50 (+ optional music/noise) | ESC-50: CC BY-NC 3.0 | 16 kHz mono; expected verdict `not_applicable` |
| Dubbed clips (Task 6) | `eval/data/edge_cases/dubbed/` | Fill in per clip in `dubbed_meta.csv` | Per clip | Expected: SyncNet confidence down-weighted |

## Workflow
```bash
pip install datasets pillow pyyaml anthropic
python eval/scripts/task4_stage_images.py --list-generators   # then set task4.image.eval_generators
python eval/scripts/task4_stage_images.py
python eval/scripts/task4_stage_text.py                        # needs ANTHROPIC_API_KEY
python eval/scripts/task4_stage_audio.py nonspeech
python eval/scripts/task4_stage_audio.py dubbed                # after adding clips + dubbed_meta.csv
python eval/scripts/task4_validate_eval_sets.py                # writes eval/reports/task4_split_note.md
```
Manifests include `sample_path, modality, true_label` as their first columns, matching `eval/data/eval_manifest.csv`, plus `generator`, `variant`, `parent_id`, `source`, `license`, `sha256`.
