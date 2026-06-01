"""Tests for JSON extraction and decision normalisation in OpenRouterClient."""

import pytest
from app.ai.openrouter_client import OpenRouterClient, normalize_decision, TradeDecision


class TestNormalizeDecision:
    def test_exact_tokens(self):
        assert normalize_decision("BUY") == "BUY"
        assert normalize_decision("SELL") == "SELL"
        assert normalize_decision("HOLD") == "HOLD"

    def test_lowercase(self):
        assert normalize_decision("buy") == "BUY"
        assert normalize_decision("sell") == "SELL"

    def test_malformed_prefix(self):
        assert normalize_decision(": HOLD") == "HOLD"
        assert normalize_decision(":SELL") == "SELL"

    def test_punctuation_only(self):
        assert normalize_decision(",") == "HOLD"
        assert normalize_decision(":") == "HOLD"

    def test_none(self):
        assert normalize_decision(None) == "HOLD"  # type: ignore[arg-type]

    def test_embedded_in_text(self):
        assert normalize_decision("The decision is BUY today") == "BUY"
        assert normalize_decision("I think SELL is best") == "SELL"


class TestExtractJson:
    def test_plain_json_object(self):
        client = OpenRouterClient()
        assert client._extract_json('{"a": 1}') == {"a": 1}

    def test_json_with_markdown_fences(self):
        client = OpenRouterClient()
        text = '```json\n{"decision": "BUY"}\n```'
        assert client._extract_json(text) == {"decision": "BUY"}

    def test_json_with_trailing_prose(self):
        client = OpenRouterClient()
        text = 'Here is the result:\n\n{"decision": "BUY"}\n\nHope this helps!'
        assert client._extract_json(text) == {"decision": "BUY"}

    def test_array_response(self):
        client = OpenRouterClient()
        text = '[{"d": 1}, {"d": 2}] extra text'
        assert client._extract_json(text) == [{"d": 1}, {"d": 2}]

    def test_empty_returns_empty_dict(self):
        client = OpenRouterClient()
        assert client._extract_json("") == {}
        assert client._extract_json(None) == {}  # type: ignore[arg-type]

    def test_no_json_returns_empty_dict(self):
        client = OpenRouterClient()
        assert client._extract_json("No JSON here, just prose.") == {}


class TestParseObject:
    def test_valid_json(self):
        client = OpenRouterClient()
        assert client._parse_object('{"confidence": 0.8}') == {"confidence": 0.8}

    def test_wrapped_in_fences(self):
        client = OpenRouterClient()
        assert client._parse_object('```\n{"confidence": 0.8}\n```') == {"confidence": 0.8}

    def test_malformed_extracts_best_effort(self):
        client = OpenRouterClient()
        # Missing closing brace
        assert client._parse_object('{"confidence": 0.8') == {}

    def test_array_becomes_first_element(self):
        client = OpenRouterClient()
        assert client._parse_object('[{"a": 1}, {"b": 2}]') == {"a": 1}


class TestParseArray:
    def test_valid_array(self):
        client = OpenRouterClient()
        assert client._parse_array('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]

    def test_dict_with_decisions_key(self):
        client = OpenRouterClient()
        assert client._parse_array('{"decisions": [{"a": 1}]}') == [{"a": 1}]

    def test_dict_with_results_key(self):
        client = OpenRouterClient()
        assert client._parse_array('{"results": [{"a": 1}]}') == [{"a": 1}]

    def test_malformed_returns_empty_list(self):
        client = OpenRouterClient()
        assert client._parse_array("not json") == []


class TestTradeDecisionModel:
    def test_defaults(self):
        td = TradeDecision(decision="BUY", confidence=0.7)
        assert td.decision == "BUY"
        assert td.confidence == 0.7
        assert td.timeframe == "H1"
        assert td.entry_price == 0.0
