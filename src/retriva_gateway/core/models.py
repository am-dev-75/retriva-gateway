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

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum

class MetadataFilterMode(str, Enum):
    SOFT = "soft"
    HARD = "hard"

class ErrorDetail(BaseModel):
    code: str
    message: Any
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ErrorResponse(BaseModel):
    error: ErrorDetail

class CapabilitiesResponse(BaseModel):
    chat: bool
    knowledge_bases: bool
    documents: bool
    ingestion: bool
    artifacts: bool
    folder_upload: bool
    speech_input: bool
    auth: bool

class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "0.1.0"

class MetadataFilter(BaseModel):
    field: str
    operator: str
    value: Optional[Any] = None

class ChatRequest(BaseModel):
    message: str
    kb_ids: List[str] = ["default"]
    metadata_filters: Optional[List[MetadataFilter]] = None
    metadata_filter_mode: MetadataFilterMode = MetadataFilterMode.SOFT
    stream: bool = False
    filters: Optional[Dict[str, Any]] = None # Legacy support

class SearchRequest(BaseModel):
    query: str
    kb_ids: List[str] = ["default"]
    metadata_filters: Optional[List[MetadataFilter]] = None
    metadata_filter_mode: MetadataFilterMode = MetadataFilterMode.SOFT
    limit: int = 50
    is_discovery: bool = False
    case_sensitive: bool = False
    filters: Optional[Dict[str, Any]] = None # Legacy support
