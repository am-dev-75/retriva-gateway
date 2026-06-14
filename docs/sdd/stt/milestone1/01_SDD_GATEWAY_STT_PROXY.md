# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


# Software Design Document — Gateway STT Proxy

## 1. Purpose

Implement Milestone 1 for voice dictation in Retriva by adding a backend speech-to-text proxy in Retriva Gateway.

The WebUI will upload recorded microphone audio to the Gateway. The Gateway will forward the audio to a locally running `whisper.cpp` HTTP server and return the transcribed text to the WebUI.

## 2. Design principles

- Keep `whisper.cpp` internal to the backend network.
- Keep the browser coupled only to Retriva Gateway.
- Do not persist user audio in Milestone 1.
- Normalize the Whisper response so WebUI does not depend on `whisper.cpp` response details.
- Fail safely with clear HTTP status codes.
- Preserve the existing Retriva query flow unchanged.

## 3. Assumptions

Antigravity must inspect the repository before editing code. The exact Gateway framework and package layout must be discovered from the current codebase.

Expected Gateway stack from previous architecture discussion:

- Python backend, likely FastAPI or equivalent.
- Existing Gateway service listening around port `8002`.
- Existing environment-driven configuration.

If the Gateway is not FastAPI, adapt the same API contract to the actual framework while preserving endpoint behavior.

## 4. New endpoint

```http
POST /stt/transcribe
Content-Type: multipart/form-data
```

### Form fields

```text
file      required  audio file, e.g. audio/webm, audio/wav, audio/mpeg
language  optional  auto | it | en | etc.; default auto
prompt    optional  initial prompt for Whisper/domain vocabulary
```

### Success response

```json
{
  "text": "Quali documenti abbiamo sul progetto X?",
  "language": "auto",
  "duration_ms": 1234,
  "model": null
}
```

For Milestone 1, `language`, `duration_ms`, and `model` may be `null` if not available. `text` must always be a string.

### Error responses

Use appropriate status codes:

- `400` — missing file or invalid form data.
- `413` — uploaded audio exceeds configured maximum size.
- `415` — unsupported media type, if MIME validation is implemented.
- `502` — Whisper server returned an error or malformed response.
- `504` — Whisper server timeout.
- `500` — unexpected Gateway-side error.

## 5. Configuration

Add environment-based configuration:

```env
WHISPER_SERVER_URL=http://127.0.0.1:8080/inference
STT_MAX_AUDIO_BYTES=20971520
STT_REQUEST_TIMEOUT_SECONDS=120
STT_ENABLED=true
```

Default values should be safe for local development.

If the project already has a typed settings/configuration object, add these fields there.

## 6. Processing flow

```text
WebUI uploads audio
   -> Gateway validates feature enabled
   -> Gateway validates file presence
   -> Gateway enforces max file size
   -> Gateway forwards multipart request to WHISPER_SERVER_URL
   -> Gateway normalizes Whisper response
   -> Gateway returns { text }
```

## 7. Whisper forwarding behavior

Forward the audio as multipart form-data using field name `file`.

Recommended forwarded form fields:

```text
response-format=json
language=<language>          only when provided and not auto
prompt=<prompt>              only when provided and non-empty
```

The exact parameter spelling accepted by the installed `whisper.cpp` version should be verified against the running server. If current server expects `response_format` instead of `response-format`, support the actual version and document the choice in code comments.

## 8. Response normalization

Whisper server responses can vary by version. Implement tolerant parsing:

- If JSON contains `text`, use that.
- Else if JSON contains `transcription`, use that.
- Else if JSON contains segments, concatenate segment text.
- Else if response is plain text, return trimmed body as text.

Always return:

```json
{
  "text": "..."
}
```

with optional metadata when available.

## 9. Temporary files

Avoid writing uploaded audio to disk unless required by the framework or client library. If temporary files are used:

- write to OS temporary directory;
- use randomized filenames;
- delete files in `finally` blocks;
- do not log temp paths unless needed for debugging.

## 10. Security and privacy

- Do not persist user audio.
- Do not log raw audio content.
- Avoid logging full transcript by default.
- Enforce max upload size.
- Apply existing Gateway authentication if present.
- Add rate limiting only if the Gateway already has a simple mechanism; otherwise document as Milestone 2.

## 11. Health check, optional for Milestone 1

If easy to add, expose:

```http
GET /stt/health
```

Response:

```json
{
  "enabled": true,
  "whisper_url_configured": true
}
```

Do not require this endpoint for Milestone 1 acceptance unless it is trivial.

## 12. Non-functional requirements

- Typical short dictation under 30 seconds should complete within the configured timeout.
- Gateway must not block indefinitely when Whisper is unavailable.
- Endpoint must work with browser-recorded `audio/webm` when Whisper server has FFmpeg support.
- Endpoint must degrade gracefully if Whisper is offline.

## 13. Done criteria

- `POST /stt/transcribe` exists.
- It accepts multipart audio upload.
- It forwards to local `whisper.cpp` server.
- It returns normalized `{ "text": "..." }` JSON.
- It has max-size and timeout safeguards.
- It includes tests or at least a documented manual test using `curl`.
