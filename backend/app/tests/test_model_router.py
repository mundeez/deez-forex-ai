"""Tests for the free-model round-robin router."""

import asyncio
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from app.ai.model_router import ModelRouter, parse_pool, DEFAULT_FREE_POOL, _RR_KEY, _COOLDOWN_PREFIX
from app.config import get_settings


async def _clear_router_redis():
    """Remove all router-related keys from Redis so tests are isolated."""
    settings = get_settings()
    try:
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        keys = []
        async for k in r.scan_iter(match=f"{_COOLDOWN_PREFIX}*"):
            keys.append(k)
        keys.append(_RR_KEY)
        if keys:
            await r.delete(*keys)
        await r.close()
    except Exception:
        pass


@pytest_asyncio.fixture(autouse=True)
async def clean_router_redis():
    await _clear_router_redis()
    yield
    await _clear_router_redis()


class TestParsePool:
    def test_empty_returns_default(self):
        assert parse_pool(None) == list(DEFAULT_FREE_POOL)
        assert parse_pool("") == list(DEFAULT_FREE_POOL)

    def test_comma_separated(self):
        raw = "a:free, b:free , c:free"
        assert parse_pool(raw) == ["a:free", "b:free", "c:free"]

    def test_newline_separated(self):
        raw = "a:free\nb:free\nc:free"
        assert parse_pool(raw) == ["a:free", "b:free", "c:free"]

    def test_mixed_delimiters(self):
        raw = "a:free, b:free\nc:free"
        assert parse_pool(raw) == ["a:free", "b:free", "c:free"]

    def test_whitespace_stripped(self):
        assert parse_pool("  a:free  ,   b:free  ") == ["a:free", "b:free"]


class TestModelRouterRotation:
    @pytest.mark.asyncio
    async def test_rotation_disabled_returns_primary_first(self):
        router = ModelRouter(
            free_pool=["a", "b", "c"],
            rotation_enabled=False,
        )
        candidates = await router.get_candidates(primary="b")
        assert candidates[0] == "b"
        assert "a" in candidates
        assert "c" in candidates

    @pytest.mark.asyncio
    async def test_rotation_disabled_no_primary(self):
        router = ModelRouter(
            free_pool=["a", "b", "c"],
            rotation_enabled=False,
        )
        candidates = await router.get_candidates()
        assert candidates == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_rotation_cycles_through_pool(self):
        router = ModelRouter(
            free_pool=["a", "b", "c"],
            rotation_enabled=True,
        )

        # Patch _next_offset to simulate deterministic rotation without Redis
        offsets = [0, 1, 2, 0]
        call_idx = 0

        async def mock_next_offset(n):
            nonlocal call_idx
            idx = offsets[call_idx % len(offsets)]
            call_idx += 1
            return idx

        router._next_offset = mock_next_offset  # type: ignore[method-assign]

        async def mock_cooled(models):
            return set()

        router._cooled_set = mock_cooled  # type: ignore[method-assign]

        first = await router.get_candidates()
        second = await router.get_candidates()
        third = await router.get_candidates()
        fourth = await router.get_candidates()

        assert first == ["a", "b", "c"]
        assert second == ["b", "c", "a"]
        assert third == ["c", "a", "b"]
        assert fourth == ["a", "b", "c"]  # cycle back

    @pytest.mark.asyncio
    async def test_cooldown_skips_model(self):
        router = ModelRouter(
            free_pool=["a", "b", "c"],
            cooldown_sec=300,
            rotation_enabled=True,
        )

        async def mock_cooled_set(models):
            return {"a"}

        router._cooled_set = mock_cooled_set  # type: ignore[method-assign]
        candidates = await router.get_candidates()
        # "a" should be at the end (last resort) because it's cooling down
        assert candidates[-1] == "a"
        assert candidates[0] != "a"

    @pytest.mark.asyncio
    async def test_paid_fallback_appended(self):
        router = ModelRouter(
            free_pool=["a", "b"],
            paid_fallback="paid-model",
            rotation_enabled=True,
        )

        async def mock_cooled(models):
            return set()

        router._cooled_set = mock_cooled  # type: ignore[method-assign]
        candidates = await router.get_candidates()
        assert "paid-model" in candidates
        # Paid fallback should come after fresh free models
        idx_paid = candidates.index("paid-model")
        assert idx_paid >= 1

    @pytest.mark.asyncio
    async def test_all_cooled_uses_paid_then_stale(self):
        router = ModelRouter(
            free_pool=["a", "b"],
            paid_fallback="paid-model",
            cooldown_sec=300,
            rotation_enabled=True,
        )

        async def mock_cooled_set(models):
            return {"a", "b"}

        router._cooled_set = mock_cooled_set  # type: ignore[method-assign]
        candidates = await router.get_candidates()
        # Paid should be first, then stale free models as last resort
        assert candidates[0] == "paid-model"
        assert "a" in candidates
        assert "b" in candidates

    @pytest.mark.asyncio
    async def test_status_snapshot(self):
        router = ModelRouter(
            free_pool=["a", "b", "c"],
            paid_fallback="paid",
            cooldown_sec=60,
            rotation_enabled=True,
        )

        async def mock_cooled_set(models):
            return {"b"}

        router._cooled_set = mock_cooled_set  # type: ignore[method-assign]
        status = await router.status()
        assert status["rotation_enabled"] is True
        assert status["free_pool"] == ["a", "b", "c"]
        assert status["paid_fallback"] == "paid"
        assert status["cooldown_sec"] == 60
        assert status["cooling_down"] == ["b"]
        assert status["available"] == ["a", "c"]

    @pytest.mark.asyncio
    async def test_mark_cooldown_no_model_is_noop(self):
        router = ModelRouter(cooldown_sec=60)
        await router.mark_cooldown("")
        await router.mark_cooldown(None)  # type: ignore[arg-type]
        status = await router.status()
        assert status["cooling_down"] == []
