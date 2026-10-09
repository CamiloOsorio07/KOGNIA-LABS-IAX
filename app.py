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
XAI_AGENT_ID = os.getenv(
    "XAI_AGENT_ID", "agent_riobGKmGZlwleXLk"
).strip()

XAI_URL = f"wss://api.x.ai/v1/realtime?agent_id={XAI_AGENT_ID}"

app = FastAPI(title="xAI Voice Agent")

STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        return {"error": "Falta static/index.html"}
    return FileResponse(index_file)


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
            "message": "Falta configurar XAI_API_KEY en Render."
        })
        await client.close(code=1011)
        return

    tasks = []

    try:
        async with websockets.connect(
            XAI_URL,
            additional_headers={
                "Authorization": f"Bearer {XAI_API_KEY}"
            },
            max_size=20 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
            open_timeout=30,
            close_timeout=5,
        ) as xai:
            await client.send_json({
                "type": "app.status",
                "message": "Conectado a xAI"
            })

            async def browser_to_xai():
                try:
                    while True:
                        message = await client.receive_text()
                        try:
                            event = json.loads(message)
                            print(
                                "NAVEGADOR -> xAI:",
                                event.get("type", "unknown")
                            )
                        except json.JSONDecodeError:
                            print("Mensaje no JSON recibido del navegador")

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

                        event_type = event.get("type", "unknown")
                        if event_type == "error":
                            print("Error xAI:", json.dumps(
                                event.get("error", event),
                                ensure_ascii=False
                            ))
                        else:
                            print("xAI -> NAVEGADOR:", event_type)

                        await client.send_json(event)
                except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
                    pass

            tasks.extend([
                asyncio.create_task(browser_to_xai()),
                asyncio.create_task(xai_to_browser()),
            ])

            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(
                *pending, return_exceptions=True
            )

    except WebSocketDisconnect:
        print("El navegador se desconectó de manera limpia.")

    except websockets.exceptions.ConnectionClosed as exc:
        print(
            f"Conexión xAI cerrada: "
            f"code={exc.code}, reason={exc.reason}"
        )

    except Exception as exc:
        print(f"Error en WebSocket: {type(exc).__name__}: {exc}")

    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks, return_exceptions=True
            )

        with suppress(Exception):
            await client.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=False
    )