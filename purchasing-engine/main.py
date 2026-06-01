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
import asyncio
from typing import Dict

from search import identify_vendors, run_searches
from result_agent import get_recommendation

load_dotenv()

processing_jobs: Dict[str, dict] = {}

app = FastAPI()

client = AsyncOpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

templates = Jinja2Templates(directory="Frontend")

with open("prompts/decisio.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

app.mount("/Frontend", StaticFiles(directory="Frontend"), name="Frontend")

def adapt_result_to_session(result: dict, profile: dict) -> dict:
    vendors = result.get("vendors", [])
    winner_name = result.get("recommended_vendor", "")
    regret = result.get("regret_analysis", {})
    flip_scenarios = result.get("flip_scenarios", [])
    slider_config = result.get("slider_config", [])

    adapted_vendors = []
    for v in vendors:
        ds = v.get("dimension_scores", {})
        lock = v.get("lock_in", {})
        lock_level = lock.get("level", "medium")
        sentiment = v.get("sentiment", {})
        levers = v.get("negotiation_levers", [])

        adapted_vendors.append({
            "id": v.get("name", "").lower().replace(" ", "_"),
            "name": v.get("name", ""),
            "tagline": sentiment.get("representative_quote", ""),
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
            "dimension_scores": ds,
            "overall_score": v.get("overall_score", 0),
            "strengths": v.get("strengths", []),
            "red_flags": v.get("red_flags", []),
            "first_90_days": v.get("first_90_days", ""),
            "regret": {
                "score":    regret.get("score", 0),
                "label":    regret.get("label", "Moderate risk"),
                "based_on": "Tavily search results",
                "reasons":  regret.get("reasons", [])
            },
            "lockin": {
                "level":       lock_level,
                "score":       lock.get("score", {"low": 25, "medium": 55, "high": 85}.get(lock_level, 55)),
                "explanation": lock.get("exit_effort", ""),
                "reasons":     lock.get("reasons", [])
            },
            "sentiment": {
                "positive_pct":         sentiment.get("positive_pct", 0),
                "label":                sentiment.get("label", ""),
                "representative_quote": sentiment.get("representative_quote", ""),
                "negative_pattern":     sentiment.get("negative_pattern", ""),
                "flagged_concern":      sentiment.get("flagged_concern", "")
            },
            "negotiation_levers": [
                {
                    "tactic":       lev.get("tactic", ""),
                    "detail":       lev.get("ask", ""),
                    "leverage":     lev.get("leverage", ""),
                    "how_to_frame": lev.get("how_to_frame", "")
                } for lev in levers
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
            "dealbreakers":            profile.get("dealbreakers", []),
            "preferred_vendor":        profile.get("search_signals", {}).get("preferred_vendor", None),
            "current_stack":           profile.get("search_signals", {}).get("current_stack", []),
            "roi_timeline":            profile.get("search_signals", {}).get("roi_timeline", None),
        },
        "recommendation": {
            "winner":         winner_name,
            "confidence":     result.get("confidence", "moderate"),
            "summary":        result.get("summary", ""),
            "expiry_reason":  "",
            "flip_scenarios": [
                {
                    "condition":   s.get("condition", ""),
                    "outcome":     s.get("because", ""),
                    "then_vendor": s.get("then_vendor", "")
                } for s in flip_scenarios
            ]
        },
        "regret_analysis": regret,
        "slider_config": slider_config,
        "assumption_log": result.get("assumption_log", []),
        "data_gaps": result.get("data_gaps", []),
        "vendors": adapted_vendors
    }

async def run_pipeline(session_id: str, data: dict):
    try:
        vendors = identify_vendors(data)
        if not vendors:
            processing_jobs[session_id] = {"status": "error", "error": "Could not identify vendors"}
            return

        search_data = await run_searches(data, vendors)
        result = await get_recommendation(data, search_data, client)

        session = adapt_result_to_session(result, data)
        session["session_id"] = session_id
        session["chat_history"] = data.get("chat_history", [])

        with open(f"data/sessions/{session_id}.json", "w") as f:
            json.dump(session, f)

        processing_jobs.pop(session_id, None)

    except Exception as e:
        import traceback
        traceback.print_exc()
        processing_jobs[session_id] = {"status": "error", "error": str(e)}

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
        session["chat_history"] = data.get("chat_history", [])

        with open(f"data/sessions/{session_id}.json", "w") as f:
            json.dump(session, f)

        return JSONResponse({"session_id": session_id})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/session/start")
async def start_session(request: Request):
    try:
        data = await request.json()
        session_id = str(uuid.uuid4())
        os.makedirs("data/sessions", exist_ok=True)
        processing_jobs[session_id] = {"status": "processing"}
        asyncio.create_task(run_pipeline(session_id, data))
        return JSONResponse({"session_id": session_id})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/session/{session_id}/status")
def get_session_status(session_id: str):
    session_path = f"data/sessions/{session_id}.json"
    if os.path.exists(session_path):
        return JSONResponse({"status": "complete", "session_id": session_id})
    if session_id in processing_jobs:
        job = processing_jobs[session_id]
        if job.get("status") == "error":
            return JSONResponse({"status": "error", "error": job.get("error", "Unknown error")})
        return JSONResponse({"status": "processing"})
    return JSONResponse({"status": "not_found"}, status_code=404)

@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    session_path = f"data/sessions/{session_id}.json"

    if not os.path.exists(session_path):
        return JSONResponse({"error": "Session not found"}, status_code=404)

    with open(session_path, "r") as f:
        data = json.load(f)

    return JSONResponse(data)

@app.get("/api/history")
def get_history():
    sessions_dir = "data/sessions"
    sessions = []
    
    if not os.path.exists(sessions_dir):
        return JSONResponse([])
    
    for filename in os.listdir(sessions_dir):
        if filename.endswith(".json"):
            try:
                with open(f"{sessions_dir}/{filename}", "r") as f:
                    data = json.load(f)
                    sessions.append({
                        "session_id": data.get("session_id", ""),
                        "created_at": data.get("created_at", ""),
                        "category": data.get("profile", {}).get("category", "Unknown"),
                        "winner": data.get("recommendation", {}).get("winner", "Unknown")
                    })
            except:
                continue
    
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return JSONResponse(sessions)

@app.delete("/api/session/{session_id}")
def delete_session(session_id: str):
    session_path = f"data/sessions/{session_id}.json"
    if os.path.exists(session_path):
        os.remove(session_path)
        return JSONResponse({"deleted": True})
    return JSONResponse({"error": "Session not found"}, status_code=404)