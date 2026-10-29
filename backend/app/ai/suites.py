"""Model suite definitions + per-function resolver.

Three pre-defined suites (Free/Testing, Production, Extreme) with latency-aware
model assignments, plus a Custom mode where the user picks per-function models.
"""
from typing import Dict, List, Optional, Any
from app.config import get_settings

settings = get_settings()

SUITE_NAMES = ["free", "production", "production_v2", "extreme", "custom"]

# Suite definitions: per-function model IDs
SUITES: Dict[str, Dict[str, str]] = {
    "free": {
        "technical": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "fundamental": "google/gemma-4-31b-it:free",
        "sentiment": "nvidia/nemotron-3.5-lightning:free",
        "macro": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "lead": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "verifier": "nvidia/nemotron-3-ultra-550b-a55b:free",
    },
    "production": {
        "technical": "deepseek/deepseek-v4-flash",
        "fundamental": "google/gemini-2.5-flash",
        "sentiment": "meta-llama/llama-3.3-70b-instruct",
        "macro": "openai/gpt-4o-mini",
        "lead": "deepseek/deepseek-v4-flash",
        "verifier": "deepseek/deepseek-r1",
    },
    # production_v2 — IDs verified live 2026-10-29 via model_health_probe.
    # Hot-path roles (technical/sentiment/lead) deliberately use NON-reasoning
    # models: reasoning models burn max_tokens on chain-of-thought and return
    # empty content, which silently parses to HOLD(0.0).
    # OpenAI models are avoided entirely — this account's provider returns
    # 400 for all chat-completions calls (Responses-API-only backend).
    "production_v2": {
        "technical": "qwen/qwen3-next-80b-a3b-instruct",
        "fundamental": "google/gemini-2.5-flash",
        "sentiment": "meta-llama/llama-3.3-70b-instruct",
        "macro": "qwen/qwen3-next-80b-a3b-instruct",
        "lead": "moonshotai/kimi-k2-0905",
        "verifier": "deepseek/deepseek-r1-0528",
    },
    "extreme": {
        "technical": "openai/gpt-4o",  # or best available
        "fundamental": "google/gemini-2.5-pro",
        "sentiment": "anthropic/claude-sonnet-4.5",
        "macro": "openai/o3",
        "lead": "anthropic/claude-opus-4.1",
        "verifier": "google/gemini-2.5-pro",
    },
}

# Latency tier annotation: which functions need fast models for the hot path
HOT_PATH_DOMAINS = {"technical", "sentiment", "lead"}
OFF_PATH_DOMAINS = {"fundamental", "macro", "verifier"}


def resolve_models(
    suite: str,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Return the per-function model map for a given suite.

    Named suites (free, production, extreme) are returned exactly as defined.
    Per-model overrides are ONLY applied when suite == "custom".
    This ensures the frontend suite dropdown works correctly.
    """
    if suite == "custom":
        env = settings
        resolved = {
            "technical": overrides.get("technical") if overrides else env.MODEL_TECHNICAL,
            "fundamental": overrides.get("fundamental") if overrides else env.MODEL_FUNDAMENTAL,
            "sentiment": overrides.get("sentiment") if overrides else env.MODEL_SENTIMENT,
            "macro": overrides.get("macro") if overrides else env.MODEL_MACRO,
            "lead": overrides.get("lead") if overrides else env.MODEL_LEAD,
            "verifier": overrides.get("verifier") if overrides else env.MODEL_VERIFIER,
        }
        # Ensure no None values: fall back to production defaults for custom
        defaults = SUITES["production"]
        return {k: (v or defaults[k]) for k, v in resolved.items()}

    if suite in SUITES:
        # Named suites are used verbatim; overrides are ignored.
        return dict(SUITES[suite])

    # Unknown suite — fall back to production (safer than free for live trading)
    return dict(SUITES["production"])


def suite_info() -> List[Dict[str, Any]]:
    """Return metadata about each suite for the frontend dropdown."""
    from typing import Any
    out = []
    for name, models in SUITES.items():
        out.append({
            "id": name,
            "label": name.replace("_", " ").title(),
            "models": models,
            "hot_path_models": {k: v for k, v in models.items() if k in HOT_PATH_DOMAINS},
            "off_path_models": {k: v for k, v in models.items() if k in OFF_PATH_DOMAINS},
        })
    out.append({
        "id": "custom",
        "label": "Custom",
        "models": {},
        "hot_path_models": {},
        "off_path_models": {},
    })
    return out
