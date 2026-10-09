"use strict";

(() => {
    const $ = (id) => document.getElementById(id);
    const voicePanel = $("voicePanel");
    const statusDot = $("statusDot");
    const statusText = $("statusText");
    const stateText = $("stateText");
    const hintText = $("hintText");
    const messages = $("messages");
    const connectBtn = $("connectBtn");
    const muteBtn = $("muteBtn");
    const disconnectBtn = $("disconnectBtn");
    const clearBtn = $("clearBtn");

    const AUDIO_RATE = 24000;
    let socket = null;
    let mediaStream = null;
    let audioContext = null;
    let micSource = null;
    let processor = null;
    let silentGain = null;
    let connected = false;
    let connecting = false;
    let muted = false;
    let playbackAt = 0;
    let messageCount = 0;
    let activeBubble = null;
    let agentText = "";
    let textSource = null;
    let responseSeen = false;

    function setStatus(text, state = "idle") {
        statusText.textContent = text;
        statusDot.classList.toggle("live", state === "live");
        statusDot.classList.toggle("error", state === "error");
    }

    function setState(text, hint = "") {
        stateText.textContent = text;
        hintText.textContent = hint;
    }

    function updateCounter() {
        $("messageCount").textContent = `${messageCount} ${messageCount === 1 ? "respuesta" : "respuestas"}`;
    }

    function addAgentMessage(text = "") {
        $("emptyState")?.remove();
        const article = document.createElement("article");
        article.className = "message";
        const label = document.createElement("div");
        label.className = "message-label";
        label.textContent = "KOGNIA";
        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.textContent = text;
        article.append(label, bubble);
        messages.appendChild(article);
        messages.scrollTop = messages.scrollHeight;
        messageCount += 1;
        updateCounter();
        return bubble;
    }

    function sendEvent(event) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return false;
        socket.send(JSON.stringify(event));
        return true;
    }

    function bytesToBase64(bytes) {
        let binary = "";
        const size = 0x8000;
        for (let i = 0; i < bytes.length; i += size) {
            binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + size, bytes.length)));
        }
        return btoa(binary);
    }

    function pcm16Base64(samples) {
        const pcm = new Int16Array(samples.length);
        for (let i = 0; i < samples.length; i++) {
            const value = Math.max(-1, Math.min(1, samples[i]));
            pcm[i] = value < 0 ? Math.round(value * 32768) : Math.round(value * 32767);
        }
        return bytesToBase64(new Uint8Array(pcm.buffer));
    }

    function resample(input, inputRate, outputRate) {
        if (inputRate === outputRate) return input;
        const ratio = inputRate / outputRate;
        const output = new Float32Array(Math.floor(input.length / ratio));
        for (let i = 0; i < output.length; i++) {
            const pos = i * ratio;
            const left = Math.floor(pos);
            const right = Math.min(left + 1, input.length - 1);
            const fraction = pos - left;
            output[i] = input[left] * (1 - fraction) + input[right] * fraction;
        }
        return output;
    }

    async function startMicrophone() {
        if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error("El micrófono requiere HTTPS o localhost y un navegador compatible.");
        }
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            video: false
        });
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw new Error("Este navegador no admite AudioContext.");
        audioContext = new AudioContextClass();
        if (audioContext.state === "suspended") await audioContext.resume();
        micSource = audioContext.createMediaStreamSource(mediaStream);
        processor = audioContext.createScriptProcessor(2048, 1, 1);
        silentGain = audioContext.createGain();
        silentGain.gain.value = 0;
        processor.onaudioprocess = (event) => {
            if (!connected || muted || !socket || socket.readyState !== WebSocket.OPEN) return;
            const samples = resample(new Float32Array(event.inputBuffer.getChannelData(0)), audioContext.sampleRate, AUDIO_RATE);
            if (samples.length) sendEvent({ type: "input_audio_buffer.append", audio: pcm16Base64(samples) });
        };
        micSource.connect(processor);
        processor.connect(silentGain);
        silentGain.connect(audioContext.destination);
    }

    function stopMicrophone() {
        try {
            if (processor) { processor.onaudioprocess = null; processor.disconnect(); }
            micSource?.disconnect();
            silentGain?.disconnect();
        } catch (error) {
            console.debug("Audio nodes ya desconectados", error);
        }
        processor = null;
        micSource = null;
        silentGain = null;
        if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
        mediaStream = null;
        if (audioContext) audioContext.close().catch(() => { });
        audioContext = null;
    }

    function decodeBase64(base64) {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        return bytes;
    }

    function playAudioChunk(base64) {
        if (!audioContext || muted) return;
        try {
            const bytes = decodeBase64(base64);
            const length = bytes.byteLength - bytes.byteLength % 2;
            if (!length) return;
            const view = new DataView(bytes.buffer, bytes.byteOffset, length);
            const count = length / 2;
            const buffer = audioContext.createBuffer(1, count, AUDIO_RATE);
            const channel = buffer.getChannelData(0);
            for (let i = 0; i < count; i++) channel[i] = view.getInt16(i * 2, true) / 32768;
            const source = audioContext.createBufferSource();
            source.buffer = buffer;
            source.connect(audioContext.destination);
            playbackAt = Math.max(playbackAt, audioContext.currentTime + 0.04);
            source.start(playbackAt);
            playbackAt += buffer.duration;
            voicePanel.classList.add("speaking");
            voicePanel.classList.remove("listening");
            setState("KOGNIA está hablando", "Escucha la respuesta…");
            source.onended = () => {
                if (!audioContext || audioContext.currentTime + 0.05 < playbackAt) return;
                voicePanel.classList.remove("speaking");
                if (connected && !muted) {
                    voicePanel.classList.add("listening");
                    setState("KOGNIA está escuchando", "Puedes hablar cuando quieras.");
                }
            };
        } catch (error) {
            console.error("No se pudo reproducir el audio:", error);
        }
    }

    function appendAgentText(delta, source) {
        if (!delta) return;
        if (textSource && textSource !== source) return;
        textSource = source;
        if (!activeBubble) activeBubble = addAgentMessage("");
        agentText += delta;
        activeBubble.textContent = agentText;
        messages.scrollTop = messages.scrollHeight;
    }

    function finishAgentText(finalText = "") {
        const text = String(finalText || agentText).trim();
        if (text) {
            if (!activeBubble) activeBubble = addAgentMessage(text);
            else activeBubble.textContent = text;
        } else if (activeBubble) {
            activeBubble.closest(".message")?.remove();
            messageCount = Math.max(0, messageCount - 1);
            updateCounter();
        }
        activeBubble = null;
        agentText = "";
        textSource = null;
        responseSeen = false;
        messages.scrollTop = messages.scrollHeight;
    }

    function handleEvent(event) {
        const type = event.type || "";
        console.debug("[KOGNIA]", type, event);

        // Las transcripciones del usuario se ignoran intencionalmente.
        if (type.startsWith("conversation.item.input_audio_transcription.")) return;

        if (type === "error" || type === "app.error") {
            const message = event.error?.message || event.message || "Se produjo un error en la conexión.";
            setStatus("Error", "error");
            setState("Error de KOGNIA", message);
            console.error("Error del servidor:", event);
            return;
        }

        if (type === "response.created") {
            activeBubble = null;
            agentText = "";
            textSource = null;
            responseSeen = true;
            setState("KOGNIA está preparando la respuesta", "Un momento…");
            return;
        }

        if (type === "response.output_audio_transcript.delta") {
            appendAgentText(event.delta, "audio");
            return;
        }
        if (type === "response.text.delta" || type === "response.output_text.delta") {
            appendAgentText(event.delta, "text");
            return;
        }
        if (type === "response.output_audio_transcript.done") {
            if (textSource !== "text") finishAgentText(event.transcript || "");
            return;
        }
        if (type === "response.output_text.done") {
            if (textSource !== "audio") finishAgentText(event.text || "");
            return;
        }
        if (type === "response.output_audio.delta" || type === "response.audio.delta") {
            if (event.delta) playAudioChunk(event.delta);
            return;
        }
        if (type === "response.done") {
            if (activeBubble && agentText) finishAgentText(agentText);
            else if (responseSeen) finishAgentText(agentText);
            if (connected && !muted) {
                voicePanel.classList.add("listening");
                setState("KOGNIA está escuchando", "Puedes hacer otra pregunta.");
            }
            return;
        }
        if (type === "input_audio_buffer.speech_started") {
            setState("KOGNIA está escuchando", "Habla con naturalidad.");
            return;
        }
        if (type === "input_audio_buffer.speech_stopped") {
            setState("Procesando tu intervención", "KOGNIA está preparando su respuesta.");
        }
    }

    function configureSession() {
        // Configuración compatible con el formato de sesión del proyecto original.
        sendEvent({
            type: "session.update",
            session: {
                type: "realtime",
                instructions: "Tu nombre es KOGNIA. Preséntate como KOGNIA, nunca como asistente genérico. Responde en español de forma natural, clara y útil. Espera a que el usuario termine de hablar antes de responder.",
                audio: {
                    input: {
                        format: { type: "audio/pcm", rate: AUDIO_RATE },
                        transcription: { model: "grok-transcribe", language: "es" },
                        turn_detection: { type: "server_vad", threshold: 0.5, prefix_padding_ms: 300, silence_duration_ms: 650 }
                    },
                    output: { format: { type: "audio/pcm", rate: AUDIO_RATE }, voice: "sal" }
                }
            }
        });
    }

    async function connect() {
        if (connected || connecting) return;
        connecting = true;
        connectBtn.disabled = true;
        setStatus("Conectando…");
        setState("Preparando KOGNIA", "Solicitando acceso al micrófono.");

        try {
            await startMicrophone();
            const protocol = location.protocol === "https:" ? "wss:" : "ws:";
            const ws = new WebSocket(`${protocol}//${location.host}/ws`);
            socket = ws;
            ws.onopen = () => {
                if (socket !== ws) return;
                connected = true;
                connecting = false;
                setStatus("Conectado", "live");
                setState("KOGNIA está escuchando", "Haz tu pregunta en voz alta.");
                voicePanel.classList.add("listening");
                connectBtn.textContent = "Conectado";
                muteBtn.disabled = false;
                disconnectBtn.disabled = false;
                configureSession();
            };
            ws.onmessage = (message) => {
                if (socket !== ws) return;
                try { handleEvent(JSON.parse(message.data)); }
                catch (error) { console.error("Evento WebSocket no válido:", error); }
            };
            ws.onerror = (error) => {
                console.error("WebSocket falló:", error);
                setStatus("Error de conexión", "error");
                setState("No se pudo conectar con KOGNIA", "Comprueba los registros del servidor.");
            };
            ws.onclose = () => {
                if (socket !== ws) return;
                socket = null;
                connected = false;
                connecting = false;
                voicePanel.classList.remove("listening", "speaking");
                setStatus("Desconectado");
                setState("KOGNIA está desconectada", "Puedes conectarte de nuevo.");
                connectBtn.disabled = false;
                connectBtn.textContent = "▶ Conectar";
                muteBtn.disabled = true;
                disconnectBtn.disabled = true;
                stopMicrophone();
            };
        } catch (error) {
            console.error("No se pudo iniciar KOGNIA:", error);
            connected = false;
            connecting = false;
            setStatus("Error", "error");
            setState("No se pudo iniciar KOGNIA", error.message || "Revisa los permisos del micrófono.");
            connectBtn.disabled = false;
            stopMicrophone();
        }
    }

    function disconnect() {
        connected = false;
        connecting = false;
        const oldSocket = socket;
        socket = null;
        if (oldSocket && oldSocket.readyState < WebSocket.CLOSING) oldSocket.close(1000, "Desconexión solicitada");
        stopMicrophone();
        voicePanel.classList.remove("listening", "speaking");
        setStatus("Desconectado");
        setState("KOGNIA está desconectada", "Pulsa Conectar para comenzar.");
        connectBtn.disabled = false;
        connectBtn.textContent = "▶ Conectar";
        muteBtn.disabled = true;
        disconnectBtn.disabled = true;
        muted = false;
        muteBtn.textContent = "Silenciar";
    }

    function toggleMute() {
        muted = !muted;
        if (mediaStream) mediaStream.getAudioTracks().forEach((track) => { track.enabled = !muted; });
        muteBtn.textContent = muted ? "Activar micrófono" : "Silenciar";
        if (muted) {
            voicePanel.classList.remove("listening");
            setState("Micrófono silenciado", "KOGNIA no recibirá tu voz.");
        } else {
            audioContext?.resume().catch(() => { });
            voicePanel.classList.add("listening");
            setState("KOGNIA está escuchando", "Puedes hacer tu siguiente pregunta.");
        }
    }

    function clearConversation() {
        messages.replaceChildren();
        const empty = document.createElement("div");
        empty.id = "emptyState";
        empty.className = "empty-state";
        const icon = document.createElement("div");
        icon.className = "empty-icon";
        icon.textContent = "✳";
        const title = document.createElement("h3");
        title.textContent = "Conversación limpia";
        const description = document.createElement("p");
        description.textContent = "Las próximas respuestas de KOGNIA aparecerán aquí.";
        empty.append(icon, title, description);
        messages.appendChild(empty);
        messageCount = 0;
        updateCounter();
        activeBubble = null;
        agentText = "";
        textSource = null;
    }

    connectBtn.addEventListener("click", connect);
    disconnectBtn.addEventListener("click", disconnect);
    muteBtn.addEventListener("click", toggleMute);
    clearBtn.addEventListener("click", clearConversation);
    window.addEventListener("beforeunload", () => {
        if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
        stopMicrophone();
    });
    updateCounter();
})();
