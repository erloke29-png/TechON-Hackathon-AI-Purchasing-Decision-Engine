from concurrent.futures import ThreadPoolExecutor
from tavily import TavilyClient
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import re

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

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

def generate_queries(category: str, decision_profile: dict) -> dict:
    try:
        response = client.chat.completions.create(
            model="perplexity/llama-3.1-sonar-large-128k-online",
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a procurement research assistant. Based on this decision profile, generate specific search queries to find the best vendors.

Decision profile:
{json.dumps(decision_profile, indent=2)}

Generate search queries specific to this user's situation. Use their budget, location, dealbreakers, and must-haves to make queries precise.

Return ONLY a JSON object with these exact keys, nothing else:
{{
  "find_vendors": "query to find top vendors for this specific use case",
  "pricing": "query to find pricing matching their budget",
  "complaints": "query to find real user complaints relevant to their use case",
  "lock_in": "query to find lock-in and switching costs",
  "reviews": "query to find honest reviews from similar buyers",
  "tco": "query to find total cost of ownership for their team size"
}}"""
                }
            ]
        )
        result = safe_json_parse(response.choices[0].message.content)
        if result:
            return result
    except Exception as e:
        print(f"Error generating queries: {e}")
    
    return {
        "find_vendors": f"top {category} vendors 2025 comparison",
        "pricing": f"{category} pricing plans cost 2025",
        "complaints": f"{category} problems complaints negative reviews",
        "lock_in": f"{category} hidden costs lock-in switching difficulty",
        "reviews": f"{category} honest review 2025 worth it",
        "tco": f"{category} total cost of ownership real price"
    }

def search_vendors(category: str, decision_profile: dict) -> list:
    queries = generate_queries(category, decision_profile)

    try:
        top_vendors_result = tavily.search(
            query=queries["find_vendors"],
            max_results=5
        )
    except Exception as e:
        print(f"Tavily search failed: {e}")
        return []

    try:
        vendor_names_response = client.chat.completions.create(
            model="perplexity/llama-3.1-sonar-large-128k-online",
            messages=[
                {
                    "role": "user",
                    "content": f"""From these search results, extract exactly 4 vendor or product names for the category '{category}'.
Return ONLY a JSON array of names, nothing else. Example: ["Vendor A", "Vendor B", "Vendor C", "Vendor D"]

Search results:
{json.dumps(top_vendors_result['results'])}"""
                }
            ]
        )
        vendor_names = safe_json_parse(vendor_names_response.choices[0].message.content)
        if not vendor_names:
            return []
    except Exception as e:
        print(f"Error extracting vendor names: {e}")
        return []

    def research_vendor(name):
        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_pricing    = executor.submit(tavily.search, f"{name} {queries['pricing']}", )
                future_complaints = executor.submit(tavily.search, f"{name} {queries['complaints']}")
                future_lockin     = executor.submit(tavily.search, f"{name} {queries['lock_in']}")
                future_reviews    = executor.submit(tavily.search, f"{name} {queries['reviews']}")
                future_tco        = executor.submit(tavily.search, f"{name} {queries['tco']}")

                pricing    = future_pricing.result()
                complaints = future_complaints.result()
                lockin     = future_lockin.result()
                reviews    = future_reviews.result()
                tco        = future_tco.result()

            synthesis = client.chat.completions.create(
                model="perplexity/llama-3.1-sonar-large-128k-online",
                messages=[
                    {
                        "role": "user",
                        "content": f"""Based on these search results about {name}, create a structured vendor profile tailored to this buyer.

Buyer profile:
{json.dumps(decision_profile, indent=2)}

Pricing results:
{json.dumps(pricing['results'])}

Complaints results:
{json.dumps(complaints['results'])}

Lock-in results:
{json.dumps(lockin['results'])}

User reviews:
{json.dumps(reviews['results'])}

Total cost of ownership:
{json.dumps(tco['results'])}

Return ONLY this JSON object, nothing else:
{{
  "name": "{name}",
  "tagline": "one sentence description",
  "pricing": {{
    "starting_price": 0,
    "currency": "USD",
    "period": "month",
    "pricing_model": "per user / flat / usage based"
  }},
  "pros": ["pro 1", "pro 2", "pro 3"],
  "cons": ["con 1", "con 2", "con 3"],
  "red_flags": ["red flag 1", "red flag 2"],
  "lock_in_score": 5,
  "tco_notes": "hidden costs and total cost of ownership for this specific buyer",
  "best_for": "type of buyer this suits best",
  "verdict": "one sentence honest assessment for this specific buyer"
}}"""
                    }
                ]
            )

            vendor_data = safe_json_parse(synthesis.choices[0].message.content)
            if vendor_data:
                return vendor_data
        except Exception as e:
            print(f"Error researching vendor {name}: {e}")
            return None

    vendors = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = executor.map(research_vendor, vendor_names)
    
    for result in results:
        if result:
            vendors.append(result)

    return vendors

            synthesis = client.chat.completions.create(
                model="perplexity/llama-3.1-sonar-large-128k-online",
                messages=[
                    {
                        "role": "user",
                        "content": f"""Based on these search results about {name}, create a structured vendor profile tailored to this buyer.

Buyer profile:
{json.dumps(decision_profile, indent=2)}

Pricing results:
{json.dumps(pricing['results'])}

Complaints results:
{json.dumps(complaints['results'])}

Lock-in results:
{json.dumps(lockin['results'])}

User reviews:
{json.dumps(reviews['results'])}

Total cost of ownership:
{json.dumps(tco['results'])}

Return ONLY this JSON object, nothing else:
{{
  "name": "{name}",
  "tagline": "one sentence description",
  "pricing": {{
    "starting_price": 0,
    "currency": "USD",
    "period": "month",
    "pricing_model": "per user / flat / usage based"
  }},
  "pros": ["pro 1", "pro 2", "pro 3"],
  "cons": ["con 1", "con 2", "con 3"],
  "red_flags": ["red flag 1", "red flag 2"],
  "lock_in_score": 5,
  "tco_notes": "hidden costs and total cost of ownership for this specific buyer",
  "best_for": "type of buyer this suits best",
  "verdict": "one sentence honest assessment for this specific buyer"
}}"""
                    }
                ]
            )

            vendor_data = safe_json_parse(synthesis.choices[0].message.content)
            if vendor_data:
                vendors.append(vendor_data)

        except Exception as e:
            print(f"Error researching vendor {name}: {e}")
            continue

    return vendors