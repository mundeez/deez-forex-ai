"""v2 AI Trading Team engine.

A multi-tiered decision engine where domain-specific analysts (technical,
fundamental, sentiment, macro) feed a Lead Strategist, which is then reviewed
by a Verifier. Each tier can use a different model from OpenRouter, enabling
latency-aware assignments (fast models for the hot path, reasoning models for
deep analysis and verification).
"""
