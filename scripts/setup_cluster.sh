#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"
CLUSTER_NAME="soka-datacenter"
if command -v docker.exe >/dev/null 2>&1; then
    DOCKER_BIN="docker.exe"
    VM_WORKER_DIR="$(wslpath -w "${PROJECT_ROOT}/vm_worker")"
else
    DOCKER_BIN="docker"
    VM_WORKER_DIR="${PROJECT_ROOT}/vm_worker"
fi
if command -v kind.exe >/dev/null 2>&1; then
    KIND_BIN="kind.exe"
    KUBECTL_BIN="kubectl.exe"
else
    KIND_BIN="kind"
    KUBECTL_BIN="kubectl"
fi

echo "=== [1/5] Building VM Worker Docker Image ==="
"${DOCKER_BIN}" build -t soka-vm-worker:latest "${VM_WORKER_DIR}"

echo "=== [2/5] Creating Multi-Node Kubernetes Cluster ==="
if "${KIND_BIN}" get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "Cluster ${CLUSTER_NAME} already exists."
else
    "${KIND_BIN}" create cluster --config ./k8s/kind-cluster.yaml
fi

echo "=== [3/5] Loading Docker Image ==="
"${KIND_BIN}" load docker-image soka-vm-worker:latest --name "${CLUSTER_NAME}"

echo "=== [4/5] Deploying 4 VM Pods ==="
"${KUBECTL_BIN}" apply -f ./k8s/vm-pods.yaml

echo "=== [5/5] Waiting for VM Pods ==="
"${KUBECTL_BIN}" wait --namespace soka-cloud --for=condition=ready pod --all --timeout=120s

"${KUBECTL_BIN}" get nodes -o wide --show-labels
"${KUBECTL_BIN}" get pods -n soka-cloud -o wide
