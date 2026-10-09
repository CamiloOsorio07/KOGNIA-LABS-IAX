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

XAI_API_KEY = os.getenv("XAI_API_KEY")
XAI_AGENT_ID = os.getenv("XAI_AGENT_ID", "agent_riobGKmGZlwleXLk").strip()

if not XAI_API_KEY:
    print("ADVERTENCIA: falta XAI_API_KEY en .env")

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

    tasks = []
    try:
        async with websockets.connect(
            XAI_URL,
            additional_headers={"Authorization": f"Bearer {XAI_API_KEY}"},
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
                while True:
                    message = await client.receive_text()
                    try:
                        event = json.loads(message)
                        event_type = event.get("type", "unknown")
                        if event_type in (
                            "input_audio_buffer.append",
                            "input_audio_buffer.commit",
                            "input_audio_buffer.clear",
                            "response.create",
                            "session.update",
                        ):
                            print("NAVEGADOR -> xAI:", event_type)
                    except json.JSONDecodeError:
                        print("NAVEGADOR -> xAI: mensaje no JSON")
                    await xai.send(message)

            async def xai_to_browser():
                async for raw in xai:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "unknown")
                    if event_type == "error":
                        print("xAI error:", json.dumps(
                            event.get("error", event), ensure_ascii=False
                        ))
                    else:
                        print("xAI -> NAVEGADOR:", event_type)

                    await client.send_json(event)

            tasks = [
                asyncio.create_task(browser_to_xai()),
                asyncio.create_task(xai_to_browser()),
            ]

            # Keep the tunnel open until either side genuinely disconnects.
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            for task in done:
                exc = task.exception()
                if exc:
                    raise exc

    except WebSocketDisconnect:
        print("El navegador se desconectó (cierre del cliente).")
    except websockets.exceptions.ConnectionClosed as exc:
        print(f"Conexión xAI cerrada: code={exc.code}, reason={exc.reason}")
        with suppress(Exception):
            await client.send_json({
                "type": "app.error",
                "message": f"xAI cerró la conexión (código {exc.code}). Revisa la terminal."
            })
    except Exception as exc:
        print("WebSocket error:", repr(exc))
        with suppress(Exception):
            await client.send_json({
                "type": "app.error",
                "message": f"Error de conexión: {exc}"
            })
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(Exception):
            await client.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)
