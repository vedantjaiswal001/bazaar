"""The deterministic intent compiler extracts a faithful, reproducible draft."""
from __future__ import annotations

from bazaar.intent.compiler import RuleBasedIntentParser, compile_intent


def test_parses_running_shoes_intent():
    d = compile_intent("Buy running shoes under ₹5,000 with 30-day returns, automatically")
    assert d.max_amount == 500_000               # ₹5,000 in paise
    assert d.allowed_categories == ("footwear",)
    assert d.return_policy_days == 30
    assert d.autonomous is True
    assert d.notes == ()                          # nothing missing


def test_k_suffix_amount():
    d = compile_intent("sneakers below 5k")
    assert d.max_amount == 500_000
    assert d.allowed_categories == ("footwear",)


def test_missing_cap_and_category_are_flagged_not_signed():
    d = compile_intent("buy something nice")
    assert d.max_amount == 0
    assert d.allowed_categories == ()
    assert len(d.notes) == 2                       # both must be set before signing


def test_parser_is_deterministic():
    p = RuleBasedIntentParser()
    text = "grocery run under rs 2000"
    assert p.parse(text) == p.parse(text)
