"""Intent Compiler — natural language -> a structured mandate draft.

This is a PROBABILISTIC / advisory step: it proposes. It never signs and never
authorizes. The human confirms the rendered draft, and only then is it signed.

The default parser is deterministic and rule-based (fully reproducible, no API
key, no demo flakiness). The interface is LLM-pluggable: drop in a parser that
calls an LLM and the rest of the system is unchanged, because whatever the parser
returns is still just a DRAFT that a human must confirm and a deterministic
verifier must independently re-check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Keyword -> canonical category. Extend freely; unknown words map to nothing.
_CATEGORY_KEYWORDS: dict[str, str] = {
    "shoe": "footwear", "shoes": "footwear", "sneaker": "footwear",
    "sneakers": "footwear", "trainer": "footwear", "footwear": "footwear",
    "shirt": "apparel", "tshirt": "apparel", "t-shirt": "apparel",
    "jacket": "apparel", "apparel": "apparel", "clothing": "apparel",
    "watch": "wearables", "smartwatch": "wearables", "wearable": "wearables",
    "band": "wearables",
    "phone": "electronics", "laptop": "electronics", "headphone": "electronics",
    "headphones": "electronics", "earbuds": "electronics", "electronics": "electronics",
    "grocery": "grocery", "groceries": "grocery", "food": "grocery",
}


@dataclass(frozen=True)
class IntentDraft:
    raw_text: str
    max_amount: int                       # paise; 0 means "unspecified"
    allowed_categories: tuple[str, ...]
    return_policy_days: int
    autonomous: bool
    notes: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class IntentParser(Protocol):
    def parse(self, text: str) -> IntentDraft: ...


def _rupees_to_paise(rupees: float) -> int:
    return int(round(rupees * 100))


def _extract_amount(text: str) -> int:
    """Find an amount cap like '₹5,000', 'under 5000', 'below Rs 4,999', '5k'."""
    t = text.lower().replace(",", "")
    # "5k" / "5 k"
    m = re.search(r"(?:under|below|max|upto|up to|less than|₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*k\b", t)
    if m:
        return _rupees_to_paise(float(m.group(1)) * 1000)
    # explicit rupee amounts, preferring those near a cap word
    candidates = re.findall(
        r"(?:under|below|max|upto|up to|less than|₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)", t
    )
    if candidates:
        return _rupees_to_paise(float(candidates[0]))
    # any bare number as a last resort
    m = re.search(r"\b(\d{2,7}(?:\.\d+)?)\b", t)
    return _rupees_to_paise(float(m.group(1))) if m else 0


def _extract_categories(text: str) -> tuple[str, ...]:
    t = text.lower()
    found: list[str] = []
    for kw, cat in _CATEGORY_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", t) and cat not in found:
            found.append(cat)
    return tuple(found)


def _extract_return_days(text: str) -> int:
    m = re.search(r"(\d+)\s*[- ]?day\s*returns?", text.lower())
    return int(m.group(1)) if m else 0


def _extract_autonomous(text: str) -> bool:
    return bool(re.search(r"\b(auto(?:matically)?|auto-?buy|on my behalf)\b", text.lower()))


class RuleBasedIntentParser:
    """Deterministic parser. Same input -> same draft, always."""

    def parse(self, text: str) -> IntentDraft:
        amount = _extract_amount(text)
        categories = _extract_categories(text)
        notes = []
        if amount == 0:
            notes.append("no spend cap detected — human must set one before signing")
        if not categories:
            notes.append("no category detected — human must set one before signing")
        return IntentDraft(
            raw_text=text,
            max_amount=amount,
            allowed_categories=categories,
            return_policy_days=_extract_return_days(text),
            autonomous=_extract_autonomous(text),
            notes=tuple(notes),
        )


class LLMIntentParser:
    """LLM-backed parser (pluggable). Requires a callable `complete(prompt)->str`
    that returns JSON. If none is configured, it falls back to the rule-based
    parser so the system always runs with no API key. Wire a real client here to
    upgrade language understanding; the security model is unchanged because the
    output is still only a draft."""

    def __init__(self, complete=None) -> None:
        self._complete = complete
        self._fallback = RuleBasedIntentParser()

    def parse(self, text: str) -> IntentDraft:
        if self._complete is None:
            return self._fallback.parse(text)
        # A real implementation would prompt the model for strict JSON and parse
        # it here. We keep the deterministic fallback as the shipped default.
        return self._fallback.parse(text)


def compile_intent(text: str, parser: IntentParser | None = None) -> IntentDraft:
    return (parser or RuleBasedIntentParser()).parse(text)
