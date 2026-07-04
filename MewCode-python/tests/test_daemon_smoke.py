"""Quick smoke test for the MewCode daemon: create session, start task, stream events."""

import asyncio
import json
import sys

import httpx
import websockets


async def main():
    base = "http://127.0.0.1:7800"
    ws_base = "ws://127.0.0.1:7800"

    async with httpx.AsyncClient(timeout=30) as http:
        # 1. Health check
        r = await http.get(f"{base}/api/health")
        print(f"[health] {r.json()}")

        # 2. Create session
        r = await http.post(f"{base}/api/session", json={})
        sid = r.json()["session_id"]
        print(f"[session] created: {sid}")

        # 3. Start a task
        r = await http.post(f"{base}/api/task", json={
            "session_id": sid,
            "prompt": "用一句话介绍你自己",
        })
        task_id = r.json()["task_id"]
        print(f"[task] started: {task_id}")

    # 4. Stream events via WebSocket
    print("[stream] connecting...")
    async with websockets.connect(f"{ws_base}/api/stream/{sid}") as ws:
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("[stream] timeout")
                break

            data = json.loads(msg)
            etype = data.get("type", "?")

            if etype == "StreamText":
                print(data["data"]["text"], end="", flush=True)
            elif etype == "LoopComplete":
                print("\n[stream] --- DONE ---")
                break
            elif etype == "ErrorEvent":
                print(f"\n[stream] ERROR: {data['data']['message']}")
                break
            elif etype == "UsageEvent":
                print(f"\n[usage] in={data['data']['input_tokens']} out={data['data']['output_tokens']}")
            elif etype == "TurnComplete":
                print(f"\n[turn] {data['data']['turn']}")
            else:
                # Show event types for debugging
                d = data.get("data", {})
                summary = str(d)[:80] if d else ""
                print(f"\n[{etype}] {summary}")


if __name__ == "__main__":
    asyncio.run(main())
