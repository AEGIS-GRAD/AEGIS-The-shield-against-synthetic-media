# Run command script for Jetson-class edge hardware emulation profiling container
# Enforces exact edge limits: 4 vCPUs and 4 GB RAM

# Linux/Bash:
# docker build -f engine/docker/Dockerfile.edge_profile -t aegis-edge-profile:latest .
# docker run --rm --cpus=4 --memory=4g -v "$(pwd)/engine/benchmark:/app/engine/benchmark" aegis-edge-profile:latest

# Windows PowerShell:
# docker build -f engine/docker/Dockerfile.edge_profile -t aegis-edge-profile:latest .
# docker run --rm --cpus=4 --memory=4g -v "${PWD}/engine/benchmark:/app/engine/benchmark" aegis-edge-profile:latest
