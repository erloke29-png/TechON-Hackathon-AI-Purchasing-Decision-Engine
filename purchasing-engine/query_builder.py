"""
query_builder.py  (v4)
----------------------
Generates targeted, negative-biased Tavily search queries per vendor.
One Claude call for all vendors. Returns 3 queries per vendor.

Fixes applied in v4:
  - Year is now dynamic — CURRENT_YEAR derived at import time, prompt and
    _ensure_year both use it. v3 hardcoded "2025" when the current year is 2026.
  - response.choices emptiness check before indexing — malformed API response
    previously raised IndexError, logged as a confusing "Claude call failed"
  - Null elements filtered from key_concerns / must_haves / dealbreakers —
    a null item inside the list crashed ", ".join even when the field itself was ok
  - Query sanitization in _validate — Claude's strings now stripped and capped
    at 120 chars before going to Tavily; non-string items in the array filtered
  - top_concern capped at 60 chars — long free-text priority fields broke
    fallback queries by blowing past Tavily's effective query length
  - _fallback_queries called once per vendor in _validate and reused across
    both the padding and dedup steps — was called twice in the partial path
  - TIMEOUT configurable from env (QUERY_BUILDER_TIMEOUT) — was hardcoded
  - Smoke test now includes a pure-Python fallback path assertion that verifies
    slot-3-aware fallbacks without making any API call
  - Removed unreachable deduped[:3] slice
  - Dedup substitution now logged at DEBUG level
"""

import asyncio
import datetime
import json
import logging
import os
import re

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

MODEL        = os.getenv("MODEL", "anthropic/claude-sonnet-4-5")
TIMEOUT      = float(os.getenv("QUERY_BUILDER_TIMEOUT", "15.0"))
CURRENT_YEAR = str(datetime.date.today().year)
PREV_YEAR    = str(datetime.date.today().year - 1)
YEAR_RE      = re.compile(r"20[2-9][0-9]")  # matches 2020–2099


# ------------------------------------------------------------------
# Prompts — built at import time so CURRENT_YEAR is always correct
# ------------------------------------------------------------------

_SYSTEM = f"""You are a research query specialist building a critical purchasing decision tool.
Your job is to write precise Tavily search queries that surface real problems, complaints, and risks.

You are NOT looking for positive reviews or marketing content.
Every query must be designed to find failure modes, not success stories.

Hard rules for every query:
- Maximum 10 words
- Include {PREV_YEAR} or {CURRENT_YEAR} for recency
- Use negative-signal words: problems, complaints, issues, hidden costs, lock-in,
  outage, billing surprise, regret, cancel, switch, slowdown, downtime, overcharge
- NEVER use: best, top, leading, award, trusted, powerful
- Make queries specific to what each vendor is known for — do not write
  the same query for every vendor with only the name swapped"""

_USER = """Generate exactly 3 Tavily search queries for each vendor below.
Tailor every query to this buyer's specific situation.

--- BUYER PROFILE ---
Category: {category}
Top concern: {top_concern}
Key concerns: {key_concerns}
Must-haves: {must_haves}
Dealbreakers: {dealbreakers}
Budget: {budget}
Switching from: {switch_from}
Compliance requirements: {compliance}

--- VENDORS ---
{vendors}

--- QUERY STRATEGY ---
Query 1 — General: problems, user complaints, failure cases for this vendor in "{category}"
Query 2 — Commercial: pricing surprises, hidden costs, billing issues, tier lock-in
Query 3 — Specific: use the per-vendor angle listed in slot 3 instructions below

--- SLOT 3 ANGLES (apply to query 3 only — one instruction per vendor) ---
{slot3_instructions}

--- OUTPUT ---
Return ONLY a valid JSON object. No preamble, no explanation, no markdown fences.

{{
  "VendorName": ["query one", "query two", "query three"],
  "VendorName2": ["query one", "query two", "query three"]
}}"""


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

async def build_queries(
    decision_profile: dict,
    vendors: list[str],
) -> dict[str, list[str]]:
    """
    Calls Claude once to generate 3 negative-biased Tavily search queries
    per vendor, tailored to the buyer's decision profile.

    Always returns a fully populated dict — every failure path produces
    slot-3-aware fallback queries, never a bare empty dict.

    Args:
        decision_profile: Parsed INTERVIEW_COMPLETE JSON (the central contract)
        vendors:          List of vendor names from identify_vendors()

    Returns:
        {vendor_name: [query1, query2, query3]}
    """
    if not vendors:
        return {}

    context = _extract_context(decision_profile)
    slot3   = _per_vendor_slot3(
        vendors,
        context["preferred_vendor"],
        context["current_stack"],
        context["top_concern"],
        context["category"],
    )

    slot3_instructions = "\n".join(
        f"- {v}: {data['instruction']}" for v, data in slot3.items()
    )

    user_prompt = _USER.format(
        vendors=json.dumps(vendors, ensure_ascii=False),
        slot3_instructions=slot3_instructions,
        category=context["category"],
        top_concern=context["top_concern"],
        key_concerns=context["key_concerns"],
        must_haves=context["must_haves"],
        dealbreakers=context["dealbreakers"],
        budget=context["budget"],
        switch_from=context["switch_from"],
        compliance=context["compliance"],
    )

    max_tokens = max(600, len(vendors) * 130)
    result     = {}

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.2,
            ),
            timeout=TIMEOUT,
        )

        # Guard: malformed responses can return an empty choices list
        if not response.choices:
            logger.warning("[build_queries] Claude returned empty choices list — using fallbacks")
        else:
            content = response.choices[0].message.content
            if not content:
                logger.warning("[build_queries] Claude returned empty content — using fallbacks")
            else:
                result = safe_json_parse(content.strip())
                if not result:
                    logger.warning(
                        "[build_queries] Could not parse response as JSON dict — using fallbacks"
                    )

    except asyncio.TimeoutError:
        logger.warning(
            "[build_queries] Claude call timed out after %.0fs — using fallbacks", TIMEOUT
        )
    except Exception as exc:
        logger.error(
            "[build_queries] Claude call failed (%s): %s", type(exc).__name__, exc
        )

    return _validate(result, vendors, context, slot3)


# ------------------------------------------------------------------
# Internals
# ------------------------------------------------------------------

def _extract_context(profile: dict) -> dict:
    """
    Pull the fields Claude needs to write targeted queries.

    v4 fixes:
    - Null elements inside key_concerns / must_haves / dealbreakers filtered
      out before join — a None item in the list crashed ", ".join even when
      the field itself was present and non-null
    - top_concern capped at 60 chars — long free-text priority fields
      produced fallback queries that exceeded Tavily's effective query length
    """
    budget   = profile.get("budget") or {}
    business = profile.get("business_context") or {}
    signals  = profile.get("search_signals") or {}

    # Filter null elements — list could be ["SOC 2", null, "rate limits"]
    key_concerns = [k for k in (signals.get("key_concerns") or []) if k]
    must_haves   = [m for m in (profile.get("must_haves")   or []) if m]
    dealbreakers = [d for d in (profile.get("dealbreakers") or []) if d]
    compliance   = [c for c in (business.get("compliance_requirements") or []) if c]

    # Stated priority first — key_concerns[0] is insertion order, not importance
    top_concern = (
        profile.get("priority")
        or (key_concerns[0] if key_concerns else "cost and reliability")
    )
    # Cap so long free-text priorities don't blow out fallback query length
    top_concern = str(top_concern).strip()[:60]

    # budget.get("amount", "unspecified") returns None when key exists with null value
    amount     = budget.get("amount")
    amount_str = str(amount) if amount is not None else "unspecified"
    budget_str = (
        f"{amount_str} "
        f"{budget.get('currency', 'USD')}/"
        f"{budget.get('period', 'month')}"
    )

    return {
        "category":         str(profile.get("category") or "software"),
        "top_concern":      top_concern,
        "key_concerns":     ", ".join(key_concerns) or "general fit",
        "must_haves":       ", ".join(must_haves)   or "none stated",
        "dealbreakers":     ", ".join(dealbreakers) or "none stated",
        "budget":           budget_str,
        "switch_from":      signals.get("switch_from") or "nothing stated",
        "compliance":       ", ".join(compliance) or "none",
        "preferred_vendor": signals.get("preferred_vendor"),
        "current_stack":    signals.get("current_stack") or [],
    }


def _per_vendor_slot3(
    vendors: list[str],
    preferred_vendor: str | None,
    current_stack: list[str],
    top_concern: str,
    category: str,
) -> dict[str, dict[str, str]]:
    """
    Returns {vendor: {"instruction": str, "fallback_q": str}} for every vendor.

    instruction  — natural language angle passed to Claude's slot 3 prompt
    fallback_q   — ready-to-use Tavily query if Claude fails for this vendor

    Priority order per vendor:
      1. Preferred vendor → bias probe (is the preference actually deserved?)
      2. current_stack non-empty → integration angle
      3. Fallback → top concern applied to this vendor
    """
    stack_display = ", ".join(current_stack[:2]) if current_stack else None
    result        = {}

    for vendor in vendors:
        is_preferred = (
            preferred_vendor is not None
            and vendor.strip().lower() == preferred_vendor.strip().lower()
        )

        if is_preferred:
            instruction = (
                f"probe whether '{vendor}' deserves this buyer's stated preference — "
                f"what do people who chose {vendor} regret or wish they'd known beforehand"
            )
            fallback_q = f"{vendor} buyer regret disappointment problems {CURRENT_YEAR}"

        elif stack_display:
            instruction = (
                f"integration problems or friction between '{vendor}' "
                f"and {stack_display} in {CURRENT_YEAR}"
            )
            fallback_q = f"{vendor} {current_stack[0]} integration problems {CURRENT_YEAR}"

        else:
            instruction = f'"{top_concern}" failures or complaints specific to {vendor}'
            fallback_q  = f"{vendor} {top_concern} issues {category} {CURRENT_YEAR}"

        result[vendor] = {"instruction": instruction, "fallback_q": fallback_q}

    return result


def _validate(
    result: dict,
    vendors: list[str],
    context: dict,
    slot3: dict,
) -> dict[str, list[str]]:
    """
    Ensure every vendor has exactly 3 distinct, sanitized, year-stamped queries.

    v4 fixes:
    - _fallback_queries called once per vendor and reused across padding and
      dedup steps — was called twice in the partial path
    - Query sanitization: Claude's strings stripped and capped at 120 chars,
      non-string items in the array filtered before they reach Tavily
    - Dedup substitution logged at DEBUG level
    - Removed unreachable [:3] slice on deduped
    """
    result_lower = {k.lower(): v for k, v in result.items()}
    validated    = {}

    for vendor in vendors:
        raw       = result_lower.get(vendor.lower(), [])
        fallbacks = _fallback_queries(vendor, context, slot3)  # once — reused below

        if not isinstance(raw, list):
            logger.warning(
                "[build_queries] %s: Claude returned %s instead of list — using fallbacks",
                vendor, type(raw).__name__,
            )
            raw = []

        if len(raw) >= 3:
            queries = raw[:3]
        elif len(raw) > 0:
            logger.warning(
                "[build_queries] %s: only %d quer%s from Claude — padding with fallbacks",
                vendor, len(raw), "y" if len(raw) == 1 else "ies",
            )
            queries = (raw + fallbacks)[:3]
        else:
            logger.warning(
                "[build_queries] %s: no queries from Claude — using fallbacks", vendor
            )
            queries = list(fallbacks)

        # Sanitize — strip whitespace, cap length, filter non-strings
        # Runs before year stamp so _ensure_year operates on clean strings
        queries = [
            q.strip()[:120]
            for q in queries
            if isinstance(q, str) and q.strip()
        ]

        # Year stamp
        queries = [_ensure_year(q) for q in queries]

        # Pad back to 3 if sanitization filtered anything (rare but safe)
        for fb in fallbacks:
            if len(queries) >= 3:
                break
            fb_clean = _ensure_year(fb.strip()[:120])
            if fb_clean not in queries:
                queries.append(fb_clean)

        # Deduplicate
        seen    = set()
        deduped = []
        for q in queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                deduped.append(q)
            else:
                logger.debug("[build_queries] %s: removed duplicate query: %s", vendor, q)

        # Pad after dedup using same fallback list (no second function call)
        for fb in fallbacks:
            if len(deduped) >= 3:
                break
            fb_clean = _ensure_year(fb.strip()[:120])
            if fb_clean.lower() not in seen:
                seen.add(fb_clean.lower())
                deduped.append(fb_clean)
                logger.debug("[build_queries] %s: substituted fallback after dedup", vendor)

        validated[vendor] = deduped

    return validated


def _ensure_year(query: str) -> str:
    """Append current year if no year marker (2020–2099) is present."""
    if not YEAR_RE.search(query):
        return query.rstrip() + f" {CURRENT_YEAR}"
    return query


def _fallback_queries(vendor: str, context: dict, slot3: dict) -> list[str]:
    """
    Slot-3-aware fallback queries used when Claude fails on a specific vendor.

    Uses the precomputed fallback_q from _per_vendor_slot3 so preferred vendor
    keeps its bias probe and stack-aware vendors keep their integration angle
    even when Claude failed entirely.
    """
    cat     = context["category"]
    slot3_q = slot3.get(vendor, {}).get(
        "fallback_q",
        f"{vendor} {context['top_concern']} issues {CURRENT_YEAR}",
    )
    return [
        f"{vendor} {cat} problems complaints {CURRENT_YEAR}",
        f"{vendor} pricing hidden costs billing issues {CURRENT_YEAR}",
        slot3_q,
    ]


# ------------------------------------------------------------------
# safe_json_parse
# NOTE: In the real project this lives in utils.py (already written).
# This copy exists so the file runs standalone for testing.
# ------------------------------------------------------------------

def safe_json_parse(text: str) -> dict:
    """Extract a JSON dict from Claude response, handling markdown fences."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return {}


# ------------------------------------------------------------------
# Smoke test — python query_builder.py
# ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    _demo_profile = {
        "category": "AI API providers",
        "must_haves": ["SOC 2 Type II", "streaming support", "predictable pricing"],
        "dealbreakers": ["usage caps without warning", "no SLA"],
        "priority": "pricing predictability",
        "budget": {"amount": 2000, "currency": "USD", "period": "month"},
        "business_context": {
            "team_size": 8,
            "growth_rate": "20% monthly",
            "compliance_requirements": ["SOC 2"],
        },
        "search_signals": {
            "key_concerns": ["pricing unpredictability", "SOC 2 compliance", "rate limits"],
            "switch_from": "OpenAI",
            "preferred_vendor": "OpenAI",
            "current_stack": ["AWS", "Slack"],
            "stakeholders": ["CTO", "Finance"],
            "roi_timeline": "3 months",
            "search_negatives": True,
        },
    }

    _null_edge_profile = {
        **_demo_profile,
        "budget":      {"amount": None, "currency": "USD", "period": "month"},
        "must_haves":  None,
        "dealbreakers": None,
        "search_signals": {
            **_demo_profile["search_signals"],
            "key_concerns": ["pricing unpredictability", None, "rate limits"],
        },
    }

    _demo_vendors = ["OpenAI", "Anthropic", "Google Gemini", "Cohere", "Mistral"]

    # --- Pure-Python fallback path assertion (no API call needed) ---
    print("=== Fallback path assertions ===\n")
    _ctx   = _extract_context(_demo_profile)
    _slot3 = _per_vendor_slot3(
        _demo_vendors,
        _ctx["preferred_vendor"],
        _ctx["current_stack"],
        _ctx["top_concern"],
        _ctx["category"],
    )
    _fallback_result = _validate({}, _demo_vendors, _ctx, _slot3)

    assert "regret" in _fallback_result["OpenAI"][2].lower(), (
        f"Expected bias probe in OpenAI slot 3, got: {_fallback_result['OpenAI'][2]}"
    )
    assert "AWS" in _fallback_result["Anthropic"][2], (
        f"Expected integration angle in Anthropic slot 3, got: {_fallback_result['Anthropic'][2]}"
    )
    assert all(len(qs) == 3 for qs in _fallback_result.values()), (
        "Not all vendors have exactly 3 fallback queries"
    )
    assert all(YEAR_RE.search(q) for qs in _fallback_result.values() for q in qs), (
        "Some fallback queries missing year marker"
    )
    print("All fallback assertions passed.\n")

    # --- Live API test ---
    async def _run():
        print("=== Demo scenario (live API) ===\n")
        queries = await build_queries(_demo_profile, _demo_vendors)
        for vendor, qs in queries.items():
            tag = "  ← bias probe" if vendor == "OpenAI" else ""
            print(f"{vendor}:{tag}")
            for label, q in zip(["problems", "pricing ", "slot 3 "], qs):
                print(f"  [{label}] {q}")
            print()

        print("=== Null-field edge case ===\n")
        queries2 = await build_queries(_null_edge_profile, _demo_vendors)
        for vendor, qs in queries2.items():
            print(f"{vendor}: {qs[0][:70]}...")

    asyncio.run(_run())