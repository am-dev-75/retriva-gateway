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

import asyncio
import unittest
from unittest.mock import patch, MagicMock
from retriva_gateway.core.filters import FilterManager
from retriva_gateway.core.models import MetadataFilterMode, MetadataFilter

class TestFilterManager(unittest.TestCase):
    @patch("retriva_gateway.core.client.core_client.get_metadata_schema")
    def test_normalize_v2_dict(self, mock_get_schema):
        mock_get_schema.return_value = {"fields": [{"field": "project"}]}
        filters = {"project": "apollo", "language": {"operator": "exists"}}
        
        loop = asyncio.get_event_loop()
        normalized = loop.run_until_complete(FilterManager.normalize_v2(filters))
        
        expected = [
            {"field": "user_metadata.project", "operator": "eq", "value": "apollo"},
            {"field": "language", "operator": "exists", "value": None}
        ]
        
        normalized_set = {(f["field"], f["operator"], f.get("value")) for f in normalized}
        expected_set = {(f["field"], f["operator"], f.get("value")) for f in expected}
        self.assertEqual(normalized_set, expected_set)

    @patch("retriva_gateway.core.client.core_client.get_metadata_schema")
    def test_normalize_v2_list(self, mock_get_schema):
        mock_get_schema.return_value = {"fields": [{"field": "project"}]}
        filters = [
            MetadataFilter(field="project", operator="eq", value="apollo"),
            {"field": "language", "operator": "exists"}
        ]
        
        loop = asyncio.get_event_loop()
        normalized = loop.run_until_complete(FilterManager.normalize_v2(filters))
        
        expected = [
            {"field": "user_metadata.project", "operator": "eq", "value": "apollo"},
            {"field": "language", "operator": "exists", "value": None}
        ]
        
        normalized_set = {(f["field"], f["operator"], f.get("value")) for f in normalized}
        expected_set = {(f["field"], f["operator"], f.get("value")) for f in expected}
        self.assertEqual(normalized_set, expected_set)

    def test_validate_mode(self):
        self.assertEqual(FilterManager.validate_mode("soft"), "soft")
        self.assertEqual(FilterManager.validate_mode(MetadataFilterMode.HARD), "hard")
        with self.assertRaises(ValueError):
            FilterManager.validate_mode("invalid")

    @patch("retriva_gateway.core.client.core_client.get_metadata_schema")
    def test_normalize_v2_unsupported_operator(self, mock_get_schema):
        mock_get_schema.return_value = {"fields": []}
        filters = {"project": {"operator": "invalid", "value": "val"}}
        
        loop = asyncio.get_event_loop()
        normalized = loop.run_until_complete(FilterManager.normalize_v2(filters))
        self.assertEqual(normalized[0]["operator"], "eq")

if __name__ == "__main__":
    unittest.main()
