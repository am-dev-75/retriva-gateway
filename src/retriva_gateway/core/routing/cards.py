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

"""Catalog-derived capability cards (Spec 040 Phase B, contract SC1).

Cards are DERIVED from the live ``ToolRegistry``.  This module stores no
tool description, destructive flag, or argument list: every card field is
read from the ``ToolDefinition`` at derivation time, and the card digest
covers the normalized card content so any tool change invalidates the
card.

The only declared catalog metadata is the module-onboarding family
declaration below (which token makes a tool belong to which family).  Card
content is never hand-authored, and nothing here is a routing vocabulary:
``phrasings`` are intentionally absent.  Free-text routing is forbidden by
Spec 040 D-1/D-4.

Phase B only: nothing in the chat path imports this module.  Cards are
wired in Phase C, behind ``AGENT_SEMANTIC_ROUTER_ENABLED``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from retriva_gateway.agent.tools import (
    ToolDefinition,
    ToolRegistry,
    build_default_tool_registry,
)
from retriva_gateway.core.routing.taxonomy import Topic

#: Card format version.  Bumping it changes every card id and digest.
CARD_VERSION = 1

#: Default module identity recorded on every card.  The tool registry is
#: the source of truth; the module string is provenance, not routing.
DEFAULT_MODULE = "retriva-gateway/agent/tools.py"

#: Bound on the argument-name summary.  Card payloads stay small and
#: content-free; parameter descriptions/types are deliberately not copied.
MAX_CARD_ARGUMENTS = 32

#: Module-onboarding family declaration (Spec 040 contract SC1 / D-5).
#: A tool belongs to the first family whose token appears in its name.
#: Order is significant: campaign-history import tools must resolve to
#: CAMPAIGN before the generic ``import`` token is considered.
_FAMILY_RULES: Tuple[Tuple[Topic, Tuple[str, ...]], ...] = (
    (Topic.CAMPAIGN, ("campaign", "grace", "exclusion", "addressed")),
    (Topic.ACP, ("acp",)),
    (Topic.QUALIFICATION, ("qualification", "qualify", "competitor")),
    (Topic.COMPANY_IMPORT, ("import",)),
)


def _tokens(name: str) -> Tuple[str, ...]:
    return tuple(part for part in name.lower().split("_") if part)


def family_for_tool(tool_name: str) -> Optional[Topic]:
    """Return the declared family for ``tool_name``, or ``None``.

    Pure and deterministic: the family is a static module declaration, not
    a model decision and not free-text routing.
    """
    tokens = _tokens(tool_name)
    for family, keywords in _FAMILY_RULES:
        if any(token.startswith(keyword)
               for token in tokens for keyword in keywords):
            return family
    return None


def _bounded(names: Sequence[str]) -> Tuple[Tuple[str, ...], bool]:
    ordered = tuple(sorted(set(names)))
    truncated = len(ordered) > MAX_CARD_ARGUMENTS
    return ordered[:MAX_CARD_ARGUMENTS], truncated


@dataclass(frozen=True)
class ToolCard:
    """Derived, bounded summary of one tool definition."""

    name: str
    description: str
    destructive: bool
    arguments: Tuple[str, ...]
    required_arguments: Tuple[str, ...]
    arguments_truncated: bool
    #: Digest of the full parameter schema (types and constraints included)
    #: so a schema-only change still invalidates the card, without copying
    #: unbounded schema text into the catalog.
    schema_digest: str

    @classmethod
    def from_definition(cls, tool: ToolDefinition) -> "ToolCard":
        parameters = tool.parameters if isinstance(tool.parameters, dict) else {}
        properties = parameters.get("properties") or {}
        required = parameters.get("required") or ()
        arguments, truncated = _bounded(
            [str(name) for name in properties])
        required_arguments, required_truncated = _bounded(
            [str(name) for name in required])
        schema = tool.parameters if isinstance(tool.parameters, dict) else {}
        return cls(
            name=tool.name,
            description=tool.description,
            destructive=bool(tool.destructive),
            arguments=arguments,
            required_arguments=required_arguments,
            arguments_truncated=truncated or required_truncated,
            schema_digest=_digest(schema),
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "destructive": self.destructive,
            "arguments": list(self.arguments),
            "required_arguments": list(self.required_arguments),
            "arguments_truncated": self.arguments_truncated,
            "schema_digest": self.schema_digest,
        }


@dataclass(frozen=True)
class CapabilityCard:
    """One family's derived capability card (Spec 040 contract SC1)."""

    card_id: str
    module: str
    version: int
    family: str
    read_only: bool
    tools: Tuple[ToolCard, ...]
    digest: str

    def payload(self) -> Dict[str, Any]:
        """Normalized, digest-covered card content (excludes ``digest``)."""
        return {
            "card_id": self.card_id,
            "module": self.module,
            "version": self.version,
            "family": self.family,
            "read_only": self.read_only,
            "tools": [tool.payload() for tool in self.tools],
        }


def _canonical(payload: Any) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def derive_cards(
        registry: Optional[ToolRegistry] = None,
        *,
        module: str = DEFAULT_MODULE,
        version: int = CARD_VERSION) -> Tuple[CapabilityCard, ...]:
    """Derive one card per workflow family from ``registry``.

    Raises ``ValueError`` when a registered tool has no declared family:
    onboarding an unmapped tool must fail loudly, never silently drop it
    from the catalog.  Cards are sorted by family and tools by name, so
    the output and every digest are deterministic.
    """
    if registry is None:
        registry = build_default_tool_registry()
    grouped: Dict[Topic, List[ToolDefinition]] = {}
    unmapped: List[str] = []
    for name in registry.names():
        tool = registry.get(name)
        if tool is None:  # defensive; names() comes from the registry
            continue
        family = family_for_tool(name)
        if family is None:
            unmapped.append(name)
        else:
            grouped.setdefault(family, []).append(tool)
    if unmapped:
        raise ValueError(
            "capability catalog has no family declaration for: "
            + ", ".join(sorted(unmapped)))

    cards: List[CapabilityCard] = []
    for family in sorted(grouped, key=lambda topic: topic.value):
        tools = tuple(
            ToolCard.from_definition(tool)
            for tool in sorted(grouped[family], key=lambda t: t.name))
        read_only = all(not tool.destructive for tool in tools)
        card_id = f"{family.value.lower()}.v{version}"
        card = CapabilityCard(
            card_id=card_id,
            module=module,
            version=version,
            family=family.value,
            read_only=read_only,
            tools=tools,
            digest="",
        )
        cards.append(CapabilityCard(
            card_id=card.card_id,
            module=card.module,
            version=card.version,
            family=card.family,
            read_only=card.read_only,
            tools=card.tools,
            digest=_digest(card.payload()),
        ))
    return tuple(cards)


def derive_card_map(
        registry: Optional[ToolRegistry] = None,
        *,
        module: str = DEFAULT_MODULE,
        version: int = CARD_VERSION) -> Dict[str, CapabilityCard]:
    """``family -> card`` map used by the SC2 family enum."""
    return {card.family: card for card in derive_cards(
        registry, module=module, version=version)}


def catalog_digest(cards: Sequence[CapabilityCard]) -> str:
    """Digest of the whole catalog (family, version, card digest)."""
    payload = [
        {
            "family": card.family,
            "version": card.version,
            "digest": card.digest,
        }
        for card in sorted(cards, key=lambda card: card.family)
    ]
    return _digest(payload)
