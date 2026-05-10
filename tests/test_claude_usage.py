import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
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


if __name__ == "__main__":
    unittest.main()
