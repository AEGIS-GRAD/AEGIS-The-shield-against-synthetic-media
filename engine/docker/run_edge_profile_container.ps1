# PowerShell runner for edge profiling container with strict resource caps
param(
    [string]$ImageTag = "aegis-edge-profile:latest",
    [string]$Cpus = "4",
    [string]$Memory = "4g"
)

Write-Host "Building Edge Emulation Profiling Container ($ImageTag)..."
docker build -f engine/docker/Dockerfile.edge_profile -t $ImageTag .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed"
    exit 1
}

Write-Host "Running Edge Hardware Profiler with --cpus=$Cpus --memory=$Memory..."
docker run --rm --cpus=$Cpus --memory=$Memory -v "${PWD}/engine/benchmark:/app/engine/benchmark" $ImageTag

if ($LASTEXITCODE -eq 0) {
    Write-Host "Edge profiling container completed successfully."
} else {
    Write-Error "Edge profiling container exited with code $LASTEXITCODE"
}
