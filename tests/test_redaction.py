from ci_copilot.redaction import redact

# Build fake tokens at runtime so secret scanners don't flag the test file.
FAKE_GH = "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
FAKE_AWS = "AKIA" + "IOSFODNN7EXAMPLE"


def test_redacts_github_and_aws_tokens():
    out, counts = redact(f"token {FAKE_GH} key {FAKE_AWS}")
    assert FAKE_GH not in out and FAKE_AWS not in out
    assert counts["github_token"] == 1
    assert counts["aws_access_key"] == 1


def test_redacts_credentials_in_url_and_key_values():
    out, counts = redact("PYPI=https://bot:hunter22@pypi.example.com/simple password=hunter22")
    assert "hunter22" not in out
    assert counts["url_credentials"] == 1
    assert counts["key_value_secret"] == 1


def test_redacts_ip_email_and_bearer():
    out, counts = redact("from 10.1.2.3 mail a.b@example.com Authorization: Bearer abcdefghijklmnop")
    assert "10.1.2.3" not in out
    assert "a.b@example.com" not in out
    assert "abcdefghijklmnop" not in out
    assert counts == {"bearer": 1, "email": 1, "ipv4": 1}


def test_redacts_private_key_block():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY-----"
    out, counts = redact(f"before\n{pem}\nafter")
    assert "MIIEow" not in out
    assert counts["private_key"] == 1


def test_clean_text_untouched():
    text = "pytest -q\n3 passed in 0.10s"
    out, counts = redact(text)
    assert out == text and counts == {}
