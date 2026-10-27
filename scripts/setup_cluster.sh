#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
CLUSTER_NAME="soka-datacenter"

echo "=== [1/5] Building VM Worker Docker Image ==="
docker build -t soka-vm-worker:latest ./vm_worker

echo "=== [2/5] Creating Multi-Node Kubernetes Cluster ==="
if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "Cluster ${CLUSTER_NAME} already exists."
else
    kind create cluster --config ./k8s/kind-cluster.yaml
fi

echo "=== [3/5] Loading Docker Image ==="
kind load docker-image soka-vm-worker:latest --name "${CLUSTER_NAME}"

echo "=== [4/5] Deploying 4 VM Pods ==="
kubectl apply -f ./k8s/vm-pods.yaml

echo "=== [5/5] Waiting for VM Pods ==="
kubectl wait --namespace soka-cloud --for=condition=ready pod --all --timeout=120s

kubectl get nodes -o wide --show-labels
kubectl get pods -n soka-cloud -o wide
