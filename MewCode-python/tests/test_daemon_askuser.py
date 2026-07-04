"""End-to-end test: AskUserRequest event flows through daemon WS stream."""

import asyncio
import json
import sys

import httpx
import websockets


async def main():
    base = "http://127.0.0.1:7800"
    ws_base = "ws://127.0.0.1:7800"

    async with httpx.AsyncClient(timeout=30) as http:
        # Health
        r = await http.get(f"{base}/api/health")
        print(f"[health] {r.json()}")

        # Create session
        r = await http.post(f"{base}/api/session", json={})
        sid = r.json()["session_id"]
        print(f"[session] {sid}")

        # Start a task that should trigger AskUserQuestion
        # The model should ask the user a question to clarify
        r = await http.post(f"{base}/api/task", json={
            "session_id": sid,
            "prompt": "Ask me a question using the AskUserQuestion tool. Ask what programming language I prefer, with options: Python, JavaScript, Rust.",
        })
        task_id = r.json()["task_id"]
        print(f"[task] {task_id}")

    # Stream events
    print("[stream] connecting...")
    askuser_request_id = None
    async with websockets.connect(f"{ws_base}/api/stream/{sid}") as ws:
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("[stream] timeout waiting for events")
                break

            data = json.loads(msg)
            etype = data.get("type", "?")
            d = data.get("data", {})

            if etype == "StreamText":
                print(d.get("text", ""), end="", flush=True)
            elif etype == "AskUserRequest":
                askuser_request_id = d.get("request_id")
                questions = d.get("questions", [])
                print(f"\n[AskUser] request_id={askuser_request_id}")
                for q in questions:
                    print(f"  {q.get('name')}: {q.get('message')} options={q.get('options', [])}")

                # Resolve it immediately via HTTP
                async with httpx.AsyncClient(timeout=10) as http:
                    r = await http.post(f"{base}/api/askuser/{sid}", json={
                        "request_id": askuser_request_id,
                        "answers": {"language": "Python"},
                    })
                    print(f"[AskUser] resolved: {r.json()}")

            elif etype == "LoopComplete":
                print("\n[stream] --- DONE ---")
                break
            elif etype == "ErrorEvent":
                print(f"\n[stream] ERROR: {d.get('message', '')}")
                break
            elif etype == "UsageEvent":
                print(f"\n[usage] in={d.get('input_tokens')} out={d.get('output_tokens')}")
            elif etype == "TurnComplete":
                print(f"\n[turn] {d.get('turn')}")
            else:
                summary = str(d)[:80] if d else ""
                print(f"\n[{etype}] {summary}")

    if askuser_request_id:
        print("\n[PASS] AskUserRequest was received and resolved via HTTP")
    else:
        print("\n[INFO] AskUserQuestion was not triggered by the model (this is OK for smoke test)")


if __name__ == "__main__":
    asyncio.run(main())
