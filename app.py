import os
import json
import asyncio
from pathlib import Path

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_AGENT_ID = os.getenv("XAI_AGENT_ID", "agent_riobGKmGZlwleXLk").strip()
XAI_URL = f"wss://api.x.ai/v1/realtime?agent_id={XAI_AGENT_ID}"

app = FastAPI(title="xAI Voice Agent")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "api_key_configured": bool(XAI_API_KEY),
        "agent_id_configured": bool(XAI_AGENT_ID),
    }


@app.websocket("/ws")
async def voice_socket(client: WebSocket):
    await client.accept()

    if not XAI_API_KEY:
        await client.send_json({
            "type": "app.error",
            "message": "Falta XAI_API_KEY en el archivo .env"
        })
        await client.close(code=1011)
        return

    try:
        async with websockets.connect(
            XAI_URL,
            additional_headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            max_size=20 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ) as xai:
            await client.send_json({"type": "app.status", "message": "Conectado a xAI"})

            async def browser_to_xai():
                try:
                    while True:
                        message = await client.receive_text()
                        await xai.send(message)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
                    pass

            async def xai_to_browser():
                try:
                    async for raw in xai:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await client.send_json(event)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
                    pass

            tasks = [
                asyncio.create_task(browser_to_xai()),
                asyncio.create_task(xai_to_browser()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in pending:
                task.cancel()

            await asyncio.gather(*pending, return_exceptions=True)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await client.send_json({"type": "app.error", "message": f"Conexión cerrada: {str(exc)}"})
        except Exception:
            pass
    finally:
        try:
            await client.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)