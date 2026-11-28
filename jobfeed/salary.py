"""Salaries for the board: the posted range where a role states one, an estimate where it doesn't.

Most careers sites leave pay out of their API, but many roles state it in the description
("Salary: £60,000 – £90,000"). `from_text` reads that. For the rest, `estimate` gives a
typical London-market range for the role's level, adjusted for how the employer pays and
where the role is. Estimates are marked as such on the board, never shown as posted pay.
"""
from __future__ import annotations

import re

LOW, HIGH = 15_000, 500_000  # plausible annual base pay in pounds

_AMOUNT = r"£\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(k\b|K\b)?"
_RANGE = re.compile(_AMOUNT + r"\s*(?:-|–|—|to)\s*" + _AMOUNT)
_SINGLE = re.compile(_AMOUNT)
# a lone figure counts only when the text around it says it is pay
_PAY_WORDS = re.compile(r"\b(salary|base|compensation|pay|per annum|p\.?a\.?|annual|package|up to|starting)\b", re.I)
# funding rounds, revenue and the like
_NOT_PAY = re.compile(r"^\s?(m|bn|million|billion)\b", re.I)


def _pounds(number: str, k: str | None) -> float:
    value = float(number.replace(",", ""))
    return value * 1000 if k else value


def text(low: float, high: float | None = None) -> str:
    """'£60k – £90k' (or '£60k' when there is one figure)."""
    parts = [f"£{round(v / 1000):g}k" for v in (low, high) if v]
    return " – ".join(dict.fromkeys(parts))


def from_text(description: str) -> str:
    """The posted salary in a job description, or '' when it states none in pounds a year."""
    for match in _RANGE.finditer(description):
        if _NOT_PAY.match(description[match.end() :]):
            continue
        low = _pounds(match.group(1), match.group(2) or match.group(4))
        high = _pounds(match.group(3), match.group(4))
        if LOW <= low <= high <= HIGH:
            return text(low, high)
    for match in _SINGLE.finditer(description):
        if _NOT_PAY.match(description[match.end() :]):
            continue
        around = description[max(0, match.start() - 60) : match.end() + 30]
        value = _pounds(match.group(1), match.group(2))
        if LOW <= value <= HIGH and _PAY_WORDS.search(around):
            return text(value)
    return ""


# Typical base pay for an engineering role at a London tech company, in £k.
BASE = {
    "junior": (40, 55),
    "mid": (65, 85),
    "senior": (85, 110),
    "staff": (110, 145),
    "manager": (100, 135),
}

# Employers known to pay well above (or a little below) that market.
QUANT = {
    "jane-street", "hudson-river-trading", "jump-trading", "optiver", "imc-trading",
    "tower-research-capital", "xtx-markets", "qube-research-technologies", "squarepoint-capital",
    "point72", "man-group", "winton", "flow-traders", "b2c2", "wintermute",
}
TOP_PAYERS = {
    "openai", "anthropic", "cognition", "cursor", "perplexity", "scale-ai", "isomorphic-labs",
    "databricks", "stripe", "palantir", "anduril", "helsing", "waymo", "airbnb", "snowflake",
    "coinbase", "ramp", "plaid", "robinhood", "figma", "notion", "datadog", "mongodb", "wiz",
    "roblox", "epic-games", "pinterest", "reddit", "spotify", "elevenlabs", "sierra", "glean",
    "decagon", "replit", "harvey", "modal", "poolside", "incidentio", "linear", "vercel",
}
INDUSTRY = {
    "magnificent-7": 1.3,
    "ai": 1.25,
    "consumer": 0.95,
    "climate-and-energy": 0.95,
    "health-and-life-sciences": 0.95,
}


def _company_factor(company: str, industry: str) -> float:
    if company in QUANT:
        return 1.6
    if company in TOP_PAYERS:
        return 1.5
    return INDUSTRY.get(industry, 1.0)


def _place_factor(region: str) -> float:
    lowered = region.lower()
    if "london" in lowered:
        return 1.0
    if "remote" in lowered:
        return 0.95
    return 0.85


def _round5(value: float) -> int:
    return int(5 * round(value / 5))


def estimate(seniority: str, category: str, company: str, industry: str, region: str) -> str:
    """A typical range for the role, e.g. '£80k – £105k'."""
    low, high = BASE.get(seniority, BASE["mid"])
    factor = _company_factor(company, industry) * _place_factor(region)
    if category not in ("engineering", "data"):
        factor *= 0.85
    return text(_round5(low * factor) * 1000, _round5(high * factor) * 1000)
