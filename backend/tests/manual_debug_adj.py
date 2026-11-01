# Debug probe: shows raw LLM adjustments vs sanitized ones for seeded data (iteration 10). Usage: python manual_debug_adj.py
import asyncio
import json
import os
import sys

sys.path.insert(0, "/app/backend")
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
import manual_seed_adjust as seedmod  # noqa: E402
import server  # noqa: E402
import ai  # noqa: E402
from emergentintegrations.llm.chat import UserMessage, TextDelta, StreamDone  # noqa: E402


async def main():
    seedmod.backup()
    seedmod.seed()
    try:
        day, start, end = server._day_range(None)
        st = await server.daily_stats("user_test1", start, end)
        print("TOTAL TRADES", st["total_trades"])
        prompt = ai.daily_prompt(day, st)
        chat = ai.daily_chat()
        full = []
        async for ev in chat.stream_message(UserMessage(text=prompt)):
            if isinstance(ev, TextDelta):
                full.append(ev.content)
            elif isinstance(ev, StreamDone):
                break
        raw = await ai.ai_adjustments("".join(full) + "\n\nDados:\n" + prompt, server._adj_allowed_text())
        print("RAW:", json.dumps(raw, ensure_ascii=False))
        hb, mb, plugins = await server._configs("user_test1")
        for a in raw:
            print("SAN:", a.get("scope"), a.get("field"), a.get("value"), "->",
                  json.dumps(server.sanitize_adj(a, hb, mb, plugins), ensure_ascii=False))
    finally:
        seedmod.clean()
        seedmod.restore()


asyncio.run(main())
