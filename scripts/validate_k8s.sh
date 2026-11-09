#!/usr/bin/env bash
# Local equivalent of the CI "k8s" job: helm lint + template + kubeconform.
set -euo pipefail
cd "$(dirname "$0")/.."
CHART=charts/aiops-log-assistant
HELM="${HELM:-helm}"
KUBECONFORM="${KUBECONFORM:-kubeconform}"
mkdir -p rendered
for env in dev prod; do
  echo "==> helm lint ($env)"
  "$HELM" lint "$CHART" -f "environments/$env/values.yaml"
  echo "==> helm template ($env)"
  "$HELM" template aiops "$CHART" -n "aiops-$env" -f "environments/$env/values.yaml" > "rendered/$env.yaml"
  echo "    $(grep -c '^kind:' "rendered/$env.yaml") objects -> rendered/$env.yaml"
done
echo "==> kubeconform (k8s 1.30, CRDs from datree catalog when available)"
"$KUBECONFORM" -strict -summary -kubernetes-version 1.30.0 \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -ignore-missing-schemas \
  rendered/dev.yaml rendered/prod.yaml argocd/*.yaml argocd/apps/*.yaml
