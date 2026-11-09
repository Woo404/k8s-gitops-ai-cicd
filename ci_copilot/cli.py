"""Command line entry point.

Examples:
  ci-copilot --log build.log
  cat build.log | ci-copilot --log -
  git diff origin/main... | ci-copilot --diff - --output triage.md
  ci-copilot --log build.log --no-llm --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from ci_copilot import __version__
from ci_copilot.llm import LLMConfig, LLMError, ask_llm
from ci_copilot.redaction import redact
from ci_copilot.render import to_markdown
from ci_copilot.rules import triage

MAX_CHARS = 12000


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def tail_relevant(text: str, max_chars: int = MAX_CHARS) -> str:
    """Keep the part of a long log most likely to contain the failure.

    CI logs are huge; errors are usually near the end. We keep the last
    `max_chars` characters, but start at a line boundary.
    """
    if len(text) <= max_chars:
        return text
    cut = text[-max_chars:]
    nl = cut.find("\n")
    return cut[nl + 1 :] if nl != -1 else cut


def analyze(raw: str, input_kind: str, use_llm: bool, config: LLMConfig | None = None, opener=None):
    scrubbed, counts = redact(raw)
    scrubbed = tail_relevant(scrubbed)
    source = "rule_fallback"
    result = None
    error = None
    if use_llm:
        try:
            kwargs = {"opener": opener} if opener else {}
            result = ask_llm(scrubbed, input_kind, config or LLMConfig.from_env(), **kwargs)
            source = "llm"
        except LLMError as exc:
            error = str(exc)
    if result is None:
        result = triage(scrubbed)
    return result, source, counts, error


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ci-copilot", description="AI-assisted CI failure triage")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--log", help="path to failed CI log, or - for stdin")
    src.add_argument("--diff", help="path to a git diff to review, or - for stdin")
    p.add_argument("--no-llm", action="store_true", help="rules only, never call an LLM")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--output", help="also write Markdown to this file (e.g. PR comment body)")
    p.add_argument(
        "--fail-on-error",
        action="store_true",
        help="exit 2 if the LLM was requested but unreachable (default: degrade to rules)",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_kind = "ci_log" if args.log else "git_diff"
    raw = _read(args.log or args.diff)
    use_llm = not args.no_llm and os.getenv("CI_COPILOT_DISABLE_LLM", "").lower() not in ("1", "true")
    result, source, counts, error = analyze(raw, input_kind, use_llm)
    if error:
        print(f"[ci-copilot] LLM unavailable, used rule fallback: {error}", file=sys.stderr)
        if args.fail_on_error:
            return 2
    md = to_markdown(result, source, counts, input_kind)
    if args.json:
        print(json.dumps({**result, "analysis_source": source, "redaction_counts": counts}, indent=2))
    else:
        print(md)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(md)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    return 0
