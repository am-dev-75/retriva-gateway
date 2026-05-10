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

from contextvars import ContextVar
from typing import Optional, List
from pydantic import BaseModel

class Principal(BaseModel):
    id: str
    roles: List[str]
    permissions: List[str]

# Request Context Storage
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
principal_ctx: ContextVar[Principal] = ContextVar(
    "principal", 
    default=Principal(id="anonymous", roles=["admin"], permissions=["*"])
)

def get_correlation_id() -> Optional[str]:
    return correlation_id_ctx.get()

def get_principal() -> Principal:
    return principal_ctx.get()
