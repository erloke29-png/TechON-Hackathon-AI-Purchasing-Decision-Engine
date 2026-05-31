"""
results_agent.py
────────────────
Phase 4 of the pipeline: decision profile + Tavily results → structured recommendation.

Flow:
    1. _prepare_tavily_context()   Compress raw Tavily data into readable text for the prompt
    2. generate_results()          Claude synthesises the full recommendation
    3. get_recommendation()        Public entry point — call this from main.py

Usage in main.py:
    from results_agent import get_recommendation
    recommendation = await get_recommendation(profile, search_data, openai_client)
"""

import json
import os
from openai import AsyncOpenAI

# ─── Config ───────────────────────────────────────────────────────────────────

MOCK_LLM = os.getenv("MOCK_LLM", "false").lower() == "true"

MAX_SNIPPETS_PER_QUERY = 2   # keep prompt lean — tavily_answer is primary signal
MAX_SNIPPET_CHARS = 300      # truncate long snippets

# ─── System prompt ────────────────────────────────────────────────────────────

RESULTS_AGENT_SYSTEM_PROMPT = """
You are TechON's recommendation synthesiser. You receive a buyer's decision profile and \
current web search results about each vendor. Your job is to produce a structured, \
evidence-based vendor recommendation that the buyer can defend to their organisation.

---

## Critical AI Rules — read these first

You are NOT an agreeable recommendation engine. You are a critical analyst. These rules \
override everything else:

1. Never recommend a vendor without explicitly stating its strongest weakness.
2. The regret_score must represent the most honest argument AGAINST your top pick — \
   not a minor caveat. If you cannot find a serious concern, look harder.
3. If a vendor has a documented issue that matches a user dealbreaker, flag it clearly \
   even if that vendor scores highest overall. Note it in red_flags with a ⚠️ prefix.
4. Never score any vendor above 88 overall without explicit documentary evidence in the \
   search results. High scores require high evidence.
5. If Tavily data for a vendor is thin or missing, set data_confidence to "low". \
   Do not invent strengths or red flags not supported by search results.

---

## Scoring

Score each vendor on 5 dimensions, 0–100. Base scores on evidence in the search results only.

| Dimension    | What to score                                                        |
|--------------|----------------------------------------------------------------------|
| compliance   | Does evidence confirm the vendor meets stated compliance requirements?|
| reliability  | Uptime track record, incident frequency, severity of outages         |
| pricing      | Fit to the user's budget at their stated usage volume                |
| feature_fit  | Coverage of stated must-haves                                        |
| lock_in_risk | Switching cost, proprietary dependencies — LOWER risk = HIGHER score |

Apply weights to calculate overall_score based on the profile's priority field:
- "reliability"        → reliability: 40%, compliance: 20%, feature_fit: 20%, pricing: 10%, lock_in_risk: 10%
- "cost" or "price"    → pricing: 40%, reliability: 20%, feature_fit: 20%, compliance: 10%, lock_in_risk: 10%
- "compliance"         → compliance: 40%, reliability: 20%, feature_fit: 20%, pricing: 10%, lock_in_risk: 10%
- "features"           → feature_fit: 40%, reliability: 20%, compliance: 20%, pricing: 10%, lock_in_risk: 10%
- anything else        → equal weights: 20% each

Additional rule: if "lock-in" or "vendor lock" appears in dealbreakers, add 15% to \
lock_in_risk weight and reduce all other weights proportionally.

---

## Data quality rules

- Only state something as a fact if it appears in the Tavily data provided.
- sources_used must only contain URLs that appear in the search results — never invent URLs.
- If a vendor's search results are empty or low quality, note it in data_gaps and lower \
  data_confidence accordingly.
- Assumptions are things you inferred but could not confirm from search results. Log them.

---

## Output format

Output ONLY valid JSON between these exact markers. Nothing before the first marker, \
nothing after the second. No explanation, no preamble.

---BEGIN_RESULTS---
{
  "recommended_vendor": "vendor name",
  "summary": "One to two sentence recommendation the buyer could read aloud. Mention the top concern.",
  "vendors": [
    {
      "name": "vendor name",
      "rank": 1,
      "overall_score": 0,
      "dimension_scores": {
        "compliance": 0,
        "reliability": 0,
        "pricing": 0,
        "feature_fit": 0,
        "lock_in_risk": 0
      },
      "strengths": ["evidence-backed strength"],
      "red_flags": ["documented concern — prefix with ⚠️ if matches a dealbreaker"],
      "why_not": "null for the winner. For losers: one honest sentence on why they lost.",
      "lock_in_danger": "high | medium | low",
      "lock_in_reasons": ["specific reason with evidence"],
      "sentiment_summary": "One sentence on real user sentiment based on search results.",
      "negotiation_levers": ["specific, actionable lever the buyer can use"],
      "data_confidence": "high | medium | low",
      "sources_used": ["https://only-real-urls-from-search-results.com"]
    }
  ],
  "regret_score": {
    "score": 0,
    "vendor": "recommended vendor name",
    "reasoning": "Two to three sentences. The strongest honest argument against the top pick.",
    "main_risk": "Short label for the primary risk, e.g. Rate limit ceiling at growth rate"
  },
  "assumption_log": [
    {
      "assumption": "What was assumed but not confirmed by search results",
      "impact": "high | medium | low",
      "how_to_verify": "Specific action the buyer can take to confirm this"
    }
  ],
  "data_gaps": [
    {
      "vendor": "vendor name",
      "missing": "What information was not found in search results",
      "effect": "How this gap affects confidence in the recommendation"
    }
  ]
}
---END_RESULTS---
""".strip()


# ─── Tavily context preparation ───────────────────────────────────────────────

def _prepare_tavily_context(search_data: dict) -> str:
    """
    Compress raw Tavily search results into readable structured text.
    Groups by vendor, keeps tavily_answer as primary signal, adds top snippets.
    Failed searches are noted so the agent knows data is missing.
    """
    results = search_data.get("results", [])
    if not results:
        return "No search results available."

    # Group by vendor
    by_vendor: dict[str, list] = {}
    for r in results:
        vendor = r.get("vendor", "general")
        by_vendor.setdefault(vendor, []).append(r)

    lines = ["## Tavily Search Results\n"]

    for vendor, vendor_results in by_vendor.items():
        lines.append(f"### {vendor}")

        for r in vendor_results:
            category = r.get("category", "unknown")
            error = r.get("error")
            tavily_answer = r.get("tavily_answer")
            snippets = r.get("results", [])

            lines.append(f"\n**{category}** — query: \"{r.get('query', '')}\"")

            if error:
                lines.append(f"  ⚠️ Search failed: {error}")
                lines.append(f"  Data confidence: none")
                continue

            if tavily_answer:
                lines.append(f"  Summary: {tavily_answer}")
            else:
                lines.append(f"  Summary: (no Tavily summary returned)")

            # Add top snippets as supporting evidence
            for snippet in snippets[:MAX_SNIPPETS_PER_QUERY]:
                url = snippet.get("url", "")
                content = snippet.get("content", "")[:MAX_SNIPPET_CHARS]
                if url and content:
                    lines.append(f"  Source: {url}")
                    lines.append(f"  Snippet: {content}...")

        lines.append("")

    return "\n".join(lines)


# ─── Results generation ───────────────────────────────────────────────────────

async def generate_results(
    profile: dict,
    search_data: dict,
    client: AsyncOpenAI,
) -> dict:
    """
    Call Claude via OpenRouter with the profile and Tavily context.
    Returns the parsed recommendation dict.
    Raises ValueError if output cannot be parsed.
    """
    tavily_context = _prepare_tavily_context(search_data)

    user_message = (
        "## Decision Profile\n\n"
        + json.dumps(profile, indent=2)
        + "\n\n"
        + tavily_context
    )

    response = await client.chat.completions.create(
        model="anthropic/claude-sonnet-4-5",
        messages=[
            {"role": "system", "content": RESULTS_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=4000,  # results are verbose — needs more headroom than query builder
        temperature=0.3,  # slightly higher than query builder — reasoning benefits from some flexibility
    )

    raw = response.choices[0].message.content.strip()

    # Extract between markers
    match_start = raw.find("---BEGIN_RESULTS---")
    match_end = raw.find("---END_RESULTS---")

    if match_start == -1 or match_end == -1:
        raise ValueError(
            f"[results_agent] Markers not found in response.\nRaw output:\n{raw}"
        )

    json_str = raw[match_start + len("---BEGIN_RESULTS---"):match_end].strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"[results_agent] Failed to parse JSON between markers: {e}\nJSON string:\n{json_str}"
        )


# ─── Mock result ──────────────────────────────────────────────────────────────

MOCK_RESULT = {
    "recommended_vendor": "Anthropic",
    "summary": (
        "Anthropic is the strongest fit for your SOC 2 requirement and reliability priority, "
        "but documented rate limit issues at scale are the key risk to validate before committing "
        "given your 20% monthly growth."
    ),
    "vendors": [
        {
            "name": "Anthropic",
            "rank": 1,
            "overall_score": 81,
            "dimension_scores": {
                "compliance": 87, "reliability": 78,
                "pricing": 70, "feature_fit": 85, "lock_in_risk": 68
            },
            "strengths": [
                "SOC 2 Type II certified — directly addresses your compliance requirement",
                "Clean API with low vendor-specific abstractions, reducing migration overhead"
            ],
            "red_flags": [
                "Documented rate limit complaints at high token volumes — risk at 20% monthly growth"
            ],
            "why_not": None,
            "lock_in_danger": "medium",
            "lock_in_reasons": [
                "Prompt engineering optimised for Claude instruction-following style may not transfer cleanly"
            ],
            "sentiment_summary": "Mostly positive on output quality; recurring frustration with rate limits and pricing unpredictability.",
            "negotiation_levers": [
                "Annual commitment unlocks enterprise rate limit tiers — ask specifically about burst capacity guarantees",
                "Reference active evaluation of Gemini and Mistral to create competitive pressure"
            ],
            "data_confidence": "medium",
            "sources_used": ["https://www.reddit.com/r/ClaudeAI"]
        },
        {
            "name": "OpenAI",
            "rank": 2,
            "overall_score": 74,
            "dimension_scores": {
                "compliance": 82, "reliability": 58,
                "pricing": 72, "feature_fit": 88, "lock_in_risk": 52
            },
            "strengths": [
                "Largest ecosystem and broadest model range",
                "SOC 2 Type II and GDPR compliance documented"
            ],
            "red_flags": [
                "⚠️ Multiple documented outages in 2025 (February, July) — conflicts with your reliability priority",
                "Pricing unpredictability is the primary reason you are switching — this concern is documented by other users too"
            ],
            "why_not": "Two documented major outages in 2025 directly conflict with your stated reliability priority, and pricing unpredictability is your current pain point with this vendor.",
            "lock_in_danger": "high",
            "lock_in_reasons": [
                "Proprietary function calling format differs from open standards",
                "Fine-tuned models are non-portable"
            ],
            "sentiment_summary": "Widespread frustration with outage frequency and rate limit handling in 2025.",
            "negotiation_levers": [
                "Reference competitor evaluations — OpenAI will offer credits to retain at-risk accounts",
                "Push for SLA with financial penalties before any annual commitment"
            ],
            "data_confidence": "high",
            "sources_used": [
                "https://community.openai.com/t/openai-2-26-2025-has-outages-and-is-actively-investigating/1130186",
                "https://www.pingdom.com/outages/chatgpt-outage-july-2025-recap"
            ]
        },
        {
            "name": "Google Gemini",
            "rank": 3,
            "overall_score": 71,
            "dimension_scores": {
                "compliance": 80, "reliability": 70,
                "pricing": 82, "feature_fit": 75, "lock_in_risk": 60
            },
            "strengths": [
                "Competitive token pricing — Flash-Lite at $0.10/M input tokens is well within your budget",
                "Google infrastructure — generally strong uptime track record"
            ],
            "red_flags": [
                "Enterprise compliance documentation less established than OpenAI or Anthropic",
                "API surface changed significantly in 2024-2025 — migration risk for existing integrations"
            ],
            "why_not": "Pricing is the strongest suit, but compliance documentation trail is thinner and API stability concerns make it a higher-risk choice for a production team.",
            "lock_in_danger": "medium",
            "lock_in_reasons": [
                "Google has a history of deprecating developer products — long-term commitment risk"
            ],
            "sentiment_summary": "Positive on pricing; mixed on enterprise support quality and API stability.",
            "negotiation_levers": [
                "Google Cloud credits can offset API costs significantly — ask about bundled GCP deals",
                "Request a dedicated TAM (Technical Account Manager) as a condition of enterprise agreement"
            ],
            "data_confidence": "medium",
            "sources_used": [
                "https://blog.laozhang.ai/en/posts/gemini-api-pricing",
                "https://intuitionlabs.ai/articles/llm-api-pricing-comparison-2025"
            ]
        },
        {
            "name": "Cohere",
            "rank": 4,
            "overall_score": 58,
            "dimension_scores": {
                "compliance": 72, "reliability": 60,
                "pricing": 68, "feature_fit": 62, "lock_in_risk": 55
            },
            "strengths": [
                "Strong enterprise focus with dedicated compliance documentation",
                "Retrieval-augmented generation (RAG) capabilities are best-in-class"
            ],
            "red_flags": [
                "Smaller ecosystem — community support and third-party integrations significantly thinner",
                "⚠️ Switching cost from OpenAI is non-trivial — API design differences require rework"
            ],
            "why_not": "Cohere's feature set is well-suited to enterprise RAG use cases, but for general API usage your team would take on meaningful migration effort for a vendor with a smaller support ecosystem.",
            "lock_in_danger": "medium",
            "lock_in_reasons": [
                "Proprietary embedding models are not interchangeable with other providers"
            ],
            "sentiment_summary": "Niche but loyal user base; concerns about general-purpose capability relative to larger providers.",
            "negotiation_levers": [
                "Cohere is aggressive on enterprise deals — ask for a proof-of-concept period with credits"
            ],
            "data_confidence": "low",
            "sources_used": []
        },
        {
            "name": "Mistral",
            "rank": 5,
            "overall_score": 54,
            "dimension_scores": {
                "compliance": 60, "reliability": 58,
                "pricing": 75, "feature_fit": 58, "lock_in_risk": 72
            },
            "strengths": [
                "Competitive pricing and open-weight models reduce lock-in risk",
                "Self-hosting option eliminates vendor dependency entirely"
            ],
            "red_flags": [
                "SOC 2 compliance documentation not clearly established for cloud API — risk for your requirement",
                "Smaller team and infrastructure than hyperscale competitors — reliability less proven at scale"
            ],
            "why_not": "Mistral's open-weight model is compelling for lock-in avoidance, but unconfirmed SOC 2 status is a direct dealbreaker match given your compliance requirement.",
            "lock_in_danger": "low",
            "lock_in_reasons": [],
            "sentiment_summary": "Enthusiastic early adopter community; enterprise readiness questions remain open.",
            "negotiation_levers": [
                "Self-hosting option gives you full negotiating leverage — use it even if you don't plan to self-host"
            ],
            "data_confidence": "low",
            "sources_used": []
        }
    ],
    "regret_score": {
        "score": 6,
        "vendor": "Anthropic",
        "reasoning": (
            "The main regret risk is rate limits. At 20% monthly growth you will likely hit "
            "enterprise tier thresholds within 3-4 months. If Anthropic cannot provide committed "
            "capacity guarantees in writing, you may face the same urgent migration you are trying "
            "to avoid right now — but with Claude-optimised prompts that don't transfer cleanly."
        ),
        "main_risk": "Rate limit ceiling at current growth rate"
    },
    "assumption_log": [
        {
            "assumption": "Anthropic's SOC 2 Type II certification covers your specific data processing use case",
            "impact": "high",
            "how_to_verify": "Request the full SOC 2 report from trust.anthropic.com and share with your compliance team"
        },
        {
            "assumption": "Your 50M token/month estimate is accurate — actual usage may be significantly higher",
            "impact": "medium",
            "how_to_verify": "Pull actual token logs from your current OpenAI usage dashboard before finalising"
        }
    ],
    "data_gaps": [
        {
            "vendor": "Anthropic",
            "missing": "Specific enterprise rate limit tiers and burst capacity guarantees",
            "effect": "Cannot confirm whether Anthropic can support 50M tokens/month plus 20% growth without throttling"
        },
        {
            "vendor": "Cohere",
            "missing": "Recent user reliability reports and pricing at 50M token scale",
            "effect": "Cohere ranking is lower confidence — could be under- or over-ranked"
        },
        {
            "vendor": "Mistral",
            "missing": "SOC 2 compliance certification status for cloud API",
            "effect": "Mistral may be ruled out entirely if SOC 2 is confirmed absent — verify before dismissing"
        }
    ]
}


# ─── Public entry point ───────────────────────────────────────────────────────

async def get_recommendation(
    profile: dict,
    search_data: dict,
    client: AsyncOpenAI,
) -> dict:
    """
    Full pipeline: profile + Tavily results → structured recommendation dict.
    Returns the recommendation, ready to write to the session file and serve to the dashboard.

    If MOCK_LLM=true, returns MOCK_RESULT immediately — no API call.
    On parse failure: raises ValueError (caller should catch and return 500).
    """
    if MOCK_LLM:
        print("[results_agent] MOCK_LLM=true — returning hardcoded mock result")
        return MOCK_RESULT

    print("[results_agent] Generating recommendation from profile + Tavily data...")
    result = await generate_results(profile, search_data, client)
    print(f"[results_agent] Recommendation: {result.get('recommended_vendor')} "
          f"(regret score: {result.get('regret_score', {}).get('score')})")
    return result