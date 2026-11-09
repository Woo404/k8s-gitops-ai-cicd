"""Deterministic rule-based triage used when no LLM is reachable.

Each rule: id, regex, category, root cause, suggested fixes.
The first rule with the most matches wins; ties go to list order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    rule_id: str
    pattern: re.Pattern[str]
    category: str
    root_cause: str
    fixes: list[str] = field(default_factory=list)


RULES: list[Rule] = [
    Rule(
        "python-module-missing",
        re.compile(r"ModuleNotFoundError: No module named '([^']+)'"),
        "dependency",
        "A Python module imported by the code or tests is not installed in the CI environment.",
        [
            "Add the missing package to requirements.txt / requirements-dev.txt and pin a version.",
            "Check the install step ran against the same Python used by pytest (setup-python version).",
            "If it is a local package, make sure `pythonpath` / `pip install -e .` is configured.",
        ],
    ),
    Rule(
        "pytest-assertion",
        re.compile(r"(?m)^(?:E\s+AssertionError|FAILED .+::.+)"),
        "test-failure",
        "One or more unit tests failed on an assertion; behaviour changed or the test expectation is stale.",
        [
            "Reproduce locally: `pytest -x -q <failing test node id>`.",
            "Read the diff between expected and actual values in the `E` lines.",
            "Decide whether the code or the test is wrong; do not just update the expectation blindly.",
        ],
    ),
    Rule(
        "ruff-lint",
        re.compile(r"(?m)^\S+\.py:\d+:\d+: [A-Z]{1,3}\d{3}"),
        "lint",
        "Ruff reported lint violations (unused imports, style or bug-prone patterns).",
        [
            "Run `ruff check . --fix` locally, then review the changes.",
            "Run `ruff format .` if the format check also failed.",
        ],
    ),
    Rule(
        "helm-template-error",
        re.compile(r"(?i)Error: (?:INSTALLATION FAILED: )?(?:template|parse error|YAML parse error)"),
        "helm",
        "Helm could not render the chart: template syntax error, missing value or bad YAML indentation.",
        [
            "Run `helm lint charts/<chart> -f <values>` and `helm template` locally to get the exact line.",
            "Check `nindent`/`indent` usage and that referenced `.Values` keys exist for every environment file.",
        ],
    ),
    Rule(
        "k8s-schema-invalid",
        re.compile(r"(?i)(?:is invalid|failed validation|additional properties .* not allowed)"),
        "kubernetes",
        "A rendered Kubernetes manifest does not match the API schema (wrong field or apiVersion).",
        [
            "Run `kubeconform -strict -summary` on `helm template` output to see the field.",
            "Check the apiVersion is supported by the target cluster version (e.g. autoscaling/v2 for HPA).",
        ],
    ),
    Rule(
        "image-pull",
        re.compile(r"(?i)(ErrImagePull|ImagePullBackOff|manifest unknown|pull access denied)"),
        "registry",
        "The cluster or runner could not pull the container image (wrong tag, private registry, no credentials).",
        [
            "Verify the tag exists in the registry (e.g. GHCR package page).",
            "For a private GHCR package create an imagePullSecret or make the package public.",
            "Check the Argo CD application points at the image tag CI actually pushed.",
        ],
    ),
    Rule(
        "docker-build",
        re.compile(r"(?i)(failed to solve|ERROR \[[^\]]+\]|COPY failed|executor failed running)"),
        "build",
        "The Docker image build failed in one of the Dockerfile steps.",
        [
            "Look at the first `ERROR [stage n/m]` line - later errors are usually consequences.",
            "Check files referenced by COPY exist in the build context and are not in .dockerignore.",
            "Rebuild locally with `docker build --progress=plain .`.",
        ],
    ),
    Rule(
        "network-timeout",
        re.compile(r"(?i)(connection timed out|read timed out|temporary failure in name resolution|ETIMEDOUT)"),
        "network",
        "A network call (package index, registry, API) timed out or DNS failed on the runner.",
        [
            "Re-run the job once; if it persists, check mirror/proxy settings.",
            "Add retries or a cache for dependency downloads.",
        ],
    ),
    Rule(
        "permission-denied",
        re.compile(r"(?i)(permission denied|403 Forbidden|resource not accessible by integration)"),
        "permissions",
        "The job lacks permission (file mode, token scope or workflow `permissions:` block).",
        [
            "For scripts: `chmod +x` and commit the mode change (`git update-index --chmod=+x`).",
            "For GitHub API/registry: add the needed `permissions:` (e.g. packages: write, pull-requests: write).",
        ],
    ),
]


def triage(text: str) -> dict:
    """Return a triage result dict using rules only."""
    best: Rule | None = None
    best_hits = 0
    evidence: list[str] = []
    for rule in RULES:
        hits = rule.pattern.findall(text)
        if len(hits) > best_hits:
            best, best_hits = rule, len(hits)
    if best is None:
        return {
            "category": "unknown",
            "root_cause": "No known failure pattern matched. Read the first error line in the log.",
            "fixes": [
                "Search the log for the first `error`/`failed` line, not the last one.",
                "Re-run the failing step locally with verbose output.",
            ],
            "confidence": 0.1,
            "matched_rule": None,
            "evidence": [],
        }
    for line in text.splitlines():
        if best.pattern.search(line):
            evidence.append(line.strip()[:200])
        if len(evidence) >= 3:
            break
    return {
        "category": best.category,
        "root_cause": best.root_cause,
        "fixes": list(best.fixes),
        "confidence": 0.5 if best_hits == 1 else 0.6,
        "matched_rule": best.rule_id,
        "evidence": evidence,
    }
