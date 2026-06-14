# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
import httpx
from retriva_gateway.main import app
from retriva_gateway.core.whisper_client import (
    normalize_whisper_response,
    extract_transcript_from_whisper_response,
)


def _make_response(text: str, content_type: str = "application/json") -> httpx.Response:
    """Build a minimal httpx.Response for testing the extractor."""
    resp = httpx.Response(
        status_code=200,
        content=text.encode("utf-8"),
        headers={"content-type": content_type},
    )
    return resp


class TestSttTranscribe(unittest.TestCase):
    """Tests for POST /gateway/stt/transcribe."""

    def setUp(self):
        self.client = TestClient(app)
        self.url = "/gateway/stt/transcribe"
        self.dummy_audio = b"\x00\x01\x02" * 100  # 300 bytes of dummy data

    # --- Happy path ---

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_success(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(return_value="hello world")

        response = self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
            data={"language": "en"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["text"], "hello world")
        self.assertEqual(body["language"], "en")

    # --- Feature gate ---

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_disabled_returns_503(self, mock_settings):
        mock_settings.STT_ENABLED = False

        response = self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 503)

    # --- Validation ---

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_missing_file_returns_422(self, mock_settings):
        mock_settings.STT_ENABLED = True

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 422)

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_empty_file_returns_400(self, mock_settings):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520

        response = self.client.post(
            self.url,
            files={"file": ("test.wav", b"", "audio/wav")},
        )

        self.assertEqual(response.status_code, 400)

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_file_too_large_returns_413(self, mock_settings):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 10  # Very small limit

        big_audio = b"\x00" * 100
        response = self.client.post(
            self.url,
            files={"file": ("test.wav", big_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 413)

    # --- Upstream errors ---

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_whisper_timeout_returns_504(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Whisper server did not respond in time.",
            )
        )

        response = self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 504)

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_whisper_unavailable_returns_502(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Whisper server is unavailable.",
            )
        )

        response = self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 502)

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_whisper_malformed_returns_502(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Whisper server returned a malformed response.",
            )
        )

        response = self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 502)
        body = response.json()
        # Global exception handler wraps into {"error": {"message": ...}}
        message = body.get("detail") or body.get("error", {}).get("message", "")
        self.assertIn("malformed", str(message).lower())

    # --- Parameter forwarding ---

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_language_auto_not_forwarded(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(return_value="hello")

        self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
            data={"language": "auto"},
        )

        mock_whisper.transcribe.assert_called_once()
        call_kwargs = mock_whisper.transcribe.call_args
        # language should be None when "auto" is passed
        self.assertIsNone(call_kwargs.kwargs.get("language") or call_kwargs[1].get("language"))

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_transcribe_prompt_forwarded(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(return_value="hello")

        self.client.post(
            self.url,
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
            data={"prompt": "technical vocabulary"},
        )

        mock_whisper.transcribe.assert_called_once()
        call_kwargs = mock_whisper.transcribe.call_args
        prompt_val = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get("prompt")
        self.assertEqual(prompt_val, "technical vocabulary")


class TestSttRootRoute(unittest.TestCase):
    """Verify that POST /stt/transcribe is reachable at root level (no prefix)."""

    def setUp(self):
        self.client = TestClient(app)
        self.dummy_audio = b"\x00\x01\x02" * 100

    @patch("retriva_gateway.api.v2.speech.whisper_client")
    @patch("retriva_gateway.api.v2.speech.settings")
    def test_root_stt_transcribe(self, mock_settings, mock_whisper):
        mock_settings.STT_ENABLED = True
        mock_settings.STT_MAX_AUDIO_BYTES = 20_971_520
        mock_whisper.transcribe = AsyncMock(return_value="root path works")

        response = self.client.post(
            "/stt/transcribe",
            files={"file": ("test.wav", self.dummy_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["text"], "root path works")

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_root_stt_health(self, mock_settings):
        mock_settings.STT_ENABLED = True
        mock_settings.WHISPER_SERVER_URL = "http://127.0.0.1:8080/inference"

        response = self.client.get("/stt/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])


class TestNormalizeWhisperResponse(unittest.TestCase):
    """Unit tests for the normalize_whisper_response string-based helper."""

    # --- Shape 1: JSON with "text" ---

    def test_json_text_field(self):
        self.assertEqual(normalize_whisper_response('{"text": "hello"}'), "hello")

    def test_json_text_field_with_whitespace(self):
        self.assertEqual(normalize_whisper_response('{"text": "  hello  "}'), "hello")

    # --- Shape 2: JSON with "transcription" ---

    def test_json_transcription_field(self):
        self.assertEqual(normalize_whisper_response('{"transcription": "hello"}'), "hello")

    # --- Shape 3: JSON with "segments" ---

    def test_json_segments(self):
        resp = '{"segments": [{"text": "hello"}, {"text": "world"}]}'
        self.assertEqual(normalize_whisper_response(resp), "hello world")

    def test_json_segments_single(self):
        resp = '{"segments": [{"text": "hello"}]}'
        self.assertEqual(normalize_whisper_response(resp), "hello")

    # --- Shape 4: plain text ---

    def test_plain_text(self):
        self.assertEqual(normalize_whisper_response("hello world"), "hello world")

    def test_plain_text_with_whitespace(self):
        self.assertEqual(normalize_whisper_response("  hello world  "), "hello world")

    # --- Edge cases ---

    def test_empty_string_returns_none(self):
        self.assertIsNone(normalize_whisper_response(""))

    def test_whitespace_only_returns_none(self):
        self.assertIsNone(normalize_whisper_response("   "))

    def test_json_empty_text_returns_none(self):
        self.assertIsNone(normalize_whisper_response('{"text": ""}'))

    def test_json_empty_dict_returns_none(self):
        self.assertIsNone(normalize_whisper_response("{}"))

    def test_json_empty_segments_returns_none(self):
        self.assertIsNone(normalize_whisper_response('{"segments": []}'))

    def test_text_preferred_over_transcription(self):
        """When both keys exist, 'text' takes precedence."""
        resp = '{"text": "from_text", "transcription": "from_transcription"}'
        self.assertEqual(normalize_whisper_response(resp), "from_text")


class TestExtractTranscriptFromWhisperResponse(unittest.TestCase):
    """Tests for extract_transcript_from_whisper_response (content-type-aware)."""

    # --- JSON content-type ---

    def test_json_text_field(self):
        resp = _make_response('{"text": "hello world"}', "application/json")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "hello world")

    def test_json_transcription_field(self):
        resp = _make_response('{"transcription": "hello"}', "application/json")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "hello")

    def test_json_segments(self):
        resp = _make_response(
            '{"segments": [{"text": "hello"}, {"text": "world"}]}',
            "application/json; charset=utf-8",
        )
        self.assertEqual(extract_transcript_from_whisper_response(resp), "hello world")

    def test_json_empty_text_falls_back_to_response_text(self):
        """When JSON has empty text and response body is just that JSON, result is the raw JSON string."""
        resp = _make_response('{"text": ""}', "application/json")
        result = extract_transcript_from_whisper_response(resp)
        # Falls back to response.text.strip() which is the raw JSON
        self.assertTrue(len(result) > 0)

    def test_json_parse_failure_falls_back_to_text(self):
        resp = _make_response("not json at all", "application/json")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "not json at all")

    # --- Non-JSON content-type ---

    def test_plain_text_content_type(self):
        resp = _make_response("hello world", "text/plain")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "hello world")

    def test_no_content_type_falls_back_to_text(self):
        resp = _make_response("hello", "")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "hello")

    # --- Empty/malformed ---

    def test_empty_response_returns_empty(self):
        resp = _make_response("", "application/json")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "")

    def test_whitespace_only_returns_empty(self):
        resp = _make_response("   ", "text/plain")
        self.assertEqual(extract_transcript_from_whisper_response(resp), "")


class TestSttHealth(unittest.TestCase):
    """Tests for GET /gateway/stt/health."""

    def setUp(self):
        self.client = TestClient(app)
        self.url = "/gateway/stt/health"

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_health_when_enabled(self, mock_settings):
        mock_settings.STT_ENABLED = True
        mock_settings.WHISPER_SERVER_URL = "http://127.0.0.1:8080/inference"

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["enabled"])
        self.assertTrue(body["whisper_url_configured"])

    @patch("retriva_gateway.api.v2.speech.settings")
    def test_health_when_disabled(self, mock_settings):
        mock_settings.STT_ENABLED = False
        mock_settings.WHISPER_SERVER_URL = ""

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertFalse(body["whisper_url_configured"])


if __name__ == "__main__":
    unittest.main()

