from tavily import TavilyClient
from dotenv import load_dotenv
import os
import json

load_dotenv()

tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

queries = [
    "OpenAI API outages downtime reliability incidents 2025",
    "Anthropic Claude API problems complaints users Reddit 2025",
    "Google Gemini API pricing tokens per million cost comparison 2025"
]

for query in queries:
    print(f"\n🔍 Searching: {query}")
    result = tavily.search(query=query, max_results=3, include_raw_content=True)
    for r in result['results']:
        print(f"\n  - {r['title']}")
        print(f"    URL: {r['url']}")
        print(f"    Content: {r.get('content', 'No content')[:300]}")
