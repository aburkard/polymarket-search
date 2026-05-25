"""Experiment: compare LLM models for generating search aliases.

Tests multiple models via OpenRouter on a diverse sample of events.
Evaluates whether the aliases would actually improve search recall.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY") or ""
if not OPENROUTER_KEY:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                OPENROUTER_KEY = line.split("=", 1)[1].strip()

MODELS = [
    "google/gemini-3-flash-preview",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.7",
    "openai/gpt-5.5",
    "x-ai/grok-4.20",
    "x-ai/grok-4.3",
]

PROMPTS = {
    "v1": """You generate search aliases for a prediction market event. Given an event title and its market questions, output a JSON array of short search terms (1-3 words each) that someone might type to find this event BUT that have NO string overlap with words already in the title or questions.

Focus on:
- Acronyms/initialisms (AOC, POTUS, FOMC, BTC, CPI, JCPOA, ECB)
- Nicknames (Wemby, SGA, LeBron, the fed)
- Conceptual bridges — how someone might describe this topic without using any of the same words (e.g. "rates go up" for a market about Fed interest rate increases)
- Entity names missing from the text (full names, alternate names)

Rules:
- ONLY terms with NO words already in the title/questions — skip anything redundant
- Short: 1-3 words max per term
- Specific to THIS event, not generic (don't add "politics" or "sports")
- 5-12 terms""",

    "v2": """You help people find prediction markets by generating search aliases.

A user might search for this event using words that DON'T appear in the event text at all. Your job: figure out what those missing words are.

Think about:
1. ABBREVIATIONS someone would type: ticker symbols, acronyms, initialisms (BTC, ETH, FOMC, CPI, AOC, POTUS, JCPOA, SCOTUS, SGA, etc.)
2. NICKNAMES and alternate names: Wemby for Wembanyama, the fed for Federal Reserve, Starmer for UK PM, etc.
3. HOW someone might DESCRIBE this topic using completely different words: "die" or "assassinated" for "out as President", "crash" for price decline, "rates go up" for interest rate increase
4. PEOPLE involved who aren't named in the text: candidates, leaders, players, CEOs — use the context description to find these

Rules:
- SKIP any word already in the title, market questions, or tags — only add what's MISSING
- 1-3 words per alias, 8-15 aliases total
- Be specific to THIS event, not generic""",
}

SYSTEM_PROMPT = PROMPTS["v2"]

SAMPLE_EVENTS = [
    {
        "title": "Fed decision in April?",
        "markets": [
            "Will there be no change in Fed interest rates after the April 2026 meeting?",
            "Will the Fed decrease interest rates by 25 bps after the April 2026 meeting?",
            "Will the Fed increase interest rates by 25+ bps after the April 2026 meeting?",
        ],
        "tags": "Finance Fed fomc Economy",
        "context": "The Federal Open Market Committee convenes April 29–30 for its third scheduled policy meeting of 2026, with Chair Jerome Powell's press conference following at 2:30 PM ET. Markets currently price roughly 90% probability of a hold at the 4.25–4.50% target range.",
    },
    {
        "title": "Democratic Presidential Nominee 2028",
        "markets": [
            "Will Gavin Newsom win the 2028 Democratic presidential nomination?",
            "Will Alexandria Ocasio-Cortez win the 2028 Democratic presidential nomination?",
            "Will Kamala Harris win the 2028 Democratic presidential nomination?",
        ],
        "tags": "Politics Elections",
        "context": "The 2028 Democratic primary field remains wide open, with California Governor Gavin Newsom, Vice President Kamala Harris, and Representative Alexandria Ocasio-Cortez among the top-tier contenders.",
    },
    {
        "title": "What price will Bitcoin hit in April?",
        "markets": [
            "Will Bitcoin reach $80,000 in April?",
            "Will Bitcoin dip to $65,000 in April?",
            "Will Bitcoin reach $85,000 in April?",
        ],
        "tags": "Crypto Bitcoin Prices",
        "context": "Bitcoin trades near $78,000 entering April 2026, following a post-halving rally that peaked at $95k in January. Spot BTC ETF inflows have moderated.",
    },
    {
        "title": "2026 FIFA World Cup Winner",
        "markets": [
            "Will France win the 2026 FIFA World Cup?",
            "Will Brazil win the 2026 FIFA World Cup?",
            "Will Argentina win the 2026 FIFA World Cup?",
        ],
        "tags": "Sports Soccer FIFA World Cup",
        "context": "The 2026 FIFA World Cup, hosted jointly by the United States, Canada, and Mexico, kicks off June 11. Defending champions Argentina (La Albiceleste) and favorites France (Les Bleus, led by Kylian Mbappé) top the betting.",
    },
    {
        "title": "Thunder vs. Spurs",
        "markets": [
            "Thunder vs. Spurs",
            "Spread: Spurs (-8.5)",
            "Thunder vs. Spurs: O/U 218.5",
        ],
        "tags": "Sports NBA Basketball",
        "context": "Western Conference Finals Game 3 at Frost Bank Center. The Spurs lead the series 2-0 behind Victor Wembanyama and De'Aaron Fox, while OKC's Shai Gilgeous-Alexander looks to keep the Thunder alive.",
    },
    {
        "title": "US x Iran ceasefire extended by...?",
        "markets": [
            "US x Iran ceasefire extended by April 22, 2026?",
            "US x Iran ceasefire extended by May 1, 2026?",
        ],
        "tags": "Geopolitics Iran",
        "context": "A fragile ceasefire between the United States and Iran, brokered by Oman envoy Steve Witkoff, has held since March 15. Secretary of State Marco Rubio and Iranian Foreign Minister Abbas Araghchi are negotiating an extension. Supreme Leader Ayatollah Khamenei has signaled conditional willingness.",
    },
    {
        "title": "Will annual inflation increase by 3.6% in April?",
        "markets": [
            "Will annual inflation increase by 3.6% in April?",
        ],
        "tags": "Finance Economy",
        "context": "The Bureau of Labor Statistics releases April CPI data on May 13. Core PCE, the Fed's preferred inflation gauge, came in at 3.2% in March.",
    },
    {
        "title": "Ethereum above ___ on April 29?",
        "markets": [
            "Will the price of Ethereum be above $2,400 on April 29?",
            "Will the price of Ethereum be above $1,800 on April 29?",
        ],
        "tags": "Crypto Ethereum Prices",
        "context": "ETH trades near $2,100 heading into the end of April, underperforming BTC year-to-date. Vitalik Buterin's latest roadmap post on blob scaling has renewed L2 optimism.",
    },
    {
        "title": "Minnesota Senate Election Winner",
        "markets": [
            "Will the Democrats win the Minnesota Senate race in 2026?",
            "Will the Republicans win the Minnesota Senate race in 2026?",
        ],
        "tags": "Politics Elections Midterms Minnesota Senate",
        "context": "Democratic incumbent Jon Ossoff— correction, this is Minnesota's Class II seat held by Tina Smith (DFL), who is retiring. The DFL primary features Lt. Gov. Peggy Flanagan and Rep. Angie Craig. The GOP primary features Michele Tafoya and Adam Schwarze.",
    },
    {
        "title": "Will someone mass-produce a humanoid robot by 2030?",
        "markets": [
            "Will someone mass-produce a humanoid robot by 2030?",
        ],
        "tags": "Tech Science",
        "context": "Tesla's Optimus (Gen 3), Figure AI's Figure 02, and Boston Dynamics' Atlas are the leading contenders. Elon Musk claims Optimus will be in Tesla factories by late 2026. 1X Technologies (NEO) and Agility Robotics (Digit) are also scaling.",
    },
    {
        "title": "Trump out as President by...?",
        "markets": [
            "Trump out as President by April 30?",
            "Trump out as President by December 31?",
        ],
        "tags": "Politics Trump",
        "context": "Markets on whether Donald Trump leaves office before term end via resignation, removal (25th Amendment or impeachment), death, or incapacitation.",
    },
]


def call_model(model: str, event: dict) -> tuple[str, float, float]:
    parts = [f"Event: {event['title']}"]
    if event.get("tags"):
        parts.append(f"Tags: {event['tags']}")
    parts.append("Markets:\n" + "\n".join(f"- {m}" for m in event["markets"]))
    if event.get("context"):
        parts.append(f"Context: {event['context']}")
    user_msg = "\n".join(parts)

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 1.0,
        "max_tokens": 4096,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "search_aliases",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "aliases": {
                            "type": "array",
                            "items": {"type": "string"},
                        }
                    },
                    "required": ["aliases"],
                    "additionalProperties": False,
                },
            },
        },
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
        },
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        return f"ERROR: {e}", time.time() - t0, 0

    elapsed = time.time() - t0
    choice = result.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content") or ""
    content = content.strip()
    cost = float(result.get("usage", {}).get("total_cost", 0) or 0)

    return content, elapsed, cost


def parse_aliases(raw: str) -> list[str]:
    raw = raw.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "aliases" in parsed:
            return [str(x).lower().strip() for x in parsed["aliases"] if x]
        if isinstance(parsed, list):
            return [str(x).lower().strip() for x in parsed if x]
    except json.JSONDecodeError:
        pass
    # Fallback: find JSON array anywhere
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start:end + 1])
            if isinstance(parsed, list):
                return [str(x).lower().strip() for x in parsed if x]
        except json.JSONDecodeError:
            pass
    return []


def main():
    models = MODELS
    if len(sys.argv) > 1:
        models = sys.argv[1:]

    print(f"Testing {len(models)} models on {len(SAMPLE_EVENTS)} events\n")

    all_results: dict[str, dict] = {}
    total_costs: dict[str, float] = {}

    for model in models:
        print(f"\n{'=' * 78}")
        print(f"  {model}")
        print(f"{'=' * 78}")

        model_cost = 0
        model_times = []

        for ev in SAMPLE_EVENTS:
            raw, elapsed, cost = call_model(model, ev)
            aliases = parse_aliases(raw)
            model_cost += cost
            model_times.append(elapsed)

            key = ev["title"]
            if key not in all_results:
                all_results[key] = {}
            all_results[key][model] = aliases

            print(f"\n  [{ev['title'][:50]}] ({elapsed:.1f}s, ${cost:.6f})")
            if aliases:
                print(f"    {aliases}")
            else:
                print(f"    PARSE FAILED: {raw[:200]}")

            time.sleep(0.2)

        avg_time = sum(model_times) / len(model_times)
        total_costs[model] = model_cost
        print(f"\n  Total: ${model_cost:.6f}, avg {avg_time:.1f}s/call")

    # Summary
    print(f"\n\n{'=' * 78}")
    print("  COST SUMMARY")
    print(f"{'=' * 78}")
    for model, cost in sorted(total_costs.items(), key=lambda x: x[1]):
        per_5k = cost / len(SAMPLE_EVENTS) * 5000
        print(f"  {model:45s} 10 calls: ${cost:.6f}  est 5K: ${per_5k:.4f}")

    # Quality comparison: for each event, show all models' outputs side by side
    print(f"\n\n{'=' * 78}")
    print("  QUALITY COMPARISON")
    print(f"{'=' * 78}")
    for title, model_outputs in all_results.items():
        print(f"\n  {title}")
        for model, aliases in model_outputs.items():
            short_model = model.split("/")[-1]
            print(f"    {short_model:25s} {aliases}")


if __name__ == "__main__":
    main()
