import json
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
