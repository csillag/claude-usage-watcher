# claude-usage-watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-shot Python CLI that prints the current Claude Max subscription usage (5h session, 7d weekly, per-model breakdowns) as pretty-printed JSON, fetched from `https://api.anthropic.com/api/oauth/usage` using the OAuth credentials Claude Code already stores at `~/.claude/.credentials.json`.

**Architecture:** Single Python script (stdlib only) at `bin/claude-usage`. Loads credentials, refreshes if expired (or on 401 retry), GETs the usage endpoint, prints the response body verbatim with `json.dumps(indent=2)`. Atomic write of refreshed credentials back to disk. No third-party dependencies, no virtualenv, no package metadata.

**Tech Stack:** Python 3 (stdlib: `json`, `urllib.request`, `urllib.error`, `os`, `sys`, `time`, `pathlib`, `tempfile`, `unittest`, `unittest.mock`, `importlib.util`).

---

## Spec Reference

This plan implements `docs/superpowers/specs/2026-05-10-claude-usage-watcher-design.md`. If a step here contradicts the spec, the spec wins — pause and reconcile.

## Repository Layout (target end state)

```
claude-usage-watcher/
├── bin/
│   └── claude-usage              # the script, executable, no .py extension
├── tests/
│   ├── conftest.py               # importlib loader so tests can import bin/claude-usage
│   └── test_claude_usage.py      # unittest suite, stdlib only
├── docs/
│   └── superpowers/
│       ├── specs/2026-05-10-claude-usage-watcher-design.md
│       └── plans/2026-05-10-claude-usage-watcher.md       # this file
├── Makefile                      # `make test`, `make install`
├── README.md
└── .gitignore
```

---

## Task 1: Repo Skeleton

**Files:**
- Create: `.gitignore`
- Create: `bin/claude-usage` (shebang + module docstring only at this stage)
- Create: `tests/conftest.py`
- Create: `tests/test_claude_usage.py` (one trivial smoke test)
- Create: `Makefile`

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
*.swp
.venv/
```

- [ ] **Step 2: Create `bin/claude-usage` with shebang and docstring only**

```python
#!/usr/bin/env python3
"""claude-usage: print current Claude Max subscription usage as pretty JSON.

Reads OAuth credentials from ~/.claude/.credentials.json (the same file
Claude Code uses), refreshes the access token if expired, GETs
https://api.anthropic.com/api/oauth/usage, and prints the response body
with json.dumps(indent=2). All errors go to stderr; only JSON to stdout.
"""
```

Then `chmod +x bin/claude-usage`.

- [ ] **Step 3: Create `tests/conftest.py`**

This is the bridge that lets tests import the no-extension script as a module.

```python
"""Test configuration: load bin/claude-usage as an importable module.

The CLI script lives at bin/claude-usage with no .py extension (it's the
artifact that ships to $PATH). To unit-test its functions, we use
importlib to load it under the module name `claude_usage`.
"""
import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "bin" / "claude-usage"
_spec = importlib.util.spec_from_file_location("claude_usage", _SCRIPT_PATH)
claude_usage = importlib.util.module_from_spec(_spec)
sys.modules["claude_usage"] = claude_usage
_spec.loader.exec_module(claude_usage)
```

- [ ] **Step 4: Create `tests/test_claude_usage.py` smoke test**

```python
import unittest
from tests.conftest import claude_usage


class SmokeTest(unittest.TestCase):
    def test_module_loads(self):
        self.assertTrue(hasattr(claude_usage, "__doc__"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Create `Makefile`**

```makefile
PYTHON ?= python3
INSTALL_DIR ?= $(HOME)/local/bin

.PHONY: test install clean

test:
	$(PYTHON) -m unittest discover -s tests -v

install: bin/claude-usage
	mkdir -p $(INSTALL_DIR)
	cp bin/claude-usage $(INSTALL_DIR)/claude-usage
	chmod +x $(INSTALL_DIR)/claude-usage
	@echo "Installed to $(INSTALL_DIR)/claude-usage"

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
	find . -name '*.pyc' -delete
```

- [ ] **Step 6: Run smoke test**

Run: `make test`
Expected: `OK` with 1 test passed.

- [ ] **Step 7: Commit**

```bash
git add .gitignore bin/claude-usage tests/conftest.py tests/test_claude_usage.py Makefile
git commit -m "scaffold: skeleton with importable bin/claude-usage and smoke test"
```

---

## Task 2: `load_credentials()`

Reads `~/.claude/.credentials.json` and returns the `claudeAiOauth` sub-object as a `dict`. Raises `CredentialsError` (a custom exception class) on missing file, unreadable JSON, or missing block.

**Files:**
- Modify: `bin/claude-usage`
- Modify: `tests/test_claude_usage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_usage.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from tests.conftest import claude_usage


class LoadCredentialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".credentials.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, payload):
        self.path.write_text(json.dumps(payload))

    def test_returns_oauth_block(self):
        self._write({"claudeAiOauth": {"accessToken": "tok", "expiresAt": 1, "refreshToken": "r"}})
        result = claude_usage.load_credentials(self.path)
        self.assertEqual(result["accessToken"], "tok")

    def test_missing_file_raises(self):
        with self.assertRaises(claude_usage.CredentialsError):
            claude_usage.load_credentials(self.path)

    def test_malformed_json_raises(self):
        self.path.write_text("{not json")
        with self.assertRaises(claude_usage.CredentialsError):
            claude_usage.load_credentials(self.path)

    def test_missing_oauth_block_raises(self):
        self._write({"somethingElse": {}})
        with self.assertRaises(claude_usage.CredentialsError):
            claude_usage.load_credentials(self.path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: 4 failures, all with `AttributeError: module 'claude_usage' has no attribute 'CredentialsError'` or `load_credentials`.

- [ ] **Step 3: Implement `CredentialsError` and `load_credentials` in `bin/claude-usage`**

Append below the docstring in `bin/claude-usage`:

```python
import json
import os
from pathlib import Path

DEFAULT_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


class CredentialsError(Exception):
    """Raised when credentials cannot be loaded or parsed."""


def load_credentials(path=DEFAULT_CREDENTIALS_PATH):
    """Read the credentials file and return the claudeAiOauth dict.

    Raises CredentialsError on missing file, malformed JSON, or missing
    claudeAiOauth block.
    """
    path = Path(path)
    if not path.exists():
        raise CredentialsError(
            f"No credentials file at {path}. Run `claude` to authenticate first."
        )
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise CredentialsError(f"Credentials file at {path} is malformed: {e}") from e
    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        raise CredentialsError(
            f"Credentials file at {path} has no claudeAiOauth block."
        )
    return oauth
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: 5 OK (1 smoke + 4 new).

- [ ] **Step 5: Commit**

```bash
git add bin/claude-usage tests/test_claude_usage.py
git commit -m "feat: load_credentials reads claudeAiOauth from credentials file"
```

---

## Task 3: `is_expired()`

Compares `expiresAt` (epoch milliseconds) to current time with a 60-second skew margin.

**Files:**
- Modify: `bin/claude-usage`
- Modify: `tests/test_claude_usage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_usage.py`:

```python
import time
from unittest.mock import patch


class IsExpiredTest(unittest.TestCase):
    def test_far_future_not_expired(self):
        creds = {"expiresAt": int(time.time() * 1000) + 3_600_000}  # +1h
        self.assertFalse(claude_usage.is_expired(creds))

    def test_far_past_expired(self):
        creds = {"expiresAt": int(time.time() * 1000) - 3_600_000}  # -1h
        self.assertTrue(claude_usage.is_expired(creds))

    def test_within_skew_margin_treated_as_expired(self):
        # 30s in the future, but skew is 60s -> treat as expired
        creds = {"expiresAt": int(time.time() * 1000) + 30_000}
        self.assertTrue(claude_usage.is_expired(creds))

    def test_just_past_skew_margin_not_expired(self):
        # 90s in the future, beyond 60s skew -> not expired
        creds = {"expiresAt": int(time.time() * 1000) + 90_000}
        self.assertFalse(claude_usage.is_expired(creds))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: 4 failures with `AttributeError: ... 'is_expired'`.

- [ ] **Step 3: Implement `is_expired`**

Append to `bin/claude-usage`:

```python
import time

EXPIRY_SKEW_SECONDS = 60


def is_expired(creds, now=None):
    """Return True if the access token is expired or expiring soon.

    `expiresAt` in the credentials file is epoch milliseconds.
    A 60-second skew margin avoids racing the token boundary.
    """
    if now is None:
        now = time.time()
    expires_at_ms = creds.get("expiresAt")
    if expires_at_ms is None:
        return True
    return (expires_at_ms / 1000.0) - EXPIRY_SKEW_SECONDS <= now
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: 9 OK.

- [ ] **Step 5: Commit**

```bash
git add bin/claude-usage tests/test_claude_usage.py
git commit -m "feat: is_expired with 60s skew margin"
```

---

## Task 4: `fetch_usage()`

GETs `https://api.anthropic.com/api/oauth/usage` with `Authorization: Bearer <token>` and `anthropic-beta: oauth-2025-04-20`. Returns parsed JSON. Raises a typed `AuthError` on 401 so `main()` can trigger refresh+retry. Other HTTP/network errors raise `UsageFetchError`.

**Files:**
- Modify: `bin/claude-usage`
- Modify: `tests/test_claude_usage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_usage.py`:

```python
import io
import urllib.error
from unittest.mock import patch, MagicMock


class FetchUsageTest(unittest.TestCase):
    def _mock_response(self, body_dict):
        resp = MagicMock()
        resp.read.return_value = json.dumps(body_dict).encode("utf-8")
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: None
        return resp

    def test_returns_parsed_json(self):
        with patch("claude_usage.urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_response({"five_hour": {"utilization": 7.0}})
            result = claude_usage.fetch_usage("tok-abc")
            self.assertEqual(result["five_hour"]["utilization"], 7.0)

    def test_sends_bearer_and_beta_header(self):
        with patch("claude_usage.urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_response({})
            claude_usage.fetch_usage("tok-abc")
            req = mock_open.call_args[0][0]
            self.assertEqual(req.get_header("Authorization"), "Bearer tok-abc")
            self.assertEqual(req.get_header("Anthropic-beta"), "oauth-2025-04-20")

    def test_401_raises_auth_error(self):
        err = urllib.error.HTTPError(
            url="x", code=401, msg="Unauthorized",
            hdrs=None, fp=io.BytesIO(b"unauthorized"),
        )
        with patch("claude_usage.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(claude_usage.AuthError):
                claude_usage.fetch_usage("tok-abc")

    def test_500_raises_fetch_error(self):
        err = urllib.error.HTTPError(
            url="x", code=500, msg="Server",
            hdrs=None, fp=io.BytesIO(b"boom"),
        )
        with patch("claude_usage.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(claude_usage.UsageFetchError):
                claude_usage.fetch_usage("tok-abc")

    def test_url_error_raises_fetch_error(self):
        with patch(
            "claude_usage.urllib.request.urlopen",
            side_effect=urllib.error.URLError("no dns"),
        ):
            with self.assertRaises(claude_usage.UsageFetchError):
                claude_usage.fetch_usage("tok-abc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: 5 failures referencing missing `fetch_usage`, `AuthError`, `UsageFetchError`.

- [ ] **Step 3: Implement `fetch_usage` and the two error classes**

Append to `bin/claude-usage`:

```python
import urllib.request
import urllib.error

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"


class AuthError(Exception):
    """Raised on 401 from the usage endpoint (caller may retry after refresh)."""


class UsageFetchError(Exception):
    """Raised on any other HTTP or network error from the usage endpoint."""


def fetch_usage(access_token):
    """GET the usage endpoint and return the parsed JSON body."""
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": BETA_HEADER,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthError(f"401 Unauthorized: {e.read().decode('utf-8', 'replace')}") from e
        raise UsageFetchError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise UsageFetchError(f"Network error: {e.reason}") from e
    return json.loads(body)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: 14 OK.

- [ ] **Step 5: Commit**

```bash
git add bin/claude-usage tests/test_claude_usage.py
git commit -m "feat: fetch_usage hits /api/oauth/usage with bearer + beta header"
```

---

## Task 5: Research — Extract OAuth client_id and Confirm Refresh URL

This task does not write product code; it pins down two open items from the spec so Task 6 has correct constants. Document the findings in the plan body of Task 6 (or as comments in the script).

**Files:** none (research output goes into Task 6).

- [ ] **Step 1: Find the Claude Code binary path**

Run: `readlink -f $(which claude)` and chase any shell shim. The real binary is typically at `~/.local/share/claude/versions/<version>` and is an ELF executable.

- [ ] **Step 2: Search for the OAuth client_id**

Run:
```bash
strings ~/.local/share/claude/versions/<version> | grep -E 'client_id|claude-cli|9d1c2[0-9a-f]+|cli\.anthropic' | sort -u | head -40
```

Look for a string of the form `client_id=...` or a stable UUID-like constant near `oauth/token`, `grant_type`, or `refresh_token`. Also try:

```bash
strings ~/.local/share/claude/versions/<version> | grep -B2 -A2 'grant_type' | head -60
```

- [ ] **Step 3: Confirm the refresh URL**

Run:
```bash
strings ~/.local/share/claude/versions/<version> | grep -oE 'https://[a-zA-Z0-9./_-]*oauth[a-zA-Z0-9./_-]*' | sort -u
```

The candidate from design-time investigation was `https://platform.claude.com/v1/oauth/token`. Confirm that this exact URL appears in the binary, and note any sibling URLs (e.g. there may be a separate `console.anthropic.com` path).

- [ ] **Step 4: Validate by exercising the flow manually (optional but recommended)**

With your real refresh token (do NOT commit any of this output):

```bash
REFRESH=$(jq -r '.claudeAiOauth.refreshToken' ~/.claude/.credentials.json)
CLIENT_ID="<value from Step 2>"
curl -sS -X POST https://platform.claude.com/v1/oauth/token \
  -H 'Content-Type: application/json' \
  -d "{\"grant_type\":\"refresh_token\",\"refresh_token\":\"$REFRESH\",\"client_id\":\"$CLIENT_ID\"}" \
  | jq 'keys'
```

A successful response should include `access_token`, `refresh_token` (rotated), and either `expires_at` or `expires_in`. Note the exact field names — they drive Task 6's `refresh()` implementation.

If the call fails with 400/401, try `application/x-www-form-urlencoded` body encoding instead, and inspect the binary for the Content-Type used by the Claude Code refresh path.

- [ ] **Step 5: Record findings**

Write the discovered `CLIENT_ID`, `REFRESH_URL`, and the response field names into a temporary scratch file (or into the comments of the in-progress `bin/claude-usage`). They feed directly into Task 6.

No commit at this step — research only.

---

## Task 6: `refresh()` with Atomic Credentials Write

Refreshes the access token and writes the updated credentials back to `~/.claude/.credentials.json`. The write is atomic: write to a temp file in the same directory, then `os.replace()`. Preserve `0600` permissions.

**Files:**
- Modify: `bin/claude-usage`
- Modify: `tests/test_claude_usage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_usage.py`:

```python
import os
import stat


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".credentials.json"
        self.path.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": "old-access",
                "refreshToken": "old-refresh",
                "expiresAt": 1,
                "scopes": ["user:inference"],
                "subscriptionType": "max",
            }
        }))
        os.chmod(self.path, 0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def _mock_response(self, body):
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode("utf-8")
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: None
        return resp

    def test_writes_new_tokens_to_file(self):
        new_body = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        with patch("claude_usage.urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_response(new_body)
            updated = claude_usage.refresh(self.path)
        self.assertEqual(updated["accessToken"], "new-access")
        on_disk = json.loads(self.path.read_text())["claudeAiOauth"]
        self.assertEqual(on_disk["accessToken"], "new-access")
        self.assertEqual(on_disk["refreshToken"], "new-refresh")

    def test_preserves_0600_permissions(self):
        new_body = {"access_token": "a", "refresh_token": "r", "expires_in": 60}
        with patch("claude_usage.urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._mock_response(new_body)
            claude_usage.refresh(self.path)
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_refresh_failure_raises(self):
        err = urllib.error.HTTPError(
            url="x", code=400, msg="Bad",
            hdrs=None, fp=io.BytesIO(b'{"error":"invalid_grant"}'),
        )
        with patch("claude_usage.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(claude_usage.RefreshError):
                claude_usage.refresh(self.path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: 3 failures referencing missing `refresh`, `RefreshError`.

- [ ] **Step 3: Implement `refresh` in `bin/claude-usage`**

Use the `CLIENT_ID` and `REFRESH_URL` discovered in Task 5. The implementation below assumes the response carries `access_token`, `refresh_token`, and `expires_in` (seconds). If Task 5 found `expires_at` (ms epoch) instead, adapt the `expires_at_ms` calculation accordingly.

Append to `bin/claude-usage`:

```python
import os
import stat
import tempfile

# Filled in from Task 5 research:
OAUTH_CLIENT_ID = "<set from Task 5>"
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"


class RefreshError(Exception):
    """Raised when the refresh-token exchange fails."""


def refresh(path=DEFAULT_CREDENTIALS_PATH):
    """Refresh the access token and atomically rewrite the credentials file.

    Returns the updated claudeAiOauth dict.
    """
    path = Path(path)
    raw = json.loads(path.read_text())
    creds = raw["claudeAiOauth"]
    refresh_token = creds["refreshToken"]

    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode("utf-8")
    req = urllib.request.Request(
        REFRESH_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RefreshError(
            f"Refresh failed: HTTP {e.code} {e.reason}: "
            f"{e.read().decode('utf-8', 'replace')}"
        ) from e
    except urllib.error.URLError as e:
        raise RefreshError(f"Refresh failed: network: {e.reason}") from e

    creds["accessToken"] = payload["access_token"]
    creds["refreshToken"] = payload.get("refresh_token", refresh_token)
    if "expires_at" in payload:
        creds["expiresAt"] = int(payload["expires_at"])
    else:
        creds["expiresAt"] = int((time.time() + int(payload["expires_in"])) * 1000)
    raw["claudeAiOauth"] = creds

    _atomic_write(path, json.dumps(raw, indent=2))
    return creds


def _atomic_write(path, contents):
    """Write `contents` to `path` atomically, preserving permissions."""
    path = Path(path)
    try:
        existing_mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        existing_mode = 0o600
    fd, tmp = tempfile.mkstemp(prefix=".credentials.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(contents)
        os.chmod(tmp, existing_mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: 17 OK.

- [ ] **Step 5: Commit**

```bash
git add bin/claude-usage tests/test_claude_usage.py
git commit -m "feat: refresh access token with atomic credentials write"
```

---

## Task 7: `main()` Orchestration

Wire up `load_credentials → (maybe refresh) → fetch_usage → print`. On 401 from `fetch_usage`, refresh exactly once and retry. On any failure, write a clear message to stderr and exit with the spec's exit code.

**Files:**
- Modify: `bin/claude-usage`
- Modify: `tests/test_claude_usage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_usage.py`:

```python
import sys


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".credentials.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_creds(self, expires_at_ms):
        self.path.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": "tok",
                "refreshToken": "ref",
                "expiresAt": expires_at_ms,
            }
        }))

    def _resp(self, body):
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode("utf-8")
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: None
        return resp

    def test_happy_path_prints_pretty_json(self):
        self._write_creds(int(time.time() * 1000) + 3_600_000)
        usage = {"five_hour": {"utilization": 7.0}}
        with patch("claude_usage.urllib.request.urlopen") as mock_open, \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            mock_open.return_value = self._resp(usage)
            rc = claude_usage.main(["--credentials", str(self.path)])
        self.assertEqual(rc, 0)
        printed = json.loads(out.getvalue())
        self.assertEqual(printed, usage)
        # Pretty-printed: contains a newline + 2-space indent
        self.assertIn('\n  "five_hour"', out.getvalue())

    def test_missing_credentials_exits_2(self):
        with patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = claude_usage.main(["--credentials", str(self.path)])
        self.assertEqual(rc, 2)
        self.assertIn("authenticate", err.getvalue().lower())

    def test_401_triggers_refresh_and_retry(self):
        self._write_creds(int(time.time() * 1000) + 3_600_000)
        usage = {"seven_day": {"utilization": 1.0}}
        responses = [
            urllib.error.HTTPError(url="x", code=401, msg="u", hdrs=None,
                                    fp=io.BytesIO(b"")),
            self._resp({"access_token": "new", "refresh_token": "new-r",
                        "expires_in": 60}),
            self._resp(usage),
        ]
        def side_effect(req, *a, **kw):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with patch("claude_usage.urllib.request.urlopen", side_effect=side_effect), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = claude_usage.main(["--credentials", str(self.path)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), usage)

    def test_401_after_refresh_exits_5(self):
        self._write_creds(int(time.time() * 1000) + 3_600_000)
        responses = [
            urllib.error.HTTPError(url="x", code=401, msg="u", hdrs=None,
                                    fp=io.BytesIO(b"")),
            self._resp({"access_token": "new", "refresh_token": "new-r",
                        "expires_in": 60}),
            urllib.error.HTTPError(url="x", code=401, msg="u", hdrs=None,
                                    fp=io.BytesIO(b"")),
        ]
        def side_effect(req, *a, **kw):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with patch("claude_usage.urllib.request.urlopen", side_effect=side_effect), \
             patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = claude_usage.main(["--credentials", str(self.path)])
        self.assertEqual(rc, 5)

    def test_expired_token_refreshes_proactively(self):
        self._write_creds(int(time.time() * 1000) - 3_600_000)  # expired
        usage = {"five_hour": {"utilization": 0.0}}
        responses = [
            self._resp({"access_token": "new", "refresh_token": "new-r",
                        "expires_in": 60}),
            self._resp(usage),
        ]
        with patch("claude_usage.urllib.request.urlopen",
                   side_effect=responses), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = claude_usage.main(["--credentials", str(self.path)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), usage)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `make test`
Expected: 5 failures referencing missing `main`.

- [ ] **Step 3: Implement `main`**

Append to `bin/claude-usage`:

```python
import argparse
import sys

EXIT_OK = 0
EXIT_NO_CREDS = 2
EXIT_REFRESH_FAILED = 3
EXIT_NETWORK = 4
EXIT_AUTH_AFTER_REFRESH = 5


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="claude-usage",
        description="Print Claude Max subscription usage as pretty JSON.",
    )
    parser.add_argument(
        "--credentials",
        default=str(DEFAULT_CREDENTIALS_PATH),
        help="Path to the Claude Code credentials JSON file.",
    )
    args = parser.parse_args(argv)
    creds_path = Path(args.credentials)

    try:
        creds = load_credentials(creds_path)
    except CredentialsError as e:
        print(str(e), file=sys.stderr)
        return EXIT_NO_CREDS

    if is_expired(creds):
        try:
            creds = refresh(creds_path)
        except RefreshError as e:
            print(f"Token refresh failed. Re-auth via `claude /login`.\n{e}",
                  file=sys.stderr)
            return EXIT_REFRESH_FAILED

    try:
        data = fetch_usage(creds["accessToken"])
    except AuthError:
        try:
            creds = refresh(creds_path)
        except RefreshError as e:
            print(f"Token refresh failed. Re-auth via `claude /login`.\n{e}",
                  file=sys.stderr)
            return EXIT_REFRESH_FAILED
        try:
            data = fetch_usage(creds["accessToken"])
        except AuthError as e:
            print(f"Authentication failed even after refresh. Re-auth.\n{e}",
                  file=sys.stderr)
            return EXIT_AUTH_AFTER_REFRESH
        except UsageFetchError as e:
            print(str(e), file=sys.stderr)
            return EXIT_NETWORK
    except UsageFetchError as e:
        print(str(e), file=sys.stderr)
        return EXIT_NETWORK

    print(json.dumps(data, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make test`
Expected: 22 OK.

- [ ] **Step 5: Commit**

```bash
git add bin/claude-usage tests/test_claude_usage.py
git commit -m "feat: main orchestration with refresh-on-401 retry"
```

---

## Task 8: Manual End-to-End Verification

Run the tool against the real account and compare to a direct `curl` of the endpoint.

**Files:** none.

- [ ] **Step 1: Run the tool**

```bash
./bin/claude-usage | tee /tmp/claude-usage.json
```

Expected: pretty-printed JSON with at least the keys `five_hour`, `seven_day`, `extra_usage`. Exit code 0.

- [ ] **Step 2: Compare against a direct curl**

```bash
TOKEN=$(jq -r '.claudeAiOauth.accessToken' ~/.claude/.credentials.json)
curl -sS -H "Authorization: Bearer $TOKEN" \
     -H "anthropic-beta: oauth-2025-04-20" \
     https://api.anthropic.com/api/oauth/usage \
  | jq . > /tmp/curl-usage.json
diff /tmp/curl-usage.json /tmp/claude-usage.json
```

Expected: empty diff (modulo any time-sensitive fields like `resets_at` if the windows roll between calls).

- [ ] **Step 3: Force expiry and verify refresh path**

Make a backup, then edit `expiresAt` in `~/.claude/.credentials.json` to a value in the past (e.g. `1`):

```bash
cp ~/.claude/.credentials.json ~/.claude/.credentials.json.bak
jq '.claudeAiOauth.expiresAt = 1' ~/.claude/.credentials.json > /tmp/c.json
mv /tmp/c.json ~/.claude/.credentials.json
chmod 600 ~/.claude/.credentials.json
./bin/claude-usage > /dev/null
jq '.claudeAiOauth.expiresAt' ~/.claude/.credentials.json
```

Expected: a 13-digit value far in the future (refresh ran). Exit code 0.

If anything goes wrong, restore from backup:
```bash
mv ~/.claude/.credentials.json.bak ~/.claude/.credentials.json
```

- [ ] **Step 4: No commit**

This task produces no artifact other than confidence. If the manual run reveals a bug, return to the relevant task and add a regression test before fixing.

---

## Task 9: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# claude-usage-watcher

A one-shot CLI that prints your **Claude Max subscription** usage as
pretty-printed JSON. Reports the 5-hour session window, the 7-day
weekly window, and per-model breakdowns.

This is for Max subscribers. It does not monitor pay-per-use API spend.

## Install

```bash
make install
# Installs to ~/local/bin/claude-usage by default.
# Override with: make install INSTALL_DIR=/usr/local/bin
```

The script depends only on Python 3 and the standard library.

## Use

```bash
claude-usage
```

Output is the JSON body of `https://api.anthropic.com/api/oauth/usage`,
verbatim, indented with two spaces. Pipe it into `jq`, parse it, do
whatever you want with it.

```bash
claude-usage | jq '.five_hour.utilization'
```

Authentication uses the OAuth credentials Claude Code already stores at
`~/.claude/.credentials.json`. If the access token is expired, the tool
refreshes it (and writes the rotated tokens back to the same file).

## Caveats

- The endpoint is **undocumented** by Anthropic. The schema, the URL,
  and the `anthropic-beta: oauth-2025-04-20` header are best-effort and
  may change without notice.
- The tool reads and rewrites `~/.claude/.credentials.json`. The atomic
  write minimizes the risk of corruption during a concurrent Claude Code
  refresh, but is not zero-risk.
- The OAuth client_id and refresh URL are extracted from the Claude Code
  binary. If Claude Code's auth scheme changes, this tool will break
  until those constants are re-derived.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | Success |
| 2    | Credentials missing or malformed |
| 3    | Token refresh failed |
| 4    | Network/HTTP error from the usage endpoint |
| 5    | Authentication failed even after refresh |

## Run the tests

```bash
make test
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install, usage, caveats, exit codes"
```

---

## Task 10: Final Polish — `make test` Clean Run

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `make test`
Expected: all tests pass, no warnings.

- [ ] **Step 2: Run the tool one more time**

Run: `./bin/claude-usage | jq '.five_hour, .seven_day'`
Expected: two non-null objects with `utilization` and `resets_at` keys.

- [ ] **Step 3: Verify install target**

```bash
make install INSTALL_DIR=/tmp/claude-usage-test
/tmp/claude-usage-test/claude-usage | head -3
rm -rf /tmp/claude-usage-test
```

Expected: the temp install directory is created, the binary is present and executable, and running it prints JSON.

- [ ] **Step 4: No commit**

If everything is clean, the work is done. If any of these steps fail, return to the failing task and add a regression test.

---

## Self-Review Checklist (run after the plan is written)

**Spec coverage:**
- Purpose / sample response → README + Task 4 ✓
- `load_credentials` → Task 2 ✓
- `is_expired` → Task 3 ✓
- `fetch_usage` → Task 4 ✓
- `refresh` (atomic write, 0600 perms) → Task 6 ✓
- `main` orchestration with refresh-on-401 → Task 7 ✓
- Error handling + exit codes → Task 7 + README ✓
- Stdout/stderr separation → Task 7 (`print(..., file=sys.stderr)`) ✓
- Unit tests (mocked urlopen, atomic write, 401 path) → Tasks 2, 3, 4, 6, 7 ✓
- Manual verification → Task 8 ✓
- Repo layout (`bin/claude-usage`, `tests/`, `docs/`) → Task 1 ✓
- README with caveats → Task 9 ✓
- Open items: client_id and refresh URL → Task 5 ✓

**Placeholders:** `OAUTH_CLIENT_ID = "<set from Task 5>"` is the only placeholder; it's gated by a research task that produces the value before Task 6 runs. No "TBD"/"TODO"/"add appropriate handling" anywhere.

**Type/name consistency:** `CredentialsError`, `AuthError`, `UsageFetchError`, `RefreshError`, `load_credentials`, `is_expired`, `fetch_usage`, `refresh`, `main` — names match across tasks. Exit-code constants (`EXIT_OK`, `EXIT_NO_CREDS`, …) defined in Task 7 and referenced consistently.
