"""Render a triage result as GitHub-flavoured Markdown."""

from __future__ import annotations


def to_markdown(result: dict, source: str, redaction_counts: dict[str, int], input_kind: str) -> str:
    conf = float(result.get("confidence", 0))
    lines = [
        "## 🤖 ci-copilot triage",
        "",
        f"| Field | Value |\n|---|---|\n| Input | `{input_kind}` |\n| Analysis source | `{source}` |"
        f"\n| Category | `{result.get('category', 'unknown')}` |\n| Confidence | {conf:.2f} |",
    ]
    if result.get("matched_rule"):
        lines.append(f"| Matched rule | `{result['matched_rule']}` |")
    lines += ["", "### Probable root cause", "", str(result.get("root_cause", "")), ""]
    lines += ["### Suggested fixes", ""]
    lines += [f"{i}. {fix}" for i, fix in enumerate(result.get("fixes", []), 1)]
    evidence = result.get("evidence") or []
    if evidence:
        lines += ["", "### Evidence (redacted)", "", "```text", *evidence, "```"]
    red = ", ".join(f"{k}={v}" for k, v in sorted(redaction_counts.items())) or "none"
    lines += [
        "",
        f"<sub>Redactions before analysis: {red}. Suggestions are AI/rule generated - verify before applying.</sub>",
        "",
    ]
    return "\n".join(lines)
