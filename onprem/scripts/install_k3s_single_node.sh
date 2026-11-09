#!/usr/bin/env bash
# Single-node k3s + Argo CD for a laptop VM / home lab (no Ansible needed).
# Usage: sudo ./install_k3s_single_node.sh
set -euo pipefail

K3S_VERSION="${K3S_VERSION:-v1.30.6+k3s1}"
ARGOCD_VERSION="${ARGOCD_VERSION:-v2.13.1}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [[ $EUID -ne 0 ]]; then echo "run as root (sudo)"; exit 1; fi

if ! command -v k3s >/dev/null 2>&1; then
  echo "==> installing k3s ${K3S_VERSION}"
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -s - server --write-kubeconfig-mode 0644
else
  echo "==> k3s already installed: $(k3s --version | head -1)"
fi

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
kubectl wait --for=condition=Ready node --all --timeout=180s

echo "==> installing Argo CD ${ARGOCD_VERSION}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

echo "==> applying AppProject + root app"
kubectl apply -f "${REPO_ROOT}/argocd/project.yaml" -f "${REPO_ROOT}/argocd/root-app.yaml"

echo
echo "Argo CD initial admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
echo "UI: kubectl -n argocd port-forward svc/argocd-server 8080:443  ->  https://127.0.0.1:8080 (user: admin)"
echo "Change the admin password after first login and delete argocd-initial-admin-secret."
