"""Secret / PII redaction applied BEFORE any text is sent to an LLM.

CI logs often leak tokens, passwords in URLs, cloud keys and internal IPs.
Redact first, analyze second. Patterns are intentionally conservative:
a false positive (over-redaction) is cheaper than a leaked credential.
"""

from __future__ import annotations

import re

# (category, pattern, replacement)
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"), "[REDACTED_GH_TOKEN]"),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GH_TOKEN]"),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    ("aliyun_access_key", re.compile(r"\bLTAI[0-9A-Za-z]{12,24}\b"), "[REDACTED_ALIYUN_KEY]"),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_API_KEY]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    (
        "bearer",
        re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
        r"\1[REDACTED]",
    ),
    (
        "url_credentials",
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"),
        r"\1[REDACTED]@",
    ),
    (
        "key_value_secret",
        re.compile(
            r"(?i)\b((?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)"
            r"\s*[=:]\s*)(['\"]?)[^\s'\"]{4,}\2"
        ),
        r"\1\2[REDACTED]\2",
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (
        "ipv4",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"),
        "[REDACTED_IP]",
    ),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return (redacted_text, counts_per_category)."""
    counts: dict[str, int] = {}
    out = text
    for category, pattern, repl in _PATTERNS:
        out, n = pattern.subn(repl, out)
        if n:
            counts[category] = counts.get(category, 0) + n
    return out, counts
