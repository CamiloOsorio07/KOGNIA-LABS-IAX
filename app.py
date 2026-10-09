import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

XAI_API_KEY = os.getenv("XAI_API_KEY", "").strip()
XAI_AGENT_ID = os.getenv("XAI_AGENT_ID", "agent_riobGKmGZlwleXLk").strip()
# If your xAI account uses a configured Agent ID, retain it as a query parameter.
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
            "message": "Falta XAI_API_KEY en las variables de entorno del servidor.",
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
            close_timeout=5,
        ) as xai:
            await client.send_json({"type": "app.status", "message": "Conectado a xAI"})

            async def browser_to_xai():
                while True:
                    message = await client.receive_text()
                    # Forward client event unchanged; Realtime expects JSON text frames.
                    await xai.send(message)

            async def xai_to_browser():
                async for raw in xai:
                    try:
                        event = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    await client.send_json(event)

            tasks = [
                asyncio.create_task(browser_to_xai()),
                asyncio.create_task(xai_to_browser()),
            ]
            try:
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    exc = task.exception()
                    if exc and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)):
                        raise exc
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    except WebSocketDisconnect:
        pass
    except websockets.exceptions.ConnectionClosed as exc:
        with suppress(Exception):
            await client.send_json({
                "type": "app.error",
                "message": f"La conexión con xAI se cerró: {exc}",
            })
    except Exception as exc:
        with suppress(Exception):
            await client.send_json({
                "type": "app.error",
                "message": f"Error de conexión: {exc}",
            })
    finally:
        with suppress(Exception):
            await client.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
