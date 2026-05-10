import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
