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

## 🚀 Getting Started

The infrastructure is currently fully dockerized with placeholder stubs to allow isolated development.

1. Clone the repository.
2. Run `docker compose up -d` to spin up the entire `aegis_net` network and stub containers.
3. Review the API Schemas in `shared/json-api-contracts-schema/` before building your service endpoints.
4. **Note:** Direct pushes to `main` are blocked. You must open a Pull Request, pass the `validate-docker` CI check, and receive a peer review approval before merging.
