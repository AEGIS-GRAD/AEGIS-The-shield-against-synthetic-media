# AEGIS `detector_text` Microservice

Synthetic text detection service replacing the stub `detector_binoculars` container on `aegis_net`.

## Capabilities & Architecture
- **Primary Backbone:** `desklib/ai-text-detector-v1.01` (`microsoft/deberta-v3-large` with mean-pooling linear head, MIT license), executed in `fp16` on CUDA or `fp32` on CPU with optional PEFT LoRA adapter loading via `AEGIS_TEXT_LORA_DIR`.
- **Long-Text Windowing:** Tokenizes without silent 512-token truncation, slices into `510`-token windows (`64`-token overlap, up to `32` evenly strided chunks), runs OOM-safe batched inference (`AEGIS_TEXT_BATCH_SIZE=4`), and aggregates logits weighted by chunk token count.
- **Forensic Corroboration Signals:**
  - Sentence-level **perplexity** and **burstiness** (coefficient of variation of per-sentence GPT-2 perplexity).
  - Linguistic **stylometry** (`stylometry.py`: vocabulary diversity, 3/4-gram repetition, sentence length CoV).
  - Opt-in small-model **Binoculars** cross-perplexity ratio (`AEGIS_TEXT_ENABLE_BINOCULARS=1`).
- **Minimum-Length Gating:**
  - `< 40` words returns `status="not_applicable"` with neutral `confidence=0.5` and `text_too_short`.
  - `40–149` words runs full inference and linearly attenuates `confidence` toward `0.5` with `short_text_attenuated`.

## Endpoints
- `GET /health` — liveness/readiness, active device, VRAM/RAM telemetry, loaded signal status.
- `POST /detect` — contract-conformant endpoint (`shared/json-api-contracts-schema/`).
- `GET /metrics` — Prometheus exposition (`detector_inference_latency_seconds`, `detector_inference_calls_total`, `detector_gpu_memory_allocated_bytes` for `model_name="detector_text"`).
- `POST /analyze` — deprecated raw-text endpoint kept for Task 3 evaluation scripts.

## Environment Variables
| Variable | Default | Purpose |
|---|---|---|
| `AEGIS_TEXT_MODEL_DIR` | `./models/desklib-base` | Local directory for Desklib weights/tokenizer |
| `AEGIS_TEXT_USE_FINETUNED` | `1` | Auto-attach committed Task 3 LoRA adapter when present |
| `AEGIS_TEXT_LORA_DIR` | `""` | Optional custom LoRA adapter override path |
| `AEGIS_TEXT_PPL_MODEL_DIR` | `./models/gpt2` | Local directory for GPT-2 perplexity scorer |
| `AEGIS_TEXT_FP16` | `1` | Use `float16` on CUDA GPUs |
| `AEGIS_TEXT_BATCH_SIZE` | `4` | Chunk batch size with automatic OOM halve-and-retry |
| `AEGIS_TEXT_ENABLE_PPL` | `1` | Enable GPT-2 perplexity & burstiness extraction |
| `AEGIS_TEXT_ENABLE_BINOCULARS` | `0` | Enable opt-in Qwen-0.5B Binoculars signal (8 GB+ GPU recommended) |
| `AEGIS_TEXT_MIN_WORDS` | `40` | Hard floor below which `status="not_applicable"` |
| `AEGIS_TEXT_RELIABLE_WORDS` | `150` | Threshold below which confidence is linearly attenuated |
| `AEGIS_TEXT_PRELOAD` | `1` | Load models during FastAPI lifespan startup |

