# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


# Antigravity Implementation Prompt — Gateway

You are implementing Milestone 1 voice dictation support for Retriva Gateway.

## Required outcome

Add an endpoint:

```http
POST /stt/transcribe
```

that receives multipart audio from Retriva WebUI, forwards it to a local `whisper.cpp` `whisper-server`, and returns normalized JSON:

```json
{
  "text": "..."
}
```

## Repository discovery steps

1. Inspect the Gateway repository structure.
2. Identify the web framework and router registration pattern.
3. Identify the configuration/settings pattern.
4. Identify existing HTTP client dependencies.
5. Identify existing tests and test framework.
6. Reuse project conventions; do not introduce unnecessary architecture changes.

## Implementation steps

1. Add STT configuration values:
   - `STT_ENABLED`, default `true`.
   - `WHISPER_SERVER_URL`, default `http://127.0.0.1:8080/inference`.
   - `STT_MAX_AUDIO_BYTES`, default `20971520`.
   - `STT_REQUEST_TIMEOUT_SECONDS`, default `120`.

2. Add a route module/controller for STT.

3. Implement `POST /stt/transcribe`:
   - accept file upload using the project framework;
   - read file bytes;
   - reject over-size upload with `413`;
   - reject missing/empty file with `400`;
   - forward multipart request to Whisper server;
   - map Whisper timeout to `504`;
   - map Whisper HTTP failure to `502`;
   - normalize successful response to `{ text: string }`.

4. Register the route with the Gateway application.

5. Add tests:
   - successful transcription with mocked Whisper response;
   - oversized upload;
   - Whisper timeout/error;
   - response normalization.

6. Update `.env.example` or equivalent documentation.

## Suggested FastAPI-style pseudocode

Adapt this to the actual codebase. Do not blindly paste if the project uses different conventions.

```python
@router.post("/stt/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty audio file")
    if len(content) > settings.stt_max_audio_bytes:
        raise HTTPException(status_code=413, detail="Audio file too large")

    form_data = {"response-format": "json"}
    if language and language != "auto":
        form_data["language"] = language
    if prompt:
        form_data["prompt"] = prompt

    files = {
        "file": (
            file.filename or "audio.webm",
            content,
            file.content_type or "application/octet-stream",
        )
    }

    try:
        async with httpx.AsyncClient(timeout=settings.stt_request_timeout_seconds) as client:
            response = await client.post(settings.whisper_server_url, data=form_data, files=files)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Whisper server timeout")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Whisper server unavailable: {exc}")

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Whisper server error")

    text = normalize_whisper_response(response)
    return {"text": text}
```

## Response normalization guidance

Create a small helper function and unit-test it.

```python
def normalize_whisper_response(response):
    content_type = response.headers.get("content-type", "")

    if "application/json" in content_type:
        payload = response.json()
        if isinstance(payload, dict):
            if isinstance(payload.get("text"), str):
                return payload["text"].strip()
            if isinstance(payload.get("transcription"), str):
                return payload["transcription"].strip()
            segments = payload.get("segments")
            if isinstance(segments, list):
                return " ".join(
                    segment.get("text", "").strip()
                    for segment in segments
                    if isinstance(segment, dict)
                ).strip()

    return response.text.strip()
```

## Do not implement in Milestone 1

- Do not auto-submit the query after transcription.
- Do not store audio/transcripts permanently.
- Do not add streaming transcription.
- Do not expose Whisper directly to browser clients.
