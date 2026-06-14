# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


# Acceptance Tests — Gateway STT Proxy

## Manual test prerequisites

Start `whisper.cpp` server locally:

```bash
./build/bin/whisper-server   -m models/ggml-small.bin   --host 127.0.0.1   --port 8080   -t 8
```

Start Retriva Gateway with:

```env
WHISPER_SERVER_URL=http://127.0.0.1:8080/inference
STT_ENABLED=true
```

## Manual smoke test

Using an available short audio sample:

```bash
curl -X POST http://localhost:8002/stt/transcribe   -F "file=@sample.wav;type=audio/wav"   -F "language=auto"
```

Expected response shape:

```json
{
  "text": "..."
}
```

The `text` value must be non-empty for a valid speech sample.

## Error handling tests

### Missing file

```bash
curl -X POST http://localhost:8002/stt/transcribe
```

Expected:

- HTTP `400` or framework-native validation status such as `422`.
- Clear error body.

### Whisper offline

Stop `whisper-server`, then run the smoke test again.

Expected:

- HTTP `502` or `504`.
- No Gateway crash.

### Oversized file

Set:

```env
STT_MAX_AUDIO_BYTES=100
```

Upload any audio file larger than 100 bytes.

Expected:

- HTTP `413`.

## Automated tests to add

Add tests following existing Gateway conventions.

Required scenarios:

1. Successful transcription.
   - Mock Whisper HTTP response as JSON `{ "text": "hello" }`.
   - Assert response is `200` and body contains `{ "text": "hello" }`.

2. Oversized upload.
   - Configure low max bytes.
   - Assert `413`.

3. Whisper timeout.
   - Mock HTTP client timeout.
   - Assert `504`.

4. Whisper non-2xx.
   - Mock `500` from Whisper.
   - Assert `502`.

5. Response normalization.
   - Test `{ "text": "..." }`.
   - Test `{ "transcription": "..." }`.
   - Test `{ "segments": [{ "text": "hello" }, { "text": "world" }] }`.
   - Test `text/plain` response.

## Acceptance definition

Milestone 1 Gateway implementation is accepted when:

- WebUI or curl can upload audio to `/stt/transcribe`.
- Gateway returns a transcript string from Whisper.
- Whisper failures do not crash Gateway.
- Max-size and timeout safeguards are present.
- Environment variables are documented.
