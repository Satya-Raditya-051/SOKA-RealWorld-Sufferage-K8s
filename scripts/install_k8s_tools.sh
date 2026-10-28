#!/usr/bin/env bash
set -euo pipefail

KUBECTL_VERSION="v1.37.1"
KIND_VERSION="v0.33.0"
BIN_DIR="${SOKA_BIN_DIR:-${HOME}/.local/bin}"

case "$(uname -m)" in
    x86_64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) echo "Unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

mkdir -p "${BIN_DIR}"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TEMP_DIR}"' EXIT

KUBECTL_URL="https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH}/kubectl"
curl --fail --location --retry 3 --output "${TEMP_DIR}/kubectl" "${KUBECTL_URL}"
curl --fail --location --retry 3 --output "${TEMP_DIR}/kubectl.sha256" "${KUBECTL_URL}.sha256"
KUBECTL_EXPECTED="$(tr -d '[:space:]' < "${TEMP_DIR}/kubectl.sha256")"
KUBECTL_ACTUAL="$(sha256sum "${TEMP_DIR}/kubectl" | awk '{print $1}')"
if [[ "${KUBECTL_ACTUAL}" != "${KUBECTL_EXPECTED}" ]]; then
    echo "kubectl checksum verification failed" >&2
    exit 1
fi
install -m 0755 "${TEMP_DIR}/kubectl" "${BIN_DIR}/kubectl"

KIND_ASSET="kind-linux-${ARCH}"
KIND_URL="https://kind.sigs.k8s.io/dl/${KIND_VERSION}/${KIND_ASSET}"
curl --fail --location --retry 3 --output "${TEMP_DIR}/${KIND_ASSET}" "${KIND_URL}"
curl --fail --location --retry 3 --output "${TEMP_DIR}/${KIND_ASSET}.sha256sum" "${KIND_URL}.sha256sum"
(
    cd "${TEMP_DIR}"
    sha256sum --check "${KIND_ASSET}.sha256sum"
)
install -m 0755 "${TEMP_DIR}/${KIND_ASSET}" "${BIN_DIR}/kind"

export PATH="${BIN_DIR}:${PATH}"
kubectl version --client
kind version
echo "Installed pinned binaries in ${BIN_DIR}"
