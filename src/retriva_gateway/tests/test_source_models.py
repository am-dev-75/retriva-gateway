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

"""Tests for source domain models and MediaWiki config validation."""

import unittest
from pydantic import ValidationError

from retriva_gateway.core.source_models import (
    MediaWikiSourceConfig,
    SourceInstance,
    SourceRun,
    SourceCheckpoint,
    SourceItemState,
    SourceResponse,
    SourceRunResponse,
    SourceStatus,
    SyncMode,
    ConnectorType,
    RunPhase,
    RunStatus,
    ItemStatus,
    AuthMode,
    DeletePolicy,
    AvailabilityPolicy,
)


class TestMediaWikiSourceConfig(unittest.TestCase):
    """Validate MediaWiki connector config schema."""

    def _valid_config(self, **overrides):
        defaults = {
            "api_url": "https://mediawiki.company.local/api.php",
            "auth_mode": "bot_password",
            "allowed_namespaces": [0, 100],
            "sync_interval_minutes": 15,
        }
        defaults.update(overrides)
        return defaults

    def test_valid_config(self):
        cfg = MediaWikiSourceConfig(**self._valid_config())
        self.assertEqual(cfg.api_url, "https://mediawiki.company.local/api.php")
        self.assertEqual(cfg.auth_mode, AuthMode.BOT_PASSWORD)
        self.assertEqual(cfg.delete_policy, DeletePolicy.SOFT_DELETE)

    def test_missing_api_url_raises(self):
        with self.assertRaises(ValidationError):
            MediaWikiSourceConfig(auth_mode="none")

    def test_empty_api_url_raises(self):
        with self.assertRaises(ValidationError):
            MediaWikiSourceConfig(**self._valid_config(api_url=""))

    def test_api_url_no_protocol_raises(self):
        with self.assertRaises(ValidationError):
            MediaWikiSourceConfig(**self._valid_config(api_url="mediawiki.local/api.php"))

    def test_invalid_auth_mode_raises(self):
        with self.assertRaises(ValidationError):
            MediaWikiSourceConfig(**self._valid_config(auth_mode="kerberos"))

    def test_sync_interval_too_low_raises(self):
        with self.assertRaises(ValidationError):
            MediaWikiSourceConfig(**self._valid_config(sync_interval_minutes=0))

    def test_sync_interval_too_high_raises(self):
        with self.assertRaises(ValidationError):
            MediaWikiSourceConfig(**self._valid_config(sync_interval_minutes=2000))

    def test_defaults_applied(self):
        cfg = MediaWikiSourceConfig(api_url="https://wiki.local/api.php")
        self.assertEqual(cfg.auth_mode, AuthMode.NONE)
        self.assertEqual(cfg.allowed_namespaces, [0])
        self.assertEqual(cfg.sync_interval_minutes, 15)
        self.assertEqual(cfg.delete_policy, DeletePolicy.SOFT_DELETE)
        self.assertEqual(cfg.availability_policy, AvailabilityPolicy.HIDE_UNTIL_INITIAL_SYNC_COMPLETE)

    def test_http_url_accepted(self):
        cfg = MediaWikiSourceConfig(api_url="http://internal-wiki:8080/api.php")
        self.assertEqual(cfg.api_url, "http://internal-wiki:8080/api.php")


class TestSourceInstance(unittest.TestCase):
    """Validate SourceInstance defaults and ID generation."""

    def test_defaults(self):
        src = SourceInstance(
            connector_type=ConnectorType.MEDIAWIKI,
            display_name="Test Wiki",
            target_kb_id="test_kb",
        )
        self.assertTrue(src.source_id.startswith("src_"))
        self.assertEqual(src.tenant_id, "internal-company")
        self.assertEqual(src.status, SourceStatus.BASELINE_PENDING)
        self.assertEqual(src.sync_mode, SyncMode.BASELINE)
        self.assertIsNotNone(src.created_at)
        self.assertIsNotNone(src.updated_at)

    def test_unique_ids(self):
        ids = set()
        for _ in range(100):
            src = SourceInstance(
                connector_type=ConnectorType.MEDIAWIKI,
                display_name="Test",
                target_kb_id="kb",
            )
            ids.add(src.source_id)
        self.assertEqual(len(ids), 100)


class TestSourceResponse(unittest.TestCase):
    """Validate SourceResponse redacts secret_ref."""

    def test_secret_ref_redacted(self):
        src = SourceInstance(
            connector_type=ConnectorType.MEDIAWIKI,
            display_name="Test",
            target_kb_id="kb",
            secret_ref="secret://retriva/m1/mediawiki/test",
        )
        resp = SourceResponse.from_source(src)
        self.assertTrue(resp.has_secret)
        self.assertFalse(hasattr(resp, "secret_ref"))
        # Ensure the raw value is not in the serialized output
        serialized = resp.model_dump()
        self.assertNotIn("secret_ref", serialized)
        self.assertTrue(serialized["has_secret"])

    def test_no_secret(self):
        src = SourceInstance(
            connector_type=ConnectorType.MEDIAWIKI,
            display_name="Test",
            target_kb_id="kb",
        )
        resp = SourceResponse.from_source(src)
        self.assertFalse(resp.has_secret)


class TestSourceRunResponse(unittest.TestCase):
    """Validate SourceRunResponse from_run."""

    def test_from_run(self):
        run = SourceRun(source_id="src_test", phase=RunPhase.BASELINE_SCAN)
        resp = SourceRunResponse.from_run(run)
        self.assertEqual(resp.source_id, "src_test")
        self.assertEqual(resp.phase, RunPhase.BASELINE_SCAN)
        self.assertEqual(resp.status, RunStatus.PENDING)
        self.assertIsNone(resp.finished_at)


class TestSourceEnums(unittest.TestCase):
    """Validate enum values match the spec."""

    def test_source_statuses(self):
        expected = {
            "CREATED", "VALIDATING_CONNECTION", "BASELINE_PENDING",
            "BASELINE_RUNNING", "CATCHUP_RUNNING", "ACTIVE",
            "PAUSED", "DEGRADED", "FAILED", "DELETING", "DELETED",
        }
        self.assertEqual({s.value for s in SourceStatus}, expected)

    def test_connector_types(self):
        self.assertIn("mediawiki", [ct.value for ct in ConnectorType])


if __name__ == "__main__":
    unittest.main()
