from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import re

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

def safe_json_parse(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None

with open("prompts/report_agent_prompt.txt", "r") as f:
    REPORT_AGENT_PROMPT = f.read()

def generate_session(tavily_json: dict) -> dict:
    decision_profile = tavily_json.get("decision_profile", {})
    vendors_raw = tavily_json.get("vendors_raw", [])
    category = tavily_json.get("category", "")

    response = client.chat.completions.create(
        model=os.getenv("MODEL"),
        messages=[
            {
                "role": "system",
                "content": REPORT_AGENT_PROMPT
            },
            {
                "role": "user",
                "content": f"""You are a procurement analyst. Based on the research data and buyer profile below, generate a complete vendor recommendation report.

Category: {category}

Buyer profile:
{json.dumps(decision_profile, indent=2)}

Vendor research data:
{json.dumps(vendors_raw, indent=2)}

Generate a complete SESSION object that matches this exact structure. Be honest, critical, and specific to this buyer. Do not favour any vendor. Base everything on the research data.

Return ONLY this JSON object, nothing else:
{{
  "session_id": "generated",
  "created_at": "{__import__('datetime').datetime.utcnow().isoformat()}Z",
  "expires_recommendation_at": "{(__import__('datetime').datetime.utcnow() + __import__('datetime').timedelta(days=90)).isoformat()}Z",
  "profile": {{
    "category": "{category}",
    "role": "{decision_profile.get('context', {}).get('role', 'Decision maker')}",
    "team_size": {decision_profile.get('team_size') or decision_profile.get('business_context', {}).get('team_size') or 1},
    "budget_monthly_usd": {decision_profile.get('budget', {}).get('amount') or 0},
    "growth_rate_monthly_pct": 0,
    "contract_preference": "{decision_profile.get('contract_preference', 'monthly')}",
    "priority": "{decision_profile.get('priority', 'value')}",
    "must_haves": {json.dumps(decision_profile.get('must_haves', []))},
    "dealbreakers": {json.dumps(decision_profile.get('dealbreakers', []))}
  }},
  "recommendation": {{
    "winner": "name of best vendor for this buyer",
    "confidence": "high or moderate or low",
    "summary": "2-3 sentence honest summary of why this vendor wins and what the key caveat is",
    "expiry_reason": "one sentence about when and why to re-evaluate",
    "flip_scenarios": [
      {{"condition": "If [something changes]", "outcome": "Then [different vendor] becomes better because [reason]"}},
      {{"condition": "If [something changes]", "outcome": "Then [different vendor] becomes better because [reason]"}},
      {{"condition": "If [something changes]", "outcome": "Then [different vendor] becomes better because [reason]"}}
    ]
  }},
  "vendors": [
    {{
      "id": "vendor_id_lowercase",
      "name": "Vendor Name",
      "tagline": "one sentence description",
      "pricing": {{
        "model": "per-seat or flat or usage-based",
        "monthly_estimate_usd": 0,
        "notes": "pricing details and gotchas"
      }},
      "scores": {{
        "budget": 0,
        "budget_note": "explanation",
        "features": 0,
        "features_note": "explanation",
        "compliance": 0,
        "compliance_note": "explanation",
        "growth": 0,
        "growth_note": "explanation"
      }},
      "overall_score": 0,
      "regret": {{
        "score": 0.0,
        "label": "Low risk or Moderate risk or High risk",
        "based_on": "source of reviews",
        "reasons": ["reason 1", "reason 2", "reason 3"]
      }},
      "lockin": {{
        "level": "low or medium or high",
        "score": 0,
        "explanation": "what makes it hard or easy to leave"
      }},
      "sentiment": {{
        "positive_pct": 0,
        "representative_quote": "real quote from research",
        "negative_pattern": "most common complaint"
      }},
      "negotiation_levers": [
        {{"tactic": "tactic name", "detail": "specific actionable advice"}}
      ],
      "why_not": "one sentence why this vendor lost, or null if winner"
    }}
  ]
}}"""
            }
        ]
    )

    result = safe_json_parse(response.choices[0].message.content)
    if result:
        return result
    return {}