#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="soka-datacenter"
CONTEXT_NAME="kind-${CLUSTER_NAME}"
IMAGE_NAME="soka-vm-worker:phase3"
NODE_IMAGE="kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5"
BIN_DIR="${SOKA_BIN_DIR:-${HOME}/.local/bin}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RECREATE="${1:-}"

export PATH="${BIN_DIR}:${PATH}"
cd "${PROJECT_ROOT}"

for command_name in docker kind kubectl curl; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "Missing required command: ${command_name}" >&2
        exit 1
    fi
done

docker info >/dev/null
CPU_COUNT="$(getconf _NPROCESSORS_ONLN)"
MEMORY_KIB="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if (( CPU_COUNT < 4 )); then
    echo "At least 4 logical CPUs are required; found ${CPU_COUNT}" >&2
    exit 1
fi
if (( MEMORY_KIB < 4194304 )); then
    echo "At least 4 GiB RAM is required" >&2
    exit 1
fi
if [[ "$(stat -fc %T /sys/fs/cgroup)" != "cgroup2fs" ]]; then
    echo "cgroup v2 is required for CPU measurement" >&2
    exit 1
fi

if [[ "${RECREATE}" == "--recreate" ]] && kind get clusters | grep -Fxq "${CLUSTER_NAME}"; then
    kind delete cluster --name "${CLUSTER_NAME}"
fi

if kind get clusters | grep -Fxq "${CLUSTER_NAME}"; then
    echo "Using existing cluster ${CLUSTER_NAME}; pass --recreate to rebuild it with the pinned node image."
else
    kind create cluster \
        --config ./k8s/kind-cluster.yaml \
        --image "${NODE_IMAGE}" \
        --wait 180s
fi

kubectl config use-context "${CONTEXT_NAME}" >/dev/null
docker build --pull --tag "${IMAGE_NAME}" ./vm_worker
kind load docker-image "${IMAGE_NAME}" --name "${CLUSTER_NAME}"

kubectl delete pod \
    --namespace soka-cloud \
    --selector app=soka-vm \
    --ignore-not-found \
    --wait=true
kubectl apply --filename ./k8s/vm-pods.yaml
kubectl wait \
    --namespace soka-cloud \
    --for=condition=Ready \
    pod \
    --selector app=soka-vm \
    --timeout=180s

kubectl get nodes --output wide --show-labels
kubectl get pods --namespace soka-cloud --output wide
for port in 30081 30082 30083 30084; do
    curl --fail --silent --show-error "http://127.0.0.1:${port}/health" >/dev/null
done
echo "All four worker health checks passed."
