#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
mkdir -p "$HOME/.local/bin"

if ! command -v kubectl >/dev/null 2>&1; then
    K8S_VER="$(curl -L -s https://dl.k8s.io/release/stable.txt)"
    curl -Lo "$HOME/.local/bin/kubectl" "https://dl.k8s.io/release/${K8S_VER}/bin/linux/amd64/kubectl"
    chmod +x "$HOME/.local/bin/kubectl"
fi

if ! command -v kind >/dev/null 2>&1; then
    curl -Lo "$HOME/.local/bin/kind" https://kind.sigs.k8s.io/dl/v0.27.0/kind-linux-amd64
    chmod +x "$HOME/.local/bin/kind"
fi

kubectl version --client
kind version
