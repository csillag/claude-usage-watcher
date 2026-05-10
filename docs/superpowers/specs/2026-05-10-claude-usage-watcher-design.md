# claude-usage-watcher — Design

**Date:** 2026-05-10
**Status:** Approved

## Purpose

A one-shot CLI that prints the current Claude Max subscription usage as
pretty-printed JSON. Specifically, the data exposed by Anthropic's
undocumented `/api/oauth/usage` endpoint:

- 5-hour session window: utilization (%) and reset time
- 7-day weekly window: utilization (%) and reset time
- Per-model 7-day breakdowns (Opus, Sonnet, etc.)
- Extra-credits status

This is a Max-subscription monitoring tool. It does **not** monitor
pay-per-use API spend (that lives behind the Admin API and the Console).

## Non-Goals

- No daemon, TUI, dashboard, or notifications.
- No alerting at thresholds.
- No historical storage or trend tracking.
- No per-field selection or output reshaping. Output is the upstream JSON
  body verbatim, pretty-printed.
- No support for multiple accounts. The tool reads the single credentials
  file at `~/.claude/.credentials.json`.

## Endpoint Reference

**Usage endpoint** (verified live during design):

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <accessToken>
anthropic-beta: oauth-2025-04-20
```

Sample response shape (fields may evolve):

```json
{
  "five_hour":        {"utilization": 7.0,  "resets_at": "2026-05-10T03:10:00Z"},
  "seven_day":        {"utilization": 47.0, "resets_at": "2026-05-13T00:00:01Z"},
  "seven_day_opus":   null,
  "seven_day_sonnet": {"utilization": 9.0,  "resets_at": "2026-05-13T00:00:01Z"},
  "seven_day_omelette": {"utilization": 0.0, "resets_at": null},
  "extra_usage": {"is_enabled": false, "monthly_limit": null, ...}
}
```

**Refresh endpoint** (to be confirmed at implementation time by inspecting
the Claude Code binary; observed candidate host is
`https://platform.claude.com/v1/oauth/token`). Standard OAuth2 refresh
flow:

```
POST <refresh-endpoint>
Content-Type: application/json
{
  "grant_type":    "refresh_token",
  "refresh_token": "<refresh_token>",
  "client_id":     "<extracted from Claude Code binary>"
}
```

Both the exact refresh URL and the `client_id` value are open items for
the implementer; they are recoverable by `strings`-grepping the Claude
Code binary at `~/.local/share/claude/versions/<ver>` and tracing the
auth flow.

## Architecture

Single Python script, stdlib only. No third-party dependencies, no
virtualenv, no package metadata. The script is the artifact.

Distribution is plain: drop the executable script onto `$PATH` (e.g.
`~/local/bin/claude-usage`), `chmod +x`. The repository keeps the
canonical copy at `bin/claude-usage`.

Target: ~100 lines of code.

## Components

### `load_credentials() -> dict`
Reads `~/.claude/.credentials.json`. Returns the `claudeAiOauth` sub-object.
Raises a domain-specific error if the file is missing or malformed.

### `is_expired(creds: dict) -> bool`
Compares `creds["expiresAt"]` (epoch milliseconds — verified against a
live credentials file during design) to the current time. Adds a 60-second
skew margin to avoid firing a request right at the boundary.

### `refresh(creds: dict) -> dict`
POSTs to the refresh endpoint with the refresh token and the OAuth
client_id. On success:
1. Merges the new `accessToken`, `refreshToken`, and `expiresAt` into the
   loaded credentials.
2. Writes the updated credentials back atomically: write to a sibling
   temp file in the same directory, `os.replace()` onto the original.
   Preserve file permissions (0600).
3. Returns the updated dict.

On failure (4xx/5xx from refresh endpoint), raises a domain-specific
error so `main()` can exit cleanly.

### `fetch_usage(access_token: str) -> dict`
Issues the GET against `/api/oauth/usage` with Bearer auth and the beta
header. Returns parsed JSON. Distinguishes 401 (auth) from other errors
so the caller can trigger a refresh-and-retry.

### `main()`
Orchestration:
1. `creds = load_credentials()`
2. If `is_expired(creds)`: `creds = refresh(creds)`
3. Try `fetch_usage(creds["accessToken"])`.
4. On 401: refresh once and retry the fetch. If the retry also returns
   401, exit with a clear message.
5. On success: `print(json.dumps(data, indent=2, sort_keys=False))`.

## Data Flow

```
~/.claude/.credentials.json
        |
        v
   load_credentials
        |
        v
   [expired?] --yes--> refresh ---+
        |                          |
        no                         |
        v                          v
   fetch_usage <-------- (token saved back to creds file)
        |
   [HTTP 401?] --yes (once)--> refresh, retry fetch_usage
        |
   json.dumps(indent=2)
        |
        v
      stdout
```

## Error Handling

| Condition                          | Stderr message                                         | Exit code |
|------------------------------------|--------------------------------------------------------|-----------|
| Credentials file missing/unreadable| "No credentials. Run `claude` to authenticate first."  | 2         |
| Credentials file malformed         | "Credentials file at <path> is malformed: <detail>"    | 2         |
| Refresh fails (e.g. token revoked) | "Token refresh failed. Re-auth via `claude /login`."   | 3         |
| Network error (connection, DNS)    | Raw error text                                         | 4         |
| 401 after refresh                  | "Authentication failed even after refresh. Re-auth."   | 5         |
| Success                            | (none — JSON to stdout)                                | 0         |

All non-success messages go to **stderr**. Stdout receives only the
pretty-printed JSON, so the tool composes cleanly with pipes (`| jq`,
`| grep`, etc.).

## Testing

**Unit tests** (`tests/test_claude_usage.py`, stdlib `unittest`):
- `is_expired` boundary cases (expired, soon-to-expire within skew, fresh).
- `load_credentials` raises on missing file, on malformed JSON, on missing
  `claudeAiOauth` block.
- `refresh` writes the updated credentials atomically (verify by checking
  the file appears in one shot, not partially written).
- `fetch_usage` distinguishes 401 from other HTTP errors.
- `main` orchestration: mock `urllib.request.urlopen` to return canned
  responses; assert the refresh-on-401 retry path runs exactly once.

**Manual verification:**
- Run against a live account and compare the output to a direct `curl`
  call against the same endpoint. They should match modulo ordering.
- Force an expired token (edit `expiresAt` in the credentials file to
  the past) and confirm refresh-and-fetch succeeds and the file is
  rewritten with a fresh token.

**Out of scope:**
- No live-API integration tests in CI. CI has no credentials and the
  endpoint is undocumented; a fixture-based unit suite is sufficient.

## Repository Layout

```
claude-usage-watcher/
├── bin/
│   └── claude-usage           # the script (executable, shebang #!/usr/bin/env python3)
├── tests/
│   └── test_claude_usage.py
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-10-claude-usage-watcher-design.md   # this file
├── README.md                  # install + usage + caveats
└── .gitignore
```

## Caveats To Document In README

- The endpoint is **undocumented** by Anthropic. Schema may change
  without notice. Pinning the `anthropic-beta: oauth-2025-04-20` header
  is best-effort, not a contract.
- The tool reads and rewrites `~/.claude/.credentials.json`, the same
  file Claude Code uses. The atomic-write strategy minimizes the risk of
  corruption during a concurrent Claude Code refresh, but is not
  zero-risk. Heavy concurrent use is not a target.
- Auth uses an OAuth refresh-token flow scraped from the Claude Code
  binary. If Claude Code changes its auth scheme, this tool breaks until
  the refresh path is re-derived.

## Open Items For The Implementer

1. Confirm the exact refresh endpoint URL (host + path).
2. Extract the OAuth `client_id` constant from the Claude Code binary
   (`strings ~/.local/share/claude/versions/<ver> | grep -E 'client_id|claude-cli'`).
3. Decide whether to depend on the file permission bit being `0600`
   already, or to enforce it on every write.
