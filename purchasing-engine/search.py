from concurrent.futures import ThreadPoolExecutor
from tavily import TavilyClient
from dotenv import load_dotenv
import os
import json

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

async def run_searches(decision_profile: dict, vendors: list) -> dict:
    from query_builder import build_queries

    queries_per_vendor = await build_queries(decision_profile, vendors)

    def research_vendor(name):
        queries = queries_per_vendor.get(name, [])
        if len(queries) < 3:
            category = decision_profile.get("category", "software")
            queries = [
                f"{name} {category} problems complaints 2026",
                f"{name} pricing hidden costs billing issues 2026",
                f"{name} {category} lock-in switching difficulty 2026"
            ]

        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                f1 = executor.submit(tavily.search, queries[0], )
                f2 = executor.submit(tavily.search, queries[1])
                f3 = executor.submit(tavily.search, queries[2])

                return {
                    "name": name,
                    "complaints": f1.result().get("results", []),
                    "pricing": f2.result().get("results", []),
                    "slot3": f3.result().get("results", [])
                }
        except Exception as e:
            print(f"Error researching {name}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(research_vendor, vendors))

    vendors_raw = [r for r in results if r is not None]

    flattened = []
    for vendor in vendors_raw:
        name = vendor["name"]
        for cat in ("complaints", "pricing", "slot3"):
            flattened.append({
                "vendor": name,
                "category": cat,
                "query": "",
                "results": vendor.get(cat, []),
            })

    return {
        "category": decision_profile.get("category", ""),
        "decision_profile": decision_profile,
        "vendors_raw": vendors_raw,
        "results": flattened,
    }

def identify_vendors(decision_profile: dict) -> list:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )

    category = decision_profile.get("category", "")
    must_haves = decision_profile.get("must_haves", [])
    budget = decision_profile.get("budget", {})

    try:
        response = client.chat.completions.create(
            model=os.getenv("MODEL"),
            messages=[
                {
                    "role": "user",
                    "content": f"""List the top 4 vendors for this buyer.

Category: {category}
Must-haves: {must_haves}
Budget: {budget}

Return ONLY a JSON array of vendor names, nothing else.
Example: ["Vendor A", "Vendor B", "Vendor C", "Vendor D"]"""
                }
            ]
        )
        import re
        text = response.choices[0].message.content
        match = re.search(r'\[[\s\S]*?\]', text)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"Error identifying vendors: {e}")
    return []