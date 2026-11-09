from pathlib import Path

import pytest

from ci_copilot.rules import triage

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.mark.parametrize(
    ("sample", "rule_id"),
    [
        ("failed_pytest.log", "python-module-missing"),
        ("failed_helm.log", "helm-template-error"),
        ("failed_image_pull.log", "image-pull"),
    ],
)
def test_samples_match_expected_rule(sample, rule_id):
    result = triage((SAMPLES / sample).read_text())
    assert result["matched_rule"] == rule_id
    assert result["fixes"]
    assert result["evidence"]


def test_ruff_output_detected():
    log = "app/main.py:3:8: F401 [*] `os` imported but unused\napp/x.py:1:1: I001 unsorted imports"
    assert triage(log)["category"] == "lint"


def test_unknown_log_low_confidence():
    result = triage("everything is fine but exit code 1")
    assert result["category"] == "unknown"
    assert result["confidence"] < 0.2
