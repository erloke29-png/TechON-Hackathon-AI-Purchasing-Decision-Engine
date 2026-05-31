from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from dotenv import load_dotenv
from search import search_vendors
import os
import json
import uuid

load_dotenv()

app = FastAPI()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

templates = Jinja2Templates(directory="static")

with open("prompts/system_prompt.txt", "r") as f:
    SYSTEM_PROMPT = f.read()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.post("/api/chat")
async def chat(request: dict):
    messages = request.get("messages", [])
    
    messages_with_system = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ] + messages

    def stream():
        response = client.chat.completions.create(
            model="perplexity/llama-3.1-sonar-large-128k-online",
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
    data = await request.json()
    session_id = str(uuid.uuid4())
    session_path = f"data/sessions/{session_id}.json"
    
    os.makedirs("data/sessions", exist_ok=True)
    
    from search import search_vendors
    vendors = search_vendors(data.get("category", ""), data)
    data["vendors"] = vendors
    
    with open(session_path, "w") as f:
        json.dump(data, f)
    
    return JSONResponse({"session_id": session_id})

@app.get("/api/session/{session_id}")
def get_session(session_id: str):
    session_path = f"data/sessions/{session_id}.json"
    
    if not os.path.exists(session_path):
        return JSONResponse({"error": "Session not found"}, status_code=404)
    
    with open(session_path, "r") as f:
        data = json.load(f)
    
    return JSONResponse(data)