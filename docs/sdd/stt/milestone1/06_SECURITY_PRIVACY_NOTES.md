# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


# Security and Privacy Notes — Gateway STT Proxy

## Milestone 1 safeguards

Implement these immediately:

- Keep Whisper server internal.
- Require the same authentication context as the rest of Gateway if such middleware already exists.
- Enforce maximum upload size.
- Use explicit timeout for Whisper calls.
- Delete temporary files, if any.
- Do not persist audio.
- Do not log raw audio.
- Avoid logging transcript text by default.

## Recommended log fields

```json
{
  "event": "stt_transcription",
  "status": "success",
  "audio_size_bytes": 123456,
  "duration_ms": 1200
}
```

## Avoid in logs

- Raw transcript.
- Audio file contents.
- Temporary filesystem paths, unless needed at debug level.
- Authorization headers.

## Milestone 2 candidates

- Rate limiting.
- Per-user usage metrics.
- Admin-configurable enable/disable flag.
- Explicit retention policy for transcripts if ever stored.
- Audit logging aligned with Retriva policies.
