from concurrent.futures import ThreadPoolExecutor
from tavily import TavilyClient
from dotenv import load_dotenv
import os
import json

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def run_searches(decision_profile: dict) -> dict:
    queries = decision_profile.get("search_queries", {})
    category = decision_profile.get("category", "")

    # fallback queries if chat agent didn't generate them
    if not queries or not queries.get("find_vendors"):
        queries = {
            "find_vendors": f"top {category} vendors 2025 comparison",
            "pricing": f"{category} pricing plans cost 2025",
            "complaints": f"{category} problems complaints negative reviews",
            "lock_in": f"{category} hidden costs lock-in switching difficulty",
            "reviews": f"{category} honest review 2025 worth it",
            "tco": f"{category} total cost of ownership real price"
        }

    # Step 1 – find vendor names
    try:
        vendor_search = tavily.search(
            query=queries["find_vendors"],
            max_results=5,
            include_raw_content=True
        )
    except Exception as e:
        print(f"Tavily vendor search failed: {e}")
        return {}

    # Step 2 – research each vendor in parallel
    vendor_names = extract_vendor_names(vendor_search, category)

    def research_vendor(name):
        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                fp = executor.submit(tavily.search, f"{name} {queries['pricing']}", )
                fc = executor.submit(tavily.search, f"{name} {queries['complaints']}")
                fl = executor.submit(tavily.search, f"{name} {queries['lock_in']}")
                fr = executor.submit(tavily.search, f"{name} {queries['reviews']}")
                ft = executor.submit(tavily.search, f"{name} {queries['tco']}")

                return {
                    "name": name,
                    "pricing": fp.result().get("results", []),
                    "complaints": fc.result().get("results", []),
                    "lock_in": fl.result().get("results", []),
                    "reviews": fr.result().get("results", []),
                    "tco": ft.result().get("results", [])
                }
        except Exception as e:
            print(f"Error researching {name}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(research_vendor, vendor_names))

    vendors_raw = [r for r in results if r is not None]

    return {
        "category": category,
        "decision_profile": decision_profile,
        "vendors_raw": vendors_raw
    }

def extract_vendor_names(search_result: dict, category: str) -> list:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    try:
        response = client.chat.completions.create(
            model=os.getenv("MODEL"),
            messages=[
                {
                    "role": "user",
                    "content": f"""From these search results, extract exactly 4 vendor or product names for the category '{category}'.
Return ONLY a JSON array of names, nothing else. Example: ["Vendor A", "Vendor B", "Vendor C", "Vendor D"]

Search results:
{json.dumps(search_result.get('results', []))}"""
                }
            ]
        )
        import re
        text = response.choices[0].message.content
        match = re.search(r'\[[\s\S]*?\]', text)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"Error extracting vendor names: {e}")
    return []