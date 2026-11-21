# 🛡️ AEGIS

**AEGIS** (Agentic, Edge-optimized, explainable deepfake verIfication System) is a comprehensive framework designed to detect, analyze, and explain synthetic media.

## 🏗️ System Architecture

The system consists of three main operational layers:
1. **Orchestration Agent (`orchestrator/`)**: The intelligent planning layer that determines which detectors to invoke based on the input modality, risk profile, and compute budget.
2. **Hardware-aware Inference Engine (`engine/`)**: Handles model quantization, pruning, and ONNX/TensorRT export for lightning-fast edge deployment.
3. **Multi-Agent Debate & Explainability (`debate/`)**: Arbitrates conflicting detector outputs and produces human-readable chain-of-evidence reports.

## 📂 Project Structure

This repository is organized as a monorepo, where each main component resides in its own dedicated folder. This structure allows for independent development, testing, and deployment of the microservices while maintaining a cohesive overall architecture.

- **`orchestrator/`** - Planning agent for detector invocation.
- **`engine/`** - Hardware-aware inference and deployment optimizations.
- **`detectors/`** - Independent microservices for specific deepfake detection models (e.g., Video Classifier, rPPG, AASIST, SyncNet).
- **`debate/`** - Multi-agent arbitration and reporting layer.
- **`eval/`** - Benchmarking, evaluation, and dataset tools.
- **`web/`** - Frontend user interface for uploading and viewing reports.
- **`mcp/`** - Model Context Protocol server exposing AEGIS as tools for external agents.
- **`security/`** - Wazuh SIEM agent and custom decoders for live monitoring.
- **`shared/`** - Shared utilities, global configurations, API contracts, and documentation across all microservices.
- **`.github/workflows/`** - CI/CD pipelines (automated Docker build verification).

## 🎯 Model Scope

For details on the 6 finalized detector models (covering video frame-level, video physiological, audio-visual sync, audio voice spoofing, text, and image), see [Model Scope Document](shared/docs/model_scope.md).

## 📝 Failure Notes

See [docs/failure_notes.md](docs/failure_notes.md) for per-detector failure tracking.

## 🚀 Getting Started

1. Clone the repository:
   ```bash
   git clone https://github.com/user/AEGIS.git
   cd AEGIS
   ```
2. Verify / download detector model weights:
   ```bash
   python scripts/setup_models.py
   ```
3. Start the entire system (all detector microservices, orchestrator, and web interface):
   ```bash
   docker compose up --build -d
   ```
4. Access the services:
   - **Web Interface**: `http://localhost:3000`
   - **Orchestrator API**: `http://localhost:8000`
   - **API Gateway**: `http://localhost:8081`
   - **Grafana Observability Dashboard**: `http://localhost:3001` (admin / admin)

