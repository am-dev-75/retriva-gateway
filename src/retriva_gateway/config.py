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
from typing import List

VERSION = "0.1.0"

class Settings(BaseSettings):
    GATEWAY_HOST: str = "0.0.0.0"
    GATEWAY_PORT: int = 8080
    
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
    
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
