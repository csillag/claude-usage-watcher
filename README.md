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

````bash
claude-usage | jq '.five_hour.utilization'
````

### Human-readable mode

For an at-a-glance text report with ASCII bars and humanized reset
times instead of JSON, pass `--human`:

```
$ claude-usage --human
Plan: Claude Max 20x  (active since 2026-03-01)

5-hour session   [███░░░░░░░░░░░░░░░░░]  13%   resets in 45m
7-day weekly     [██████████░░░░░░░░░░]  49%   resets in 2d 21h
  Sonnet (7d)    [██░░░░░░░░░░░░░░░░░░]   9%   resets in 2d 21h
  Opus (7d)      —                             no usage
Extra credits    disabled
```

Lines shown:

- `Plan: ...` — your subscription tier and status (only shown in
  `--human` mode; the JSON output is unchanged from the upstream
  endpoint).
- `5-hour session` — the rolling 5-hour quota for the current Claude
  Max session.
- `7-day weekly` — the rolling 7-day quota.
- `Sonnet (7d)` / `Opus (7d)` — per-model 7-day usage. A line shows
  `—` and `no usage` if you haven't used that model in the window.
- `Extra credits` — `disabled` if the account has no extra-credits
  plan, otherwise `<percent>% of $<monthly_limit>`.

The output is intended for terminals; if you need a stable, scriptable
representation, use the default JSON form.

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
