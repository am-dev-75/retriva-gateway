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

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import List

VERSION = "1.1.0-rc0"

class Settings(BaseSettings):
    GATEWAY_HOST: str = "0.0.0.0"
    GATEWAY_PORT: int = 8002
    
    # Retriva Core URLs
    # We allow separate URLs for ingestion and chat to match docker-compose setup
    RETRIVA_CORE_INGESTION_URL: str = "http://localhost:8000"
    RETRIVA_CORE_CHAT_URL: str = "http://localhost:8001"
    
    GATEWAY_ENABLE_AUTH: bool = False
    GATEWAY_ENABLE_ARTIFACTS: bool = True
    GATEWAY_ENABLE_FOLDER_UPLOAD: bool = True
    GATEWAY_ENABLE_SPEECH_INPUT: bool = False
    GATEWAY_MAX_UPLOAD_MB: int = 500
    GATEWAY_UPLOAD_TMP_DIR: str = "/tmp/retriva-gateway-uploads"
    GATEWAY_CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"]
    
    # --- Speech-to-Text (Whisper) ---
    STT_ENABLED: bool = True
    WHISPER_SERVER_URL: str = "http://127.0.0.1:8080/inference"
    STT_MAX_AUDIO_BYTES: int = 20_971_520          # 20 MiB
    STT_REQUEST_TIMEOUT_SECONDS: int = 120

    # --- Dynamic Ingestion (Connected Sources) ---
    DYNAMIC_INGESTION_ENABLED: bool = True
    DYNAMIC_INGESTION_DATA_DIR: str = "/tmp/retriva-gateway-dynamic-sources"
    ALLOWED_CONNECTOR_TYPES: List[str] = ["mediawiki"]
    DEFAULT_TENANT_ID: str = "internal-company"
    GATEWAY_INTERNAL_SERVICE_TOKEN: str = ""  # Empty = auth disabled for internal endpoints

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _sync_speech_flag(self) -> "Settings":
        """Keep the capability flag in sync: if STT is enabled, advertise speech_input."""
        if self.STT_ENABLED:
            self.GATEWAY_ENABLE_SPEECH_INPUT = True
        return self

settings = Settings()
