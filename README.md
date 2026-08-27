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

## 🚀 Getting Started

*(More detailed instructions will be added as services are implemented)*

Check the `docker-compose.yml` for orchestrating the microservices, and refer to individual folder `README.md` files for specific component details.
