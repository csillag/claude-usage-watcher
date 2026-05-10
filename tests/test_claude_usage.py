import unittest
from tests.conftest import claude_usage


class SmokeTest(unittest.TestCase):
    def test_module_loads(self):
        self.assertTrue(hasattr(claude_usage, "__doc__"))


if __name__ == "__main__":
    unittest.main()
