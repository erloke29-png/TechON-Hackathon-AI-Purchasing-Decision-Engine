# TechON-Hackathon-AI-Purchasing-Decision-Engine

An AI-powered vendor evaluation tool that turns messy procurement research
into a clear, defensible recommendation. Built for [hackathon name].

## What it does

- Runs a conversational interview to understand your requirements, budget,
  and constraints
- Detects contradictions in your answers and flags them once (then moves on)
- Generates a results dashboard with a scored vendor comparison, lock-in
  danger ratings, regret score, customer review sentiment, and negotiation levers
- Live sliders let you stress-test assumptions and watch the recommendation
  update in real time

Currently seeded for **AI API providers**: OpenAI, Anthropic, Gemini,
Cohere, and Mistral.

## Tech stack

- **Backend**: Python + FastAPI
- **Frontend**: Vanilla HTML, CSS, JavaScript
- **AI**: Anthropic Claude API (claude-sonnet-4-20250514)
- **Data**: Static JSON files (no database)
- **Deploy**: Render.com

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/your-username/purchasing-engine
cd purchasing-engine
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Add your API key**

Open `.env` and replace the placeholder:

Get a key at https://console.anthropic.com


**4. Run locally**
```bash
uvicorn main:app --reload
```

Open http://localhost:8000 in your browser.

## Project structure

purchasing-engine/
├── main.py                    # FastAPI app — all routes
├── requirements.txt
├── .env                       # API key (never commit this)
├── static/
│   ├── chat.html              # Phase 1 — interview UI
│   ├── dashboard.html         # Phase 2 — results dashboard
│   ├── style.css              # Shared styles
│   ├── chat.js                # Interview stream handler
│   ├── dashboard.js           # Dashboard render logic
│   └── scorer.js              # Scoring, regret score, expiry
├── data/
│   ├── vendors.json           # Pre-seeded vendor data
│   ├── contradiction_rules.json
│   └── sessions/              # Per-user decision profiles (auto-created)
└── prompts/
└── interviewer.txt        # Claude system prompt for Phase 1


## Deploying to Render

1. Push your code to GitHub (make sure `.env` is in `.gitignore`)
2. Go to https://render.com and click **New Web Service**
3. Connect your GitHub repo
4. Set the following:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Under **Environment Variables**, add `ANTHROPIC_API_KEY` with your key
6. Click **Deploy** — live in ~3 minutes

## Team

| Person | Owns |
|--------|------|
| [Name] | Chat interview + decision profile JSON |
| [Name] | Results dashboard + comparison table |
| [Name] | Live sliders + decision expiry trigger |
| [Name] | Risk panel + lock-in ratings + regret score + sentiment |

## Demo scenario

*"VP of Engineering evaluating AI API providers for a team of 8,
$2k/month budget, 20% monthly growth, SOC 2 required."*
