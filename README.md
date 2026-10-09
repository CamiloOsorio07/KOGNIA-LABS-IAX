# Voz IA — xAI Realtime

Pequeña aplicación web con FastAPI + WebSocket y una interfaz de voz. La API key se mantiene en el servidor.

## 1. Requisitos

- Python 3.10 o superior
- Una API key válida de xAI
- El agente configurado en xAI para audio en tiempo real

## 2. Instalar

En esta carpeta, abre una terminal:

```bash
python -m venv .venv
```

Windows PowerShell:
```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
source .venv/bin/activate
```

Instala dependencias y crea el archivo de configuración:

```bash
pip install -r requirements.txt
```

Copia `.env.example` a `.env` y coloca una **clave nueva**:

```dotenv
XAI_API_KEY=tu_clave_nueva
XAI_AGENT_ID=agent_riobGKmGZlwleXLk
```

No compartas ni subas el archivo `.env`.

## 3. Ejecutar

```bash
python app.py
```

Abre http://127.0.0.1:8000 en Chrome o Edge y pulsa **Conectar**. Acepta el permiso de micrófono.

## Notas

- El navegador se conecta al servidor local; la clave API no se envía al navegador.
- La app espera que el agente/endpoint de xAI acepte eventos Realtime como `input_audio_buffer.append` y emita `response.output_audio.delta` / `response.output_audio_transcript.delta`.
- La detección de turnos (VAD) depende de la configuración de audio del agente. Si el agente exige configuración de sesión explícita, añade el evento `session.update` apropiado según la configuración actual de tu agente en xAI.
- La captura usa `ScriptProcessorNode` por simplicidad del ejemplo. Para producción, migra a `AudioWorklet`.
- En despliegue remoto, usa HTTPS/WSS para que el navegador permita el micrófono.
