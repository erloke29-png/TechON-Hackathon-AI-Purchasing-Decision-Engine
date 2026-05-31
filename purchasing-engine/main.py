from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI, OpenAI
from dotenv import load_dotenv
import os
import json
import uuid
import datetime

from search import identify_vendors, run_searches
from result_agent import get_recommendation

load_dotenv()

app = FastAPI()

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

templates = Jinja2Templates(directory="Frontend")

with open("prompts/decisio.txt", "r") as f:
    SYSTEM_PROMPT = f.read()

app.mount("/static", StaticFiles(directory="Frontend"), name="Frontend")

def adapt_result_to_session(result: dict, profile: dict) -> dict:
    vendors = result.get("vendors", [])
    winner_name = result.get("recommended_vendor", "")
    regret = result.get("regret_score", {})

    adapted_vendors = []
    for v in vendors:
        ds = v.get("dimension_scores", {})
        lock_level = v.get("lock_in_danger", "medium")
        adapted_vendors.append({
            "id": v.get("name", "").lower().replace(" ", "_"),
            "name": v.get("name", ""),
            "tagline": v.get("sentiment_summary", ""),
            "pricing": {
                "model": "usage-based",
                "monthly_estimate_usd": 0,
                "notes": ""
            },
            "scores": {
                "budget":          ds.get("pricing", 0),
                "budget_note":     "",
                "features":        ds.get("feature_fit", 0),
                "features_note":   "",
                "compliance":      ds.get("compliance", 0),
                "compliance_note": "",
                "growth":          ds.get("reliability", 0),
                "growth_note":     ""
            },
            "overall_score": v.get("overall_score", 0),
            "regret": {
                "score":    regret.get("score", 0),
                "label":    "Moderate risk",
                "based_on": "Tavily search results",
                "reasons":  v.get("red_flags", [])
            },
            "lockin": {
                "level":       lock_level,
                "score":       {"low": 25, "medium": 55, "high": 85}.get(lock_level, 55),
                "explanation": " ".join(v.get("lock_in_reasons", []))
            },
            "sentiment": {
                "positive_pct":         70,
                "representative_quote": v.get("sentiment_summary", ""),
                "negative_pattern":     v.get("red_flags", [""])[0] if v.get("red_flags") else ""
            },
            "negotiation_levers": [
                {"tactic": lev, "detail": ""} for lev in v.get("negotiation_levers", [])
            ],
            "why_not": v.get("why_not")
        })

    business = profile.get("business_context", {})
    now = datetime.datetime.utcnow()

    return {
        "created_at": now.isoformat() + "Z",
        "expires_recommendation_at": (now + datetime.timedelta(days=90)).isoformat() + "Z",
        "profile": {
            "category":                profile.get("category", ""),
            "role":                    profile.get("context", {}).get("role", "Decision maker"),
            "team_size":               business.get("team_size", 1),
            "budget_monthly_usd":      profile.get("budget", {}).get("amount", 0),
            "growth_rate_monthly_pct": 0,
            "contract_preference":     business.get("contract_preference", "monthly"),
            "priority":                profile.get("priority", "value"),
            "must_haves":              profile.get("must_haves", []),
            "dealbreakers":            profile.get("dealbreakers", [])
        },
        "recommendation": {
            "winner":         winner_name,
            "confidence":     "moderate",
            "summary":        result.get("summary", ""),
            "expiry_reason":  "",
            "flip_scenarios": []
        },
        "vendors": adapted_vendors
    }

@app.get("/")
def root(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])

    messages_with_system = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ] + messages

    def stream():
        sync_client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1"
        )
        response = sync_client.chat.completions.create(
            model=os.getenv("MODEL"),
            messages=messages_with_system,
            stream=True
        )
        for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    return StreamingResponse(stream(), media_type="text/plain")

@app.get("/dashboard")
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.post("/api/session")
async def save_session(request: Request):
    try:
        data = await request.json()
        session_id = str(uuid.uuid4())
        os.makedirs("data/sessions", exist_ok=True)

        vendors = identify_vendors(data)
        if not vendors:
            return JSONResponse({"error": "Could not identify vendors"}, status_code=400)

        search_data = await run_searches(data, vendors)
        result = await get_recommendation(data, search_data, client)

        session = adapt_result_to_session(result, data)
        session["session_id"] = session_id

        with open(f"data/sessions/{session_id}.json", "w") as f:
            json.dump(session, f)

        return JSONResponse({"session_id": session_id})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    session_path = f"data/sessions/{session_id}.json"

    if not os.path.exists(session_path):
        return JSONResponse({"error": "Session not found"}, status_code=404)

    with open(session_path, "r") as f:
        data = json.load(f)

    return JSONResponse(data)