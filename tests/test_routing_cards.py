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

"""Spec 040 Phase B — capability-card derivation and digest tests.

Cards must be derived from the live ToolRegistry: a changed tool
definition must change the card digest, and no tool may be silently
dropped from the catalog.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

import pytest

from retriva_gateway.agent.tools import (
    ToolDefinition,
    ToolRegistry,
    build_default_tool_registry,
)
from retriva_gateway.core.routing.cards import (
    CARD_VERSION,
    DEFAULT_MODULE,
    MAX_CARD_ARGUMENTS,
    catalog_digest,
    derive_card_map,
    derive_cards,
    family_for_tool,
)
from retriva_gateway.core.routing.taxonomy import Topic


async def _noop(arguments: Dict[str, Any], ctx: Any) -> Dict[str, Any]:
    return {}


def _tool(
        name: str,
        *,
        description: str = "test tool",
        destructive: bool = False,
        properties: Optional[Dict[str, Any]] = None,
        required: Optional[list] = None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
        execute=_noop,
        destructive=destructive,
    )


def _registry_with(*tools: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _default_with(replacements: Dict[str, ToolDefinition]) -> ToolRegistry:
    base = build_default_tool_registry()
    registry = ToolRegistry()
    for name in base.names():
        tool = replacements.get(name, base.get(name))
        registry.register(tool)
    for name, tool in replacements.items():
        if name not in base.names():
            registry.register(tool)
    return registry


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def test_derives_one_card_per_workflow_family():
    cards = derive_cards()
    assert {card.family for card in cards} == {
        Topic.ACP.value,
        Topic.QUALIFICATION.value,
        Topic.COMPANY_IMPORT.value,
        Topic.CAMPAIGN.value,
    }
    for card in cards:
        assert card.card_id == f"{card.family.lower()}.v{CARD_VERSION}"
        assert card.module == DEFAULT_MODULE
        assert card.version == CARD_VERSION
        assert card.tools
        assert card.digest
        assert len(card.digest) == 64
        assert card.read_only == all(
            not tool.destructive for tool in card.tools)


def test_every_registry_tool_appears_exactly_once():
    registry = build_default_tool_registry()
    cards = derive_cards(registry)
    names = [tool.name for card in cards for tool in card.tools]
    assert sorted(names) == registry.names()
    assert len(names) == len(set(names))


def test_cards_are_sorted_and_deterministic():
    first = derive_cards()
    second = derive_cards()
    assert [card.family for card in first] == sorted(
        card.family for card in first)
    assert [card.digest for card in first] == [
        card.digest for card in second]
    assert catalog_digest(first) == catalog_digest(second)
    for card in first:
        assert [tool.name for tool in card.tools] == sorted(
            tool.name for tool in card.tools)


def test_family_declaration_covers_ambiguous_tool_names():
    assert family_for_tool("import_campaign_company_history") is Topic.CAMPAIGN
    assert family_for_tool("get_company_campaign_history") is Topic.CAMPAIGN
    assert family_for_tool("analyze_company_import") is Topic.COMPANY_IMPORT
    assert family_for_tool("commit_company_import") is Topic.COMPANY_IMPORT
    assert family_for_tool("list_competitor_proposal_signals") is \
        Topic.QUALIFICATION
    assert family_for_tool("cancel_qualification_job") is Topic.QUALIFICATION
    assert family_for_tool("accept_acp_enrichment_evidence") is Topic.ACP
    assert family_for_tool("list_campaigns") is Topic.CAMPAIGN
    assert family_for_tool("unknown_tool") is None


def test_unmapped_tool_fails_closed():
    registry = _registry_with(_tool("unknown_tool"))
    with pytest.raises(ValueError, match="unknown_tool"):
        derive_cards(registry)


def test_card_map_keyed_by_family():
    card_map = derive_card_map()
    assert set(card_map) == {
        Topic.ACP.value,
        Topic.QUALIFICATION.value,
        Topic.COMPANY_IMPORT.value,
        Topic.CAMPAIGN.value,
    }
    assert card_map[Topic.CAMPAIGN.value].family == Topic.CAMPAIGN.value


# ---------------------------------------------------------------------------
# Digest stability (cards cannot drift from the tools)
# ---------------------------------------------------------------------------

def test_changing_description_changes_the_digest():
    base = build_default_tool_registry()
    original = base.get("list_campaigns")
    changed = replace(original, description=original.description + " changed")
    before = derive_cards(base)
    after = derive_cards(_default_with({"list_campaigns": changed}))
    assert catalog_digest(before) != catalog_digest(after)
    campaign_before = {c.family: c for c in before}[Topic.CAMPAIGN.value]
    campaign_after = {c.family: c for c in after}[Topic.CAMPAIGN.value]
    assert campaign_before.digest != campaign_after.digest


def test_changing_destructive_changes_the_digest():
    base = build_default_tool_registry()
    original = base.get("list_campaigns")
    changed = replace(original, destructive=True)
    before = {c.family: c for c in derive_cards(base)}
    after = {c.family: c for c in derive_cards(
        _default_with({"list_campaigns": changed}))}
    assert before[Topic.CAMPAIGN.value].digest != \
        after[Topic.CAMPAIGN.value].digest
    # Other campaign tools are already destructive, so the card-level
    # read_only flag does not change; the per-tool flag and digest do.
    assert before[Topic.CAMPAIGN.value].read_only == \
        after[Topic.CAMPAIGN.value].read_only
    after_tool = next(
        tool for tool in after[Topic.CAMPAIGN.value].tools
        if tool.name == "list_campaigns")
    assert after_tool.destructive is True


def test_changing_arguments_changes_the_digest():
    base = build_default_tool_registry()
    original = base.get("list_campaigns")
    changed = replace(original, parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "family": {"type": "string"},
            "new_argument": {"type": "string"},
        },
        "required": ["status"],
    })
    before = {c.family: c for c in derive_cards(base)}
    after = {c.family: c for c in derive_cards(
        _default_with({"list_campaigns": changed}))}
    assert before[Topic.CAMPAIGN.value].digest != \
        after[Topic.CAMPAIGN.value].digest
    after_tool = next(
        tool for tool in after[Topic.CAMPAIGN.value].tools
        if tool.name == "list_campaigns")
    assert "new_argument" in after_tool.arguments


def test_changing_parameter_type_changes_the_digest():
    base = build_default_tool_registry()
    original = base.get("list_campaigns")
    changed_properties = {
        name: {"type": "integer"}
        for name in (original.parameters.get("properties") or {})
    }
    changed = replace(original, parameters={
        "type": "object",
        "properties": changed_properties,
        "required": list(original.parameters.get("required") or []),
    })
    before = {c.family: c for c in derive_cards(base)}
    after = {c.family: c for c in derive_cards(
        _default_with({"list_campaigns": changed}))}
    assert before[Topic.CAMPAIGN.value].digest != \
        after[Topic.CAMPAIGN.value].digest
    before_tool = next(
        tool for tool in before[Topic.CAMPAIGN.value].tools
        if tool.name == "list_campaigns")
    after_tool = next(
        tool for tool in after[Topic.CAMPAIGN.value].tools
        if tool.name == "list_campaigns")
    assert before_tool.arguments == after_tool.arguments
    assert before_tool.schema_digest != after_tool.schema_digest


def test_adding_and_removing_a_tool_changes_the_digest():
    base = build_default_tool_registry()
    before = derive_cards(base)
    registry = ToolRegistry()
    for name in base.names():
        registry.register(base.get(name))
    registry.register(_tool("list_campaigns_extra"))
    after = derive_cards(registry)
    assert catalog_digest(before) != catalog_digest(after)


def test_read_only_card_when_all_tools_are_read_only():
    registry = _registry_with(_tool("list_campaigns"))
    (card,) = derive_cards(registry)
    assert card.read_only is True
    assert card.family == Topic.CAMPAIGN.value


# ---------------------------------------------------------------------------
# Bounded argument summary
# ---------------------------------------------------------------------------

def test_argument_summary_is_bounded_and_content_free():
    properties = {
        f"argument_{index}": {"type": "string", "description": "x" * 500}
        for index in range(MAX_CARD_ARGUMENTS + 8)
    }
    registry = _registry_with(_tool(
        "list_campaigns", properties=properties,
        required=["argument_0"]))
    (card,) = derive_cards(registry)
    tool = card.tools[0]
    assert len(tool.arguments) == MAX_CARD_ARGUMENTS
    assert tool.arguments_truncated is True
    assert tool.required_arguments == ("argument_0",)
    assert len(tool.schema_digest) == 64
    # Only argument NAMES are summarized; parameter descriptions/types are
    # never copied into the card.
    import json
    rendered = json.dumps(card.payload())
    assert "x" * 500 not in rendered
    assert "parameters" not in card.payload()["tools"][0]
