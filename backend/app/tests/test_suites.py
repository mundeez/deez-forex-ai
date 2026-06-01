"""Tests for model suite resolver."""
import pytest
from app.ai.suites import resolve_models, suite_info, SUITES


def test_free_suite_resolution():
    """Free suite should return the expected free model IDs."""
    models = resolve_models("free")
    assert models["technical"] == "openai/gpt-oss-120b:free"
    assert models["lead"] == "openai/gpt-oss-120b:free"
    assert models["verifier"] == "deepseek/deepseek-r1:free"


def test_production_suite_resolution():
    """Production suite should return affordable paid models."""
    models = resolve_models("production")
    assert "flash" in models["fundamental"]  # gemini-2.5-flash
    assert "deepseek-v4-flash" in models["technical"]


def test_extreme_suite_resolution():
    """Extreme suite should return top-tier models."""
    models = resolve_models("extreme")
    assert "opus" in models["lead"] or "gpt-4o" in models["technical"]


def test_custom_suite_with_overrides():
    """Custom suite should use overrides and fall back to env defaults."""
    models = resolve_models("custom", overrides={"technical": "my-custom-model"})
    assert models["technical"] == "my-custom-model"
    # Others should fall back to defaults
    assert models["lead"] is not None


def test_custom_suite_empty_overrides():
    """Custom suite with no overrides should not return None values."""
    models = resolve_models("custom")
    for k, v in models.items():
        assert v is not None and v != ""


def test_unknown_suite_fallback():
    """Unknown suite should fall back to free models."""
    models = resolve_models("nonexistent")
    assert models == SUITES["free"]


def test_suite_info_structure():
    """suite_info should return metadata for each suite."""
    info = suite_info()
    ids = [s["id"] for s in info]
    assert "free" in ids
    assert "production" in ids
    assert "extreme" in ids
    assert "custom" in ids
    for s in info:
        if s["id"] != "custom":
            assert "models" in s
            assert "hot_path_models" in s
            assert "off_path_models" in s
