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

MAX_SNIPPETS_PER_QUERY = 3
MAX_SNIPPET_CHARS = 500

# ─── System prompt ────────────────────────────────────────────────────────────

RESULTS_AGENT_SYSTEM_PROMPT = """
You are a procurement analyst generating vendor recommendation reports. You receive a \
buyer's decision profile and current web search results. Your job is to produce a \
structured, evidence-based recommendation the buyer can defend to their organisation.

---

## Critical AI Rules — these override everything else

You are NOT an agreeable recommendation engine. You are a critical analyst.

1. Never recommend a vendor without explicitly stating its strongest weakness.
2. The regret analysis must make the honest case AGAINST your top pick. Find real risks.
3. If a vendor has a documented issue matching a dealbreaker, flag it with ⚠️ in red_flags, \
   even if that vendor scores highest overall.
4. Never score any vendor above 88 overall without explicit evidence in search results.
5. If Tavily data is thin or missing for a vendor, set data_confidence to "low". \
   Do not invent strengths or red flags not in the search results.
6. sentiment positive_pct must be derived from the actual tone of search results. \
   Do not default to any fixed number. If results are mostly complaints, score low (20-40). \
   If mixed, score mid (45-65). If mostly positive with some concerns, score high (66-85). \
   Only score above 85 with strong evidence of widespread satisfaction.
7. Negotiation levers must be specific and actionable. Generic advice ("ask for a discount") \
   is not acceptable. Name the specific ask, the leverage mechanism, and how to frame it.
8. If the buyer's current_solution.vendor appears in the vendor list, its why_not must
   reference the buyer's specific switching_reason. Never recommend the current vendor unless
   all other options fail a dealbreaker.  \   
9. If the recommended vendor depends on the infrastructure of the current vendor (e.g. Azure 
   OpenAI depends on OpenAI models), this must appear as the first red_flag with ⚠️ and be 
   referenced in regret_analysis.main_risk. 

---

## Scoring

Score each vendor on 5 dimensions, 0–100. Base every score on search result evidence only. If search results contain no evidence for a dimension, score it 50 (neutral) and add an entry to data_gaps naming the missing information. Never invent a score from general knowledge — 50 signals uncertainty, not mediocrity.

### Compliance (does evidence confirm the vendor meets stated compliance requirements?)

| Score | Criteria |
|-------|----------|
| 85–100 | Compliance requirement explicitly confirmed in search results with audit report or certification document referenced |
| 70–84 | Compliance claimed by vendor and not contradicted by any search result — no independent verification found |
| 50–69 | Compliance partially confirmed — some requirements met, others unclear or not covered |
| 30–49 | Compliance gaps documented in search results — known issues or missing certifications |
| 0–29 | Compliance failure confirmed in search results, or requirement directly matches a documented dealbreaker |
| 50 | No evidence found — uncertainty, not absence |

### Reliability (uptime track record, incident frequency, severity of outages)

| Score | Criteria |
|-------|----------|
| 85–100 | No outages documented in search results in the past 12 months, or only minor incidents with fast resolution |
| 70–84 | One minor incident documented, or uptime reputation is generally positive with isolated complaints |
| 50–69 | Mixed reliability signals — some incidents documented but not severe or frequent |
| 30–49 | Multiple incidents documented in search results, or one severe outage with significant user impact |
| 0–29 | Pattern of repeated outages documented, or a single catastrophic incident with confirmed business impact on users |
| 50 | No evidence found — uncertainty, not absence |

### Pricing (fit to the user's budget at their stated usage volume)

| Score | Criteria |
|-------|----------|
| 85–100 | Pricing confirmed well within budget with room to spare — no billing surprise patterns in search results |
| 70–84 | Pricing likely within budget based on published rates — minor billing complaint patterns present |
| 50–69 | Pricing unclear or at the edge of budget — billing surprises documented but not dominant complaint |
| 30–49 | Pricing likely to exceed budget, or billing surprise complaints are a dominant pattern in search results |
| 0–29 | Pricing confirmed to exceed budget, or billing chaos/unexpected charges are the primary complaint pattern |
| 50 | No pricing evidence found — uncertainty, not absence |

### Feature fit (coverage of stated must-haves)

| Score | Criteria |
|-------|----------|
| 85–100 | All stated must-haves confirmed covered by evidence in search results |
| 70–84 | Most must-haves covered — one minor gap or unconfirmed must-have |
| 50–69 | Some must-haves covered, others unconfirmed or partially met |
| 30–49 | Multiple must-haves unconfirmed or one significant gap documented |
| 0–29 | A stated must-have is confirmed absent, or a dealbreaker match is documented |
| 50 | No evidence found — uncertainty, not absence |

### Lock-in risk (switching cost — LOWER switching cost = HIGHER score)

| Score | Criteria |
|-------|----------|
| 70–100 | Open standards, portable data formats, no proprietary training or infrastructure dependencies |
| 40–69 | Some proprietary elements but migration is feasible with moderate effort — estimated under 4 weeks |
| 0–39 | Proprietary formats, non-portable fine-tunes, or significant re-engineering required to exit |
| 50 | No evidence found — uncertainty, not absence |

---

## Data quality rules

- Only state something as a fact if it appears in the Tavily data provided.
- sources_used must only contain URLs that appear in the search results — never invent URLs.
- If a vendor's results are empty or low quality, note it in data_gaps and lower confidence.
- Assumptions are things inferred but not confirmed. Log every significant one.

---

## Output format

Output ONLY valid JSON between these exact markers. Nothing before the first marker, \
nothing after the second. No explanation, no preamble.

---BEGIN_RESULTS---
{
  "recommended_vendor": "vendor name",
  "confidence": "high | moderate | low",
  "summary": "Exactly 2 sentences. Sentence 1: why this vendor wins, naming at least one specific evidence-backed strength. Sentence 2: the single biggest risk or caveat, naming the specific concern.",
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
      "strengths": [
        "evidence-backed strength with specific detail",
        "second strength with specific detail"
      ],
      "red_flags": [
        "documented concern — prefix with ⚠️ if it matches a buyer dealbreaker"
      ],
      "why_not": "null for the winner. For losers: one honest sentence on why they lost.",
      "lock_in": {
        "level": "low | medium | high",
        "score": 0,
        "reasons": [
          "specific exit cost #1 — name the actual friction",
          "specific exit cost #2 — name the actual friction"
        ],
        "exit_effort": "one sentence on what switching away would actually involve"
      },
      "sentiment": {
        "positive_pct": 0,
        "label": "Mostly positive | Mixed | Mostly negative",
        "representative_quote": "a real phrase or paraphrase from search results",
        "negative_pattern": "the most common complaint pattern found in search results",
        "flagged_concern": "null, or a one-line concern directly relevant to this buyer's stated priorities"
      },
      "negotiation_levers": [
        {
          "tactic": "short name of the lever",
          "ask": "the specific thing to ask for, verbatim if possible",
          "leverage": "why they have power here — what the vendor wants",
          "how_to_frame": "one sentence on the exact framing to use in the conversation"
        }
      ],
      "first_90_days": "2-3 sentences on what onboarding and early usage actually looks like based on search results. Be honest about rough edges.",
      "data_confidence": "high | medium | low",
      "sources_used": ["https://only-real-urls-from-search-results.com"]
    }
  ],
## Regret score calibration
- 80–100: Strong clear winner, large score gap, all must-haves met — low regret risk
- 60–79: Moderate confidence, some must-have gaps or close race with rank-2
- 40–59: Near-tie between rank-1 and rank-2, or significant unresolved risks
- 0–39: Weak recommendation, multiple unresolved dealbreaker risks, or no clear winner
  "regret_analysis": {
    "score": 0,
    "label": "Low risk | Moderate risk | High risk",
    "vendor": "recommended vendor name",
    "score_gap": 0,
    "score_gap_note": "one sentence on what the gap between rank-1 and rank-2 means — if gap is 5 or less, flag this as a near-tie explicitly",
    "main_risk": "short label for the primary risk, e.g. Rate limit ceiling at growth rate",
    "reasons": [
      "specific risk factor #1 with evidence",
      "specific risk factor #2 with evidence",
      "specific risk factor #3 with evidence"
    ],
    "mitigation": "one concrete thing the buyer can do before committing to reduce regret risk"
  },
  "flip_scenarios": [
    {
      "condition": "If [specific measurable thing changes about the buyer's situation]",
      "then_vendor": "name of vendor that would win instead",
      "because": "one sentence on why that changes the ranking"
    },
    {
      "condition": "If [second specific change]",
      "then_vendor": "name of vendor",
      "because": "reason"
    },
    {
      "condition": "If [third specific change]",
      "then_vendor": "name of vendor",
      "because": "reason"
    }
  ],
  "slider_config": [
    {
      "id": "dimension_id matching a key in dimension_scores e.g. pricing",
      "label": "Human-readable label for the slider e.g. Price sensitivity",
      "dimension": "exact key from dimension_scores: compliance | reliability | pricing | feature_fit | lock_in_risk",
      "default_weight": 0,
      "description": "one sentence on what moving this slider does to the ranking"
    }
  ],
  "assumption_log": [
    {
      "assumption": "what was assumed but not confirmed by search results",
      "impact": "high | medium | low",
      "how_to_verify": "specific action the buyer can take to confirm this"
    }
  ],
  "data_gaps": [
    {
      "vendor": "vendor name",
      "missing": "what information was not found in search results",
      "effect": "how this gap affects confidence in the recommendation"
    }
  ]
}
---END_RESULTS---

## Slider config rules

slider_config must contain 3–4 sliders. Choose dimensions that are most \
contested or sensitive for this specific buyer — not always the same set.

Rules:
- Always include the dimension matching the buyer's priority field as the first slider
- Always include at least one dimension where vendors are closely scored (gap < 15 points)
- default_weight values must sum to exactly 100
- Do not include a dimension as a slider if all vendors score within 10 points of each other — \
  it won't move the ranking and will confuse the user
- label should be buyer-friendly, not technical: \
  "pricing" → "Price sensitivity", "lock_in_risk" → "Avoid lock-in", \
  "feature_fit" → "Feature depth", "compliance" → "Compliance strictness", \
  "reliability" → "Reliability priority"
""".strip()


# ─── Tavily context preparation ───────────────────────────────────────────────

def _prepare_tavily_context(search_data: dict) -> str:
    results = search_data.get("results", [])
    if not results:
        return "No search results available."

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
    tavily_context = _prepare_tavily_context(search_data)

    user_message = (
        "## Decision Profile\n\n"
        + json.dumps(profile, indent=2)
        + "\n\n"
        + tavily_context
    )

    response = await client.chat.completions.create(
        model=os.getenv("MODEL", "anthropic/claude-sonnet-4-5"),
        messages=[
            {"role": "system", "content": RESULTS_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=10000,
        temperature=0.1,
    )

    raw = response.choices[0].message.content.strip()

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
    "confidence": "moderate",
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
                "compliance": 87,
                "reliability": 78,
                "pricing": 70,
                "feature_fit": 85,
                "lock_in_risk": 68
            },
            "strengths": [
                "SOC 2 Type II certified — directly addresses your compliance requirement with documented audit trail",
                "Cleaner API design with fewer proprietary abstractions than OpenAI, reducing future migration overhead"
            ],
            "red_flags": [
                "⚠️ Documented rate limit complaints at high token volumes — risk compounds at 20% monthly growth",
                "Pricing tiers are opaque — enterprise costs are not published and require direct sales negotiation"
            ],
            "why_not": None,
            "lock_in": {
                "level": "medium",
                "score": 55,
                "reasons": [
                    "Prompt engineering tuned to Claude's instruction-following style does not transfer cleanly to other models — expect 2-4 weeks of prompt rework if switching",
                    "No fine-tuning API currently — less lock-in than OpenAI fine-tunes, but Claude-specific system prompt patterns accumulate over time"
                ],
                "exit_effort": "Moderate — prompts need rewriting and output format assumptions need auditing, but no proprietary data formats are involved."
            },
            "sentiment": {
                "positive_pct": 68,
                "label": "Mostly positive",
                "representative_quote": "Output quality is consistently strong; the rate limit behaviour at high volumes is the main frustration",
                "negative_pattern": "Rate limit throttling at scale is the dominant complaint thread, especially for teams growing past 10M tokens/month",
                "flagged_concern": "Rate limit ceiling directly conflicts with your 20% monthly growth — validate enterprise tier capacity in writing before signing"
            },
            "negotiation_levers": [
                {
                    "tactic": "Annual commitment for rate limit tier",
                    "ask": "Ask specifically for a committed throughput SLA with burst capacity guarantees in the contract, not just a tier upgrade",
                    "leverage": "Anthropic needs to show enterprise revenue growth — annual commitments are prioritised for capacity allocation",
                    "how_to_frame": "Tell them your 20% monthly growth means you'll hit standard tier limits within 90 days and you need written capacity guarantees before you can sign"
                },
                {
                    "tactic": "Competitive evaluation pressure",
                    "ask": "Reference that you are actively testing Google Gemini and Mistral in parallel and need their best commercial terms to proceed",
                    "leverage": "Anthropic is actively competing for enterprise accounts and will move on pricing when they believe they might lose the deal",
                    "how_to_frame": "Frame it as a timeline pressure: 'We need to make a decision in two weeks and Gemini has already come back with a reserved capacity offer'"
                },
                {
                    "tactic": "Migration cost offset",
                    "ask": "Ask for $500-1000 in API credits to cover the cost of prompt migration and testing from OpenAI",
                    "leverage": "You are switching from a competitor — the switching cost is real and Anthropic benefits from absorbing it to win the account",
                    "how_to_frame": "Position it as a proof-of-concept budget: 'We need to validate performance at our usage volume before committing — credits let us do that without risk'"
                }
            ],
            "first_90_days": "Onboarding is largely self-serve — documentation is strong and the API is straightforward. Expect 1-2 weeks to migrate and tune prompts from OpenAI. The main early friction is hitting rate limits during load testing before enterprise tier is activated — plan your migration timing around this.",
            "data_confidence": "medium",
            "sources_used": ["https://www.reddit.com/r/ClaudeAI"]
        },
        {
            "name": "OpenAI",
            "rank": 2,
            "overall_score": 74,
            "dimension_scores": {
                "compliance": 82,
                "reliability": 58,
                "pricing": 72,
                "feature_fit": 88,
                "lock_in_risk": 45
            },
            "strengths": [
                "Largest model ecosystem and broadest feature set — widest coverage of edge cases",
                "SOC 2 Type II and GDPR compliance are well-documented with a public trust portal"
            ],
            "red_flags": [
                "⚠️ Multiple documented outages in 2025 (February, July) — directly conflicts with your stated reliability priority",
                "⚠️ Pricing unpredictability is the primary reason you are switching — this pattern is confirmed by other enterprise users"
            ],
            "why_not": "Two documented major outages in 2025 directly conflict with your reliability priority, and pricing unpredictability is the exact pain point driving your switch — this vendor does not solve your problem.",
            "lock_in": {
                "level": "high",
                "score": 32,
                "reasons": [
                    "Proprietary function calling format is not compatible with open standards — any tool-use implementation must be rewritten to switch providers",
                    "Fine-tuned models trained via OpenAI's API are entirely non-portable — the training data and resulting weights cannot be exported"
                ],
                "exit_effort": "High — function calling code, fine-tuned models, and Assistants API implementations all require significant rework to migrate."
            },
            "sentiment": {
                "positive_pct": 52,
                "label": "Mixed",
                "representative_quote": "The model quality is there but the outages and pricing changes have made it hard to rely on for production",
                "negative_pattern": "Outage frequency and rate limit handling are the dominant complaints in 2025 — reliability sentiment has declined from prior years",
                "flagged_concern": "Your switching reason (pricing unpredictability) is one of the top documented complaints from current OpenAI enterprise customers"
            },
            "negotiation_levers": [
                {
                    "tactic": "Churn threat credits",
                    "ask": "If you tell them you are actively evaluating alternatives, they will likely offer 3-6 months of credits to retain you",
                    "leverage": "OpenAI has high churn pressure from Anthropic and Gemini — retention credits are a standard tool their sales team uses",
                    "how_to_frame": "Be direct: 'We are pricing out Anthropic and Gemini right now — what can you offer to make staying the obvious choice?'"
                },
                {
                    "tactic": "SLA with financial penalties",
                    "ask": "Request a written SLA with financial penalties for downtime before signing any annual commitment",
                    "leverage": "Given the 2025 outage record, this is a reasonable ask — if they refuse, that itself is signal",
                    "how_to_frame": "Frame it as standard enterprise due diligence: 'Given the incidents this year, our procurement team requires an SLA with teeth before we can approve annual spend'"
                }
            ],
            "first_90_days": "Onboarding is fast given you are already on the platform. The real risk is the first time you hit a rate limit or outage in production — have a fallback plan ready. Pricing changes have historically come with 30 days notice.",
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
                "compliance": 80,
                "reliability": 70,
                "pricing": 82,
                "feature_fit": 75,
                "lock_in_risk": 60
            },
            "strengths": [
                "Flash-Lite pricing at $0.10/M input tokens is well below your $2k/month budget even at high volume",
                "Google infrastructure delivers strong uptime track record for core API availability"
            ],
            "red_flags": [
                "Enterprise compliance documentation is less established than OpenAI or Anthropic — SOC 2 coverage requires verification",
                "API surface changed significantly in 2024-2025 — stability risk for long-term production integrations"
            ],
            "why_not": "Pricing is the strongest suit, but compliance documentation trail is thinner and API stability concerns make it a higher-risk choice for a production team with SOC 2 requirements.",
            "lock_in": {
                "level": "medium",
                "score": 52,
                "reasons": [
                    "Google has a documented history of deprecating developer products without long-term continuity guarantees (Stadia, Google+, numerous APIs)",
                    "Gemini-specific multimodal and grounding features have no direct equivalent at other providers — any features using them require rearchitecting"
                ],
                "exit_effort": "Moderate — core text API is relatively portable, but any Google-specific features (grounding, Search integration) are not."
            },
            "sentiment": {
                "positive_pct": 61,
                "label": "Mixed",
                "representative_quote": "Pricing is genuinely competitive but the enterprise support experience is inconsistent compared to Anthropic",
                "negative_pattern": "Enterprise support quality and response times are the primary complaints — mixed reports on dedicated account management",
                "flagged_concern": "Compliance documentation depth is below your SOC 2 requirement standard — requires explicit verification before committing"
            },
            "negotiation_levers": [
                {
                    "tactic": "GCP bundle deal",
                    "ask": "Ask for Gemini API costs to be offset against Google Cloud Platform credits — Google bundles these for accounts spending on GCP",
                    "leverage": "Google wants GCP wallet share — Gemini API is a wedge product and they will discount it to grow cloud spend",
                    "how_to_frame": "Ask: 'We are evaluating consolidating on GCP — can you show us what the bundled economics look like at our usage volume?'"
                },
                {
                    "tactic": "Reserved capacity tier",
                    "ask": "Ask for a reserved throughput agreement — Google offers these for enterprise accounts but does not advertise them",
                    "leverage": "You can reference Anthropic's enterprise capacity guarantees as a competing offer",
                    "how_to_frame": "Position as a decision requirement: 'Anthropic has offered us committed throughput SLA — we need something equivalent to consider Google as a production option'"
                }
            ],
            "first_90_days": "API integration is straightforward but enterprise support onboarding can be slow — expect 2-4 weeks to get a named account contact. Compliance documentation requests may take longer than with Anthropic or OpenAI.",
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
                "compliance": 72,
                "reliability": 60,
                "pricing": 68,
                "feature_fit": 62,
                "lock_in_risk": 55
            },
            "strengths": [
                "Best-in-class RAG and embedding capabilities — strong fit if retrieval is a primary use case",
                "Enterprise compliance focus with dedicated documentation and support"
            ],
            "red_flags": [
                "⚠️ Significantly smaller ecosystem — community support and third-party integrations are limited compared to top-tier providers",
                "General-purpose model capability lags OpenAI and Anthropic for non-RAG tasks"
            ],
            "why_not": "Cohere is well-suited to enterprise RAG use cases, but for general API usage your team would take on meaningful migration effort for a vendor with a smaller support ecosystem and lower general capability ceiling.",
            "lock_in": {
                "level": "medium",
                "score": 48,
                "reasons": [
                    "Proprietary embedding models are not interchangeable with other providers — any search or retrieval infrastructure built on Cohere embeddings requires re-indexing to switch",
                    "Smaller ecosystem means fewer community-maintained libraries and integrations — more custom code required which increases switching cost over time"
                ],
                "exit_effort": "Moderate to high for RAG use cases — embedding indexes must be rebuilt. For pure completion use cases, migration is standard effort."
            },
            "sentiment": {
                "positive_pct": 58,
                "label": "Mixed",
                "representative_quote": "Excellent for enterprise RAG but the general completions feel like a step behind the bigger players",
                "negative_pattern": "Capability gap versus OpenAI and Anthropic on general tasks is the dominant criticism — users who chose for RAG are satisfied, general users less so",
                "flagged_concern": "Smaller support ecosystem means slower resolution times if you hit edge cases during your growth phase"
            },
            "negotiation_levers": [
                {
                    "tactic": "Proof of concept credits",
                    "ask": "Cohere is aggressive on enterprise deals — ask for a 90-day proof-of-concept period with full credits before any commitment",
                    "leverage": "They are competing hard against larger providers and will absorb POC costs to win enterprise accounts",
                    "how_to_frame": "Ask: 'We need to validate performance at production scale before we can justify switching — can you support a 90-day funded POC?'"
                }
            ],
            "first_90_days": "Onboarding support is hands-on — they typically assign a solutions engineer for enterprise accounts. Expect the integration to take longer than OpenAI due to less community documentation and fewer examples.",
            "data_confidence": "low",
            "sources_used": []
        },
        {
            "name": "Mistral",
            "rank": 5,
            "overall_score": 54,
            "dimension_scores": {
                "compliance": 60,
                "reliability": 58,
                "pricing": 75,
                "feature_fit": 58,
                "lock_in_risk": 78
            },
            "strengths": [
                "Open-weight models eliminate vendor dependency entirely — self-hosting option gives full control",
                "Competitive token pricing with the lowest lock-in risk of any vendor evaluated"
            ],
            "red_flags": [
                "⚠️ SOC 2 compliance documentation for cloud API is not clearly established — direct dealbreaker given your requirement",
                "Smaller infrastructure team than hyperscale competitors — reliability at enterprise scale is less proven"
            ],
            "why_not": "Mistral's open-weight model is compelling for lock-in avoidance, but unconfirmed SOC 2 status is a direct dealbreaker match given your compliance requirement.",
            "lock_in": {
                "level": "low",
                "score": 78,
                "reasons": [
                    "Open-weight models can be downloaded and self-hosted — no vendor dependency if you choose to move",
                    "API format follows open standards — switching to a different provider requires minimal code changes"
                ],
                "exit_effort": "Low — open-weight models are portable and the API design minimises vendor-specific patterns."
            },
            "sentiment": {
                "positive_pct": 55,
                "label": "Mixed",
                "representative_quote": "Great for teams who want to avoid lock-in but enterprise readiness is not there yet",
                "negative_pattern": "Enterprise readiness gaps (compliance, support SLAs, reliability guarantees) are the consistent criticism from larger teams",
                "flagged_concern": "SOC 2 compliance status for cloud API is unconfirmed — this is a direct dealbreaker given your stated compliance requirement"
            },
            "negotiation_levers": [
                {
                    "tactic": "Self-hosting leverage",
                    "ask": "Use the self-hosting option as negotiating leverage even if you do not plan to self-host — it is a credible outside option",
                    "leverage": "If you can self-host, Mistral's cloud offering has no captive audience — they must compete on value",
                    "how_to_frame": "Tell them: 'We are evaluating cloud versus self-hosted for cost and compliance reasons — what would make cloud the obvious choice?'"
                }
            ],
            "first_90_days": "Self-hosted setup requires 2-4 weeks of infrastructure work. Cloud API onboarding is fast but enterprise support is limited. Compliance documentation requests may go unanswered or take weeks.",
            "data_confidence": "low",
            "sources_used": []
        }
    ],
    "regret_analysis": {
        "score": 6,
        "label": "Moderate risk",
        "vendor": "Anthropic",
        "score_gap": 7,
        "score_gap_note": "Anthropic leads OpenAI by 7 points overall, but this gap narrows significantly on features (85 vs 88) — OpenAI outperforms on raw capability, Anthropic wins on reliability and compliance.",
        "main_risk": "Rate limit ceiling at 20% monthly growth",
        "reasons": [
            "Documented rate limit complaints at high token volumes are the most consistent negative signal in Anthropic community forums — at 20% monthly growth you will likely hit enterprise tier thresholds within 3-4 months",
            "Enterprise rate limit tiers and burst capacity guarantees are not published — you are committing without knowing the ceiling, which creates the same pricing unpredictability you are switching away from OpenAI to avoid",
            "If Anthropic cannot provide committed capacity in writing, you may face an urgent mid-growth migration with Claude-optimised prompts that do not transfer cleanly to other providers"
        ],
        "mitigation": "Before signing, request a written enterprise throughput SLA with specific burst capacity guarantees — if they cannot provide it, treat the risk as high and reconsider OpenAI with a reliability SLA instead."
    },
    "flip_scenarios": [
        {
            "condition": "If your monthly growth rate drops below 5% or usage stabilises",
            "then_vendor": "OpenAI",
            "because": "Rate limit risk disappears at stable volume and OpenAI's broader feature set becomes the differentiating factor"
        },
        {
            "condition": "If SOC 2 compliance requirement is removed or downgraded",
            "then_vendor": "Mistral",
            "because": "Lock-in risk becomes the dominant factor and Mistral's open-weight model is the strongest answer to that concern"
        },
        {
            "condition": "If budget increases above $4k/month and GCP consolidation is on the roadmap",
            "then_vendor": "Google Gemini",
            "because": "Bundled GCP pricing makes Gemini significantly cheaper at scale and compliance documentation gaps become manageable with dedicated account support"
        }
    ],
    "slider_config": [
        {
            "id": "reliability",
            "label": "Reliability priority",
            "dimension": "reliability",
            "default_weight": 40,
            "description": "Increasing this favours vendors with stronger uptime records — pushes OpenAI down due to 2025 outages"
        },
        {
            "id": "compliance",
            "label": "Compliance strictness",
            "dimension": "compliance",
            "default_weight": 30,
            "description": "Increasing this favours vendors with stronger SOC 2 documentation — eliminates Mistral at high values"
        },
        {
            "id": "feature_fit",
            "label": "Feature depth",
            "dimension": "feature_fit",
            "default_weight": 20,
            "description": "Increasing this narrows the gap between Anthropic and OpenAI — OpenAI leads on raw feature breadth"
        },
        {
            "id": "lock_in_risk",
            "label": "Avoid lock-in",
            "dimension": "lock_in_risk",
            "default_weight": 10,
            "description": "Increasing this significantly boosts Mistral and penalises OpenAI — most impactful slider for lock-in-sensitive buyers"
        }
    ],
    "assumption_log": [
        {
            "assumption": "Anthropic's SOC 2 Type II certification covers your specific data processing use case and jurisdiction",
            "impact": "high",
            "how_to_verify": "Request the full SOC 2 report from trust.anthropic.com and share with your compliance team before signing"
        },
        {
            "assumption": "Your usage estimate is accurate — actual token consumption may be significantly higher once integrated at scale",
            "impact": "medium",
            "how_to_verify": "Pull actual token logs from your current OpenAI usage dashboard and calculate a 6-month projection before finalising budget"
        },
        {
            "assumption": "Anthropic can provide enterprise rate limit tiers sufficient for your growth trajectory",
            "impact": "high",
            "how_to_verify": "Ask Anthropic sales directly: 'What is the committed throughput limit at enterprise tier and what is the burst capacity policy?'"
        }
    ],
    "data_gaps": [
        {
            "vendor": "Anthropic",
            "missing": "Specific enterprise rate limit tiers, burst capacity guarantees, and published SLA terms",
            "effect": "Cannot confirm whether Anthropic can support your growth trajectory without throttling — this is the primary unresolved risk"
        },
        {
            "vendor": "Cohere",
            "missing": "Recent user reliability reports and pricing at 50M+ token monthly scale",
            "effect": "Cohere's ranking is lower confidence — could be under-ranked if reliability has improved in 2025"
        },
        {
            "vendor": "Mistral",
            "missing": "SOC 2 compliance certification status for cloud API — confirmed presence or absence would change the ranking",
            "effect": "Mistral may be eliminated entirely if SOC 2 is confirmed absent, or jump significantly if confirmed present — verify before dismissing"
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
          f"(regret score: {result.get('regret_analysis', {}).get('score')})")
    return result