"""Test configuration: load bin/claude-usage as an importable module.

The CLI script lives at bin/claude-usage with no .py extension (it's the
artifact that ships to $PATH). To unit-test its functions, we use
importlib to load it under the module name `claude_usage`.
"""
import importlib.util
import sys
from pathlib import Path
from importlib.machinery import SourceFileLoader

# Get the repo root by finding where this conftest.py is located.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO_ROOT / "bin" / "claude-usage"

_loader = SourceFileLoader("claude_usage", str(_SCRIPT_PATH))
_spec = importlib.util.spec_from_loader("claude_usage", _loader)
claude_usage = importlib.util.module_from_spec(_spec)
sys.modules["claude_usage"] = claude_usage
_spec.loader.exec_module(claude_usage)
