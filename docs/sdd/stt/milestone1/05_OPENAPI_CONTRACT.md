# Retriva Milestone 1 — Whisper.cpp Dictation Integration

Generated SDD pack for implementation with Antigravity.

Date: 2026-06-14
Owner: Andrea Marson
Project: Retriva
Milestone: 1 — Local prototype for voice dictation


# OpenAPI Contract — `/stt/transcribe`

## Endpoint

```http
POST /stt/transcribe
```

## Request

Content type:

```text
multipart/form-data
```

Fields:

```yaml
file:
  required: true
  type: string
  format: binary
  description: Browser-recorded audio or WAV/MP3/OGG/WebM audio file.
language:
  required: false
  type: string
  description: Optional language code. Use auto or omit for auto-detection.
prompt:
  required: false
  type: string
  description: Optional initial prompt/domain vocabulary hint.
```

## Response `200`

```json
{
  "text": "Quali sono i documenti relativi al progetto X?",
  "language": "it",
  "duration_ms": 1200,
  "model": "ggml-small.bin"
}
```

Only `text` is mandatory in Milestone 1. Other fields may be omitted or set to `null`.

## Error response example

```json
{
  "detail": "Whisper server timeout"
}
```

## Compatibility requirement

The WebUI must rely only on the `text` property. Any other property is optional and non-breaking.
