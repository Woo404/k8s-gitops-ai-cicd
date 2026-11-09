import io
import json
from pathlib import Path

from ci_copilot import cli
from ci_copilot.llm import LLMConfig

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener_returning(content: str, captured: dict):
    def opener(req, timeout):
        captured["body"] = json.loads(req.data.decode())
        captured["url"] = req.full_url
        payload = {"choices": [{"message": {"content": content}}]}
        return _FakeResp(json.dumps(payload).encode())

    return opener


def test_llm_path_uses_redacted_text():
    captured: dict = {}
    reply = (
        '```json\n{"category":"dependency","root_cause":"httpx missing","fixes":["add httpx"],"confidence":0.8}\n```'
    )
    raw = (SAMPLES / "failed_pytest.log").read_text()
    result, source, counts, error = cli.analyze(
        raw, "ci_log", True, LLMConfig(base_url="http://llm.test/v1"), _opener_returning(reply, captured)
    )
    assert source == "llm" and error is None
    assert result["root_cause"] == "httpx missing"
    sent = captured["body"]["messages"][1]["content"]
    assert "S3cr3tPassw0rd" not in sent
    assert "10.20.30.40" not in sent
    assert captured["url"] == "http://llm.test/v1/chat/completions"
    assert counts["url_credentials"] == 1


def test_falls_back_to_rules_when_llm_unreachable():
    def broken_opener(req, timeout):
        raise OSError("connection refused")

    raw = (SAMPLES / "failed_helm.log").read_text()
    result, source, _counts, error = cli.analyze(raw, "ci_log", True, LLMConfig(), broken_opener)
    assert source == "rule_fallback"
    assert "connection refused" in error
    assert result["matched_rule"] == "helm-template-error"


def test_bad_llm_json_falls_back():
    raw = (SAMPLES / "failed_pytest.log").read_text()
    result, source, _c, error = cli.analyze(raw, "ci_log", True, LLMConfig(), _opener_returning("sorry, no idea", {}))
    assert source == "rule_fallback" and "no JSON" in error


def test_main_writes_output_and_step_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    out = tmp_path / "comment.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rc = cli.main(["--log", str(SAMPLES / "failed_image_pull.log"), "--no-llm", "--output", str(out)])
    assert rc == 0
    md = out.read_text()
    assert "ci-copilot triage" in md and "image-pull" in md
    assert "AKIAIOSFODNN7EXAMPLE" not in md
    assert summary.read_text().startswith("## ")
    assert "Suggested fixes" in capsys.readouterr().out


def test_fail_on_error_exit_code(monkeypatch):
    monkeypatch.setenv("CI_COPILOT_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("CI_COPILOT_LLM_TIMEOUT", "1")
    rc = cli.main(["--log", str(SAMPLES / "failed_helm.log"), "--fail-on-error"])
    assert rc == 2


def test_tail_relevant_keeps_end():
    text = "\n".join(f"line {i}" for i in range(5000)) + "\nE   ModuleNotFoundError: No module named 'x'"
    kept = cli.tail_relevant(text, max_chars=200)
    assert kept.endswith("No module named 'x'")
    assert len(kept) <= 200
