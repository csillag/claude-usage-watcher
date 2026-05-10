import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch, MagicMock
from tests.conftest import claude_usage


class SmokeTest(unittest.TestCase):
    def test_module_loads(self):
        self.assertTrue(hasattr(claude_usage, "__doc__"))


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

    def test_missing_expiry_treated_as_expired(self):
        self.assertTrue(claude_usage.is_expired({}))


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


class FormatHumanTest(unittest.TestCase):
    def test_renders_full_response(self):
        # now = 2026-05-09T22:00:00Z
        # five_hour reset 5h later -> "resets in 5h 0m"
        # seven_day reset 2d 2h later -> "resets in 2d 2h"
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        data = {
            "five_hour": {"utilization": 10.0, "resets_at": "2026-05-10T03:00:00+00:00"},
            "seven_day": {"utilization": 48.0, "resets_at": "2026-05-12T00:00:00+00:00"},
            "extra_usage": {"is_enabled": False, "monthly_limit": None,
                            "used_credits": None, "utilization": None,
                            "currency": None},
        }
        expected = (
            "5-hour session   [██░░░░░░░░░░░░░░░░░░]  10%   resets in 5h 0m\n"
            "7-day weekly     [██████████░░░░░░░░░░]  48%   resets in 2d 2h\n"
            "Extra credits    disabled"
        )
        self.assertEqual(claude_usage.format_human(data, now=now), expected)

    def test_extra_usage_enabled(self):
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        data = {
            "five_hour": None,
            "seven_day": None,
            "seven_day_sonnet": None,
            "seven_day_opus": None,
            "extra_usage": {
                "is_enabled": True,
                "utilization": 30.0,
                "monthly_limit": 100,
                "used_credits": 30,
                "currency": "USD",
            },
        }
        out = claude_usage.format_human(data, now=now)
        # Last line should be the extras line
        last_line = out.splitlines()[-1]
        self.assertEqual(last_line, "Extra credits    30% of $100")

    def test_null_entry_renders_em_dash_no_usage(self):
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        line = claude_usage._render_row("Some label", None, now)
        self.assertIn("—", line)        # em-dash bar
        self.assertIn("no usage", line)
        self.assertNotIn("%", line)

    def test_reset_in_minutes_format(self):
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        # 45 minutes from now
        resets_at = (now + timedelta(minutes=45)).isoformat()
        result = claude_usage._humanize_reset(resets_at, now)
        self.assertEqual(result, "resets in 45m")

    def test_reset_past_renders_reset(self):
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        # 1 second in the past
        resets_at = (now - timedelta(seconds=1)).isoformat()
        result = claude_usage._humanize_reset(resets_at, now)
        self.assertEqual(result, "reset")

    def test_reset_in_days_format(self):
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        # 2 days, 19 hours from now
        resets_at = (now + timedelta(days=2, hours=19, minutes=30)).isoformat()
        result = claude_usage._humanize_reset(resets_at, now)
        self.assertEqual(result, "resets in 2d 19h")


class FormatPlanNameTest(unittest.TestCase):
    def test_max_20x(self):
        self.assertEqual(claude_usage._format_plan_name("default_claude_max_20x"), "Claude Max 20x")

    def test_max_5x(self):
        self.assertEqual(claude_usage._format_plan_name("default_claude_max_5x"), "Claude Max 5x")

    def test_pro(self):
        self.assertEqual(claude_usage._format_plan_name("default_claude_pro"), "Claude Pro")

    def test_unknown_tier_passes_through(self):
        self.assertEqual(claude_usage._format_plan_name("weird_unknown_tier"), "weird unknown tier")


class FormatPlanHeaderTest(unittest.TestCase):
    def test_active(self):
        profile = {"organization": {
            "rate_limit_tier": "default_claude_max_20x",
            "subscription_status": "active",
            "subscription_created_at": "2026-03-01T01:20:53.708212Z",
        }}
        self.assertEqual(
            claude_usage._format_plan_header(profile),
            "Plan: Claude Max 20x  (active since 2026-03-01)",
        )

    def test_inactive(self):
        profile = {"organization": {
            "rate_limit_tier": "default_claude_pro",
            "subscription_status": "cancelled",
            "subscription_created_at": "2026-03-01T01:20:53.708212Z",
        }}
        self.assertEqual(
            claude_usage._format_plan_header(profile),
            "Plan: Claude Pro  (status: cancelled, since 2026-03-01)",
        )

    def test_missing_keys_returns_unknown(self):
        self.assertEqual(claude_usage._format_plan_header({}), "Plan: unknown")


class FormatHumanWithProfileTest(unittest.TestCase):
    def test_prepends_header_and_blank_line(self):
        now = datetime(2026, 5, 9, 22, 0, 0, tzinfo=timezone.utc)
        data = {
            "five_hour": {"utilization": 10.0, "resets_at": "2026-05-10T03:00:00+00:00"},
            "seven_day": {"utilization": 48.0, "resets_at": "2026-05-12T00:00:00+00:00"},
            "seven_day_sonnet": None,
            "seven_day_opus": None,
            "extra_usage": {"is_enabled": False},
        }
        profile = {"organization": {
            "rate_limit_tier": "default_claude_max_20x",
            "subscription_status": "active",
            "subscription_created_at": "2026-03-01T01:20:53.708212Z",
        }}
        out = claude_usage.format_human(data, profile=profile, now=now)
        lines = out.splitlines()
        self.assertEqual(lines[0], "Plan: Claude Max 20x  (active since 2026-03-01)")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "5-hour session   [██░░░░░░░░░░░░░░░░░░]  10%   resets in 5h 0m")


class FetchProfileTest(unittest.TestCase):
    def _resp(self, body):
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode("utf-8")
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: None
        return resp

    def test_returns_parsed_json(self):
        with patch("claude_usage.urllib.request.urlopen") as mock_open:
            mock_open.return_value = self._resp({"account": {"has_claude_max": True}})
            result = claude_usage.fetch_profile("tok-abc")
            self.assertTrue(result["account"]["has_claude_max"])

    def test_401_raises_auth_error(self):
        err = urllib.error.HTTPError(
            url="x", code=401, msg="Unauthorized",
            hdrs=None, fp=io.BytesIO(b"u"),
        )
        with patch("claude_usage.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(claude_usage.AuthError):
                claude_usage.fetch_profile("tok-abc")


class MainHumanProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".credentials.json"
        self.path.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": "tok",
                "refreshToken": "ref",
                "expiresAt": int(time.time() * 1000) + 3_600_000,
            }
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _resp(self, body):
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode("utf-8")
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: None
        return resp

    def test_human_includes_plan_header(self):
        usage = {
            "five_hour": {"utilization": 10.0, "resets_at": "2026-05-10T03:00:00+00:00"},
            "seven_day": {"utilization": 48.0, "resets_at": "2026-05-12T00:00:00+00:00"},
            "seven_day_sonnet": None,
            "seven_day_opus": None,
            "extra_usage": {"is_enabled": False},
        }
        profile = {"organization": {
            "rate_limit_tier": "default_claude_max_20x",
            "subscription_status": "active",
            "subscription_created_at": "2026-03-01T01:20:53.708212Z",
        }}
        # main calls fetch_usage then fetch_profile (or vice versa — check the impl).
        # Order responses to match. If your impl fetches usage first:
        responses = [self._resp(usage), self._resp(profile)]
        with patch("claude_usage.urllib.request.urlopen", side_effect=responses), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = claude_usage.main(["--human", "--credentials", str(self.path)])
        self.assertEqual(rc, 0)
        self.assertTrue(out.getvalue().startswith("Plan: "))


class MainHumanFlagTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".credentials.json"
        self.path.write_text(json.dumps({
            "claudeAiOauth": {
                "accessToken": "tok",
                "refreshToken": "ref",
                "expiresAt": int(time.time() * 1000) + 3_600_000,
            }
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _resp(self, body):
        resp = MagicMock()
        resp.read.return_value = json.dumps(body).encode("utf-8")
        resp.__enter__ = lambda self: self
        resp.__exit__ = lambda self, *a: None
        return resp

    def test_human_flag_renders_text_not_json(self):
        usage = {
            "five_hour": {"utilization": 0.0, "resets_at": None},
            "seven_day": {"utilization": 0.0, "resets_at": None},
            "seven_day_sonnet": None,
            "seven_day_opus": None,
            "extra_usage": {"is_enabled": False},
        }
        profile = {"organization": {
            "rate_limit_tier": "default_claude_max_20x",
            "subscription_status": "active",
            "subscription_created_at": "2026-03-01T01:20:53.708212Z",
        }}
        responses = [self._resp(usage), self._resp(profile)]
        with patch("claude_usage.urllib.request.urlopen", side_effect=responses), \
             patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = claude_usage.main(["--credentials", str(self.path), "--human"])
        self.assertEqual(rc, 0)
        # With profile header prepended, output starts with "Plan: "
        # and the usage rows still appear after a blank line.
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith("Plan: "))
        self.assertEqual(lines[1], "")
        self.assertTrue(lines[2].startswith("5-hour session"))


if __name__ == "__main__":
    unittest.main()
