import json, urllib.request, os
from pathlib import Path

key = ""
env = Path(__file__).parent.parent / ".env"
if env.exists():
    for line in env.read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            key = line.split("=", 1)[1].strip()

models = [
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "google/gemini-3-flash",
    "google/gemini-3.5-flash",
    "google/gemini-3.1-pro-preview",
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-5.5",
    "anthropic/claude-opus-4.7",
    "x-ai/grok-4.20",
    "qwen/qwen3.7-max",
]

# Quick test: send a tiny prompt to each
for model in models:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with just the word 'ok'"}],
        "max_tokens": 5,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            content = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            print(f"OK     {model:45s} → {content[:30]}")
    except Exception as e:
        print(f"FAIL   {model:45s} → {e}")
