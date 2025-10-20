import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "copilot_changelog_to_discord.py"
    spec = importlib.util.spec_from_file_location("copilot_changelog_to_discord", module_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # ensure module is visible during dataclass processing
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_is_copilot_tagged_by_tag_term():
    mod = _load_module()
    entry: dict[str, Any] = {
        "title": "Update",
        "tags": [{"term": "Copilot"}],
    }
    assert mod.is_copilot_tagged(entry) is True


def test_is_copilot_tagged_by_category():
    mod = _load_module()
    entry: dict[str, Any] = {
        "title": "Update",
        "category": "GitHub Copilot",
    }
    assert mod.is_copilot_tagged(entry) is True


def test_basic_summary_truncates():
    mod = _load_module()
    entry: dict[str, Any] = {
        "summary": "<p>" + ("x" * 1000) + "</p>",
    }
    s = mod.basic_summary(entry, max_len=100)
    assert len(s) <= 100


def test_summarize_entry_falls_back_to_basic_summary():
    mod = _load_module()
    mod.GITHUB_MODELS_TOKEN = None
    mod.OPENAI_API_KEY = None
    entry: dict[str, Any] = {
        "summary": "<p>Copilot improvements to code search.</p>",
    }
    summary = mod.summarize_entry(entry)
    assert "Copilot improvements to code search." in summary
