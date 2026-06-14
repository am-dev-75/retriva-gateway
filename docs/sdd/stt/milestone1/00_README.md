# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


## Pack: Retriva Gateway STT Proxy

This pack contains the Software Design Document and implementation instructions for adding a minimal speech-to-text proxy endpoint to Retriva Gateway.

### Goal

Add a Gateway endpoint:

```http
POST /stt/transcribe
Content-Type: multipart/form-data
```

The endpoint accepts an audio file from Retriva WebUI, forwards it to a local `whisper.cpp` `whisper-server` instance, and returns a normalized JSON payload containing the transcript.

### Out of scope for Milestone 1

- Authentication changes, unless Gateway already has an authentication middleware to reuse.
- Persistent storage of uploaded audio.
- Streaming transcription.
- Automatic query submission.
- Production-grade observability dashboards.
- Advanced language/domain prompt configuration UI.

### Files in this pack

- `01_SDD_GATEWAY_STT_PROXY.md` — design document.
- `02_AGENT_IMPLEMENTATION_PROMPT.md` — direct instructions for Antigravity.
- `03_ACCEPTANCE_TESTS.md` — manual and automated test expectations.
- `04_ENV_CONFIG.md` — required environment variables.
- `05_OPENAPI_CONTRACT.md` — endpoint request/response contract.
- `06_SECURITY_PRIVACY_NOTES.md` — minimal safeguards for audio handling.
