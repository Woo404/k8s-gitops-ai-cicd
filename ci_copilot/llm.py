"""Minimal OpenAI-compatible chat client (stdlib only, so the Action has no deps).

Works with Ollama (`http://localhost:11434/v1`), vLLM, or any hosted
OpenAI-compatible endpoint, selected purely via environment variables.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

SYSTEM_PROMPT = """You are a senior DevOps engineer doing CI failure triage.
You receive a REDACTED CI log or git diff. Rules:
- Base every statement on the given text; do not invent file names, hosts, versions or secrets.
- If the evidence is insufficient, say so and lower the confidence.
- Reply with ONE JSON object only, keys:
  category (string), root_cause (string), fixes (array of short strings, max 5),
  confidence (number 0..1), evidence (array of up to 3 exact lines copied from input).
"""


class LLMError(RuntimeError):
    """Raised when the LLM is unreachable or returns unusable output."""


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "qwen2.5:7b"
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            base_url=os.getenv("CI_COPILOT_LLM_BASE_URL", cls.base_url).rstrip("/"),
            api_key=os.getenv("CI_COPILOT_LLM_API_KEY", cls.api_key),
            model=os.getenv("CI_COPILOT_LLM_MODEL", cls.model),
            timeout=float(os.getenv("CI_COPILOT_LLM_TIMEOUT", str(cls.timeout))),
        )


def _extract_json(content: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or prose; take the first object."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise LLMError("model reply contained no JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"model reply was not valid JSON: {exc}") from exc
    for key in ("category", "root_cause", "fixes"):
        if key not in data:
            raise LLMError(f"model reply missing key: {key}")
    data.setdefault("confidence", 0.5)
    data.setdefault("evidence", [])
    data["fixes"] = [str(f) for f in data["fixes"]][:5]
    data["confidence"] = max(0.0, min(1.0, float(data["confidence"])))
    return data


def build_messages(text: str, input_kind: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Input type: {input_kind}\n-----\n{text}\n-----"},
    ]


def ask_llm(text: str, input_kind: str, config: LLMConfig, opener=urllib.request.urlopen) -> dict:
    """Call /chat/completions and return the parsed triage dict.

    `opener` is injectable so tests never touch the network.
    """
    body = json.dumps(
        {
            "model": config.model,
            "messages": build_messages(text, input_kind),
            "temperature": 0.1,
        }
    ).encode()
    req = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"},
        method="POST",
    )
    try:
        with opener(req, timeout=config.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("unexpected response shape from LLM") from exc
    return _extract_json(content)
