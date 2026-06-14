# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


# Environment and Configuration — Gateway STT Proxy

Add these variables to `.env.example`, deployment docs, or the Gateway configuration reference.

```env
# Enable/disable speech-to-text proxy endpoint.
STT_ENABLED=true

# Internal URL of whisper.cpp HTTP server.
WHISPER_SERVER_URL=http://127.0.0.1:8080/inference

# Max accepted audio upload size in bytes. Default: 20 MiB.
STT_MAX_AUDIO_BYTES=20971520

# Timeout for calls from Gateway to whisper.cpp.
STT_REQUEST_TIMEOUT_SECONDS=120
```

## Local development

Run Whisper locally:

```bash
./build/bin/whisper-server   -m models/ggml-small.bin   --host 127.0.0.1   --port 8080   -t 8
```

Run Gateway normally.

## Docker Compose note

If Gateway and Whisper run in the same Compose network, use the service name:

```env
WHISPER_SERVER_URL=http://whisper:8080/inference
```

Do not expose the Whisper service publicly unless there is a deliberate reason.
