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

"""Tests for the Connected Sources API (dynamic ingestion).

Covers:
- Source CRUD
- MediaWiki config validation
- Unsupported connector rejection
- Pause/resume lifecycle
- Manual sync run creation
- First-sync lifecycle transitions (internal endpoints)
- Internal endpoint auth
- Secret redaction
"""

import unittest
import shutil
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient

from retriva_gateway.main import app
from retriva_gateway.core.json_source_repository import (
    source_repo,
    run_repo,
    checkpoint_repo,
    item_state_repo,
)


def _valid_create_payload(**overrides):
    payload = {
        "connector_type": "mediawiki",
        "display_name": "Test MediaWiki",
        "target_kb_id": "test_kb",
        "config": {
            "api_url": "https://wiki.company.local/api.php",
            "auth_mode": "bot_password",
            "allowed_namespaces": [0, 100],
            "sync_interval_minutes": 15,
        },
        "secret_ref": "secret://retriva/m1/mediawiki/test",
    }
    payload.update(overrides)
    return payload


class _SourceTestBase(unittest.TestCase):
    """Base test class that isolates JSON storage per test."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.settings_patcher = patch(
            "retriva_gateway.core.json_source_repository.settings"
        )
        self.mock_settings = self.settings_patcher.start()
        self.mock_settings.DYNAMIC_INGESTION_DATA_DIR = self.tmp_dir

        self.api_settings_patcher = patch(
            "retriva_gateway.api.v2.sources.settings"
        )
        self.mock_api_settings = self.api_settings_patcher.start()
        self.mock_api_settings.DYNAMIC_INGESTION_ENABLED = True
        self.mock_api_settings.DEFAULT_TENANT_ID = "internal-company"
        self.mock_api_settings.ALLOWED_CONNECTOR_TYPES = ["mediawiki"]

        self.internal_settings_patcher = patch(
            "retriva_gateway.api.internal.sources.settings"
        )
        self.mock_internal_settings = self.internal_settings_patcher.start()
        self.mock_internal_settings.GATEWAY_INTERNAL_SERVICE_TOKEN = ""

        self.connector_settings_patcher = patch(
            "retriva_gateway.core.connector_manager.settings"
        )
        self.mock_connector_settings = self.connector_settings_patcher.start()
        self.mock_connector_settings.ALLOWED_CONNECTOR_TYPES = ["mediawiki"]

        self.client = TestClient(app)

    def tearDown(self):
        self.settings_patcher.stop()
        self.api_settings_patcher.stop()
        self.internal_settings_patcher.stop()
        self.connector_settings_patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_source(self, **overrides):
        return self.client.post("/gateway/sources", json=_valid_create_payload(**overrides))


class TestSourceCrud(_SourceTestBase):
    """CRUD operations on connected sources."""

    def test_create_mediawiki_source(self):
        r = self._create_source()
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertTrue(body["source_id"].startswith("src_"))
        self.assertEqual(body["connector_type"], "mediawiki")
        self.assertEqual(body["status"], "BASELINE_PENDING")
        self.assertEqual(body["sync_mode"], "baseline")
        self.assertEqual(body["tenant_id"], "internal-company")

    def test_reject_unsupported_connector(self):
        r = self._create_source(connector_type="sharepoint")
        self.assertEqual(r.status_code, 422)

    def test_reject_invalid_mediawiki_url(self):
        r = self._create_source(config={
            "api_url": "not-a-url",
            "auth_mode": "none",
        })
        self.assertEqual(r.status_code, 422)

    def test_secret_ref_not_in_response(self):
        r = self._create_source()
        body = r.json()
        self.assertTrue(body["has_secret"])
        self.assertNotIn("secret_ref", body)

    def test_list_sources(self):
        self._create_source(display_name="Source 1")
        self._create_source(display_name="Source 2")
        r = self.client.get("/gateway/sources")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)

    def test_get_source(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.get(f"/gateway/sources/{source_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["source_id"], source_id)

    def test_get_source_not_found(self):
        r = self.client.get("/gateway/sources/src_nonexistent")
        self.assertEqual(r.status_code, 404)

    def test_update_source(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.patch(f"/gateway/sources/{source_id}", json={
            "display_name": "Updated Name",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["display_name"], "Updated Name")

    def test_update_source_config_revalidated(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.patch(f"/gateway/sources/{source_id}", json={
            "config": {"api_url": "no-protocol"},
        })
        self.assertEqual(r.status_code, 422)

    def test_delete_source(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.delete(f"/gateway/sources/{source_id}")
        self.assertEqual(r.status_code, 204)
        # Source should now be DELETED
        r2 = self.client.get(f"/gateway/sources/{source_id}")
        self.assertEqual(r2.json()["status"], "DELETED")


class TestSourceLifecycle(_SourceTestBase):
    """Pause, resume, and manual sync lifecycle."""

    def test_pause_active_source(self):
        """A source in BASELINE_PENDING can be paused."""
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.post(f"/gateway/sources/{source_id}/pause")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "PAUSED")

    def test_resume_paused_source(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        self.client.post(f"/gateway/sources/{source_id}/pause")
        r = self.client.post(f"/gateway/sources/{source_id}/resume")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "BASELINE_PENDING")

    def test_pause_deleted_source_returns_409(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        self.client.delete(f"/gateway/sources/{source_id}")
        r = self.client.post(f"/gateway/sources/{source_id}/pause")
        self.assertEqual(r.status_code, 409)

    def test_resume_non_paused_returns_409(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.post(f"/gateway/sources/{source_id}/resume")
        self.assertEqual(r.status_code, 409)

    def test_manual_sync_creates_run(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.post(f"/gateway/sources/{source_id}/sync")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["run_id"].startswith("run_"))
        self.assertEqual(body["source_id"], source_id)
        self.assertEqual(body["phase"], "baseline_scan")
        self.assertEqual(body["status"], "pending")

    def test_sync_deleted_source_returns_409(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        self.client.delete(f"/gateway/sources/{source_id}")
        r = self.client.post(f"/gateway/sources/{source_id}/sync")
        self.assertEqual(r.status_code, 409)


class TestSourceStatus(_SourceTestBase):
    """Status and run queries."""

    def test_get_source_status(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.get(f"/gateway/sources/{source_id}/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "BASELINE_PENDING")
        self.assertIsNone(body["latest_run"])

    def test_get_source_status_with_run(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        self.client.post(f"/gateway/sources/{source_id}/sync")
        r = self.client.get(f"/gateway/sources/{source_id}/status")
        body = r.json()
        self.assertIsNotNone(body["latest_run"])

    def test_list_runs(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        self.client.post(f"/gateway/sources/{source_id}/sync")
        self.client.post(f"/gateway/sources/{source_id}/sync")
        r = self.client.get(f"/gateway/sources/{source_id}/runs")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)

    def test_get_single_run(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]
        r = self.client.get(f"/gateway/sources/{source_id}/runs/{run_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["run_id"], run_id)


class TestFirstSyncLifecycle(_SourceTestBase):
    """Test the first-sync state machine via internal endpoints."""

    def test_baseline_to_catchup_to_active(self):
        """Complete run transitions: baseline → catchup → active."""
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]

        # Start baseline sync
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        # Complete baseline → should transition to catchup
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/complete",
            json={"status": "completed"},
        )
        source = self.client.get(f"/gateway/sources/{source_id}").json()
        self.assertEqual(source["sync_mode"], "catchup")
        self.assertEqual(source["status"], "CATCHUP_RUNNING")

        # Start catchup sync
        sync_r2 = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id2 = sync_r2.json()["run_id"]

        # Complete catchup → should transition to incremental / ACTIVE
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id2}/complete",
            json={
                "status": "completed",
                "checkpoint": {
                    "checkpoint_type": "mediawiki_recentchanges",
                    "last_seen_rcid": 12345,
                },
            },
        )
        source = self.client.get(f"/gateway/sources/{source_id}").json()
        self.assertEqual(source["sync_mode"], "incremental")
        self.assertEqual(source["status"], "ACTIVE")

    def test_checkpoint_saved_after_catchup(self):
        """Checkpoint is only saved when run completes successfully."""
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]

        # Start + complete baseline
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/complete",
            json={"status": "completed"},
        )

        # Status should show no checkpoint yet (baseline didn't include one)
        status = self.client.get(f"/gateway/sources/{source_id}/status").json()
        self.assertFalse(status["has_checkpoint"])

        # Start + complete catchup with checkpoint
        sync_r2 = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id2 = sync_r2.json()["run_id"]
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id2}/complete",
            json={
                "status": "completed",
                "checkpoint": {
                    "checkpoint_type": "mediawiki_recentchanges",
                    "last_seen_rcid": 99999,
                },
            },
        )

        status = self.client.get(f"/gateway/sources/{source_id}/status").json()
        self.assertTrue(status["has_checkpoint"])

    def test_failed_run_sets_source_failed(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/complete",
            json={"status": "failed", "error_code": "CONN_REFUSED"},
        )
        source = self.client.get(f"/gateway/sources/{source_id}").json()
        self.assertEqual(source["status"], "FAILED")


class TestInternalEndpoints(_SourceTestBase):
    """Internal worker endpoint tests."""

    def test_heartbeat(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/heartbeat",
            json={"processed_items": 42},
        )
        self.assertEqual(r.status_code, 200)

    def test_events_upsert_items(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/events",
            json={
                "events": [
                    {
                        "source_item_id": "mediawiki:rdwiki:page:1",
                        "source_revision": "100",
                        "content_hash": "sha256:abc",
                        "status": "indexed",
                    },
                    {
                        "source_item_id": "mediawiki:rdwiki:page:2",
                        "source_revision": "101",
                        "content_hash": "sha256:def",
                        "status": "indexed",
                    },
                ]
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["processed"], 2)

        # Verify items visible
        items_r = self.client.get(f"/gateway/sources/{source_id}/items")
        self.assertEqual(len(items_r.json()), 2)

    def test_idempotent_item_upsert(self):
        """Same source_item_id + revision → single record."""
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        event = {
            "source_item_id": "mediawiki:rdwiki:page:1",
            "source_revision": "100",
            "content_hash": "sha256:abc",
            "status": "indexed",
        }
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/events",
            json={"events": [event]},
        )
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/events",
            json={"events": [event]},
        )

        items_r = self.client.get(f"/gateway/sources/{source_id}/items")
        self.assertEqual(len(items_r.json()), 1)

    def test_ingestion_session(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/ingestion-session"
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["kb_id"], "test_kb")
        self.assertEqual(body["tenant_id"], "internal-company")

    def test_internal_auth_required_when_configured(self):
        """When service token is set, missing header returns 401."""
        self.mock_internal_settings.GATEWAY_INTERNAL_SERVICE_TOKEN = "secret-token-123"

        create_r = self._create_source()
        source_id = create_r.json()["source_id"]

        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/ingestion-session"
        )
        self.assertEqual(r.status_code, 401)

    def test_internal_auth_passes_with_valid_token(self):
        self.mock_internal_settings.GATEWAY_INTERNAL_SERVICE_TOKEN = "secret-token-123"

        create_r = self._create_source()
        source_id = create_r.json()["source_id"]

        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/ingestion-session",
            headers={"X-Service-Token": "secret-token-123"},
        )
        self.assertEqual(r.status_code, 200)

    def test_get_checkpoint_not_found(self):
        """Valid token but no checkpoint returns 404."""
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        
        r = self.client.get(
            f"/gateway/internal/sources/{source_id}/checkpoint"
        )
        self.assertEqual(r.status_code, 404)

    def test_get_checkpoint_success(self):
        """Checkpoint written by complete endpoint can be retrieved."""
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        checkpoint_data = {
            "checkpoint_type": "mediawiki_recentchanges",
            "last_seen_rcid": 12345,
            "cursor": {"rcid": 12345}
        }

        # complete run and save checkpoint
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/complete",
            json={"status": "completed", "checkpoint": checkpoint_data}
        )

        r = self.client.get(
            f"/gateway/internal/sources/{source_id}/checkpoint"
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["source_id"], source_id)
        self.assertEqual(body["checkpoint_type"], "mediawiki_recentchanges")
        self.assertEqual(body["last_seen_rcid"], 12345)
        self.assertEqual(body["cursor"], {"rcid": 12345})
        self.assertNotIn("secret_ref", body)

    def test_get_checkpoint_auth_required(self):
        self.mock_internal_settings.GATEWAY_INTERNAL_SERVICE_TOKEN = "secret-token-123"

        create_r = self._create_source()
        source_id = create_r.json()["source_id"]

        r = self.client.get(
            f"/gateway/internal/sources/{source_id}/checkpoint"
        )
        self.assertEqual(r.status_code, 401)

    def test_get_checkpoint_unknown_source(self):
        r = self.client.get("/gateway/internal/sources/src_unknown/checkpoint")
        self.assertEqual(r.status_code, 404)


class TestDisabledDynamicIngestion(_SourceTestBase):
    """Feature-gated: all source endpoints should return 503."""

    def test_create_returns_503_when_disabled(self):
        self.mock_api_settings.DYNAMIC_INGESTION_ENABLED = False
        r = self._create_source()
        self.assertEqual(r.status_code, 503)

    def test_list_returns_503_when_disabled(self):
        self.mock_api_settings.DYNAMIC_INGESTION_ENABLED = False
        r = self.client.get("/gateway/sources")
        self.assertEqual(r.status_code, 503)


class TestV2RoutePrefix(_SourceTestBase):
    """Verify /api/v2/sources also works."""

    def test_v2_create_source(self):
        r = self.client.post("/api/v2/sources", json=_valid_create_payload())
        self.assertEqual(r.status_code, 201)

    def test_v2_list_sources(self):
        self.client.post("/api/v2/sources", json=_valid_create_payload())
        r = self.client.get("/api/v2/sources")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()), 1)


class TestIdempotentSourceCreation(_SourceTestBase):
    """§8: Idempotent source creation by client-provided key."""

    def test_idempotent_create_returns_same_source(self):
        payload = _valid_create_payload(idempotency_key="idem-key-1")
        r1 = self.client.post("/gateway/sources", json=payload)
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post("/gateway/sources", json=payload)
        # Second call returns the same source (200, not 201, from FastAPI perspective
        # but the body is identical)
        self.assertEqual(r2.json()["source_id"], r1.json()["source_id"])

    def test_different_keys_create_different_sources(self):
        r1 = self.client.post("/gateway/sources", json=_valid_create_payload(
            idempotency_key="key-a",
        ))
        r2 = self.client.post("/gateway/sources", json=_valid_create_payload(
            idempotency_key="key-b",
        ))
        self.assertNotEqual(r1.json()["source_id"], r2.json()["source_id"])

    def test_no_key_always_creates_new(self):
        r1 = self._create_source()
        r2 = self._create_source()
        self.assertNotEqual(r1.json()["source_id"], r2.json()["source_id"])


class TestPagination(_SourceTestBase):
    """§8: Pagination on list endpoints."""

    def test_list_sources_pagination(self):
        for i in range(5):
            self._create_source(display_name=f"Source {i}")
        # Default returns all 5 (limit=50)
        r = self.client.get("/gateway/sources")
        self.assertEqual(len(r.json()), 5)
        # Limit 2
        r = self.client.get("/gateway/sources?limit=2")
        self.assertEqual(len(r.json()), 2)
        # Offset 3
        r = self.client.get("/gateway/sources?offset=3")
        self.assertEqual(len(r.json()), 2)
        # Limit 2 + offset 4
        r = self.client.get("/gateway/sources?limit=2&offset=4")
        self.assertEqual(len(r.json()), 1)

    def test_list_runs_pagination(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        for _ in range(3):
            self.client.post(f"/gateway/sources/{source_id}/sync")
        r = self.client.get(f"/gateway/sources/{source_id}/runs?limit=2")
        self.assertEqual(len(r.json()), 2)

    def test_list_items_pagination(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]
        events = [
            {"source_item_id": f"page:{i}", "status": "indexed"}
            for i in range(5)
        ]
        self.client.post(
            f"/gateway/internal/sources/{source_id}/runs/{run_id}/events",
            json={"events": events},
        )
        r = self.client.get(f"/gateway/sources/{source_id}/items?limit=3")
        self.assertEqual(len(r.json()), 3)


class TestIngestionSessionRunScope(_SourceTestBase):
    """§4.2: Ingestion session optionally scoped to a run."""

    def test_ingestion_session_with_run_id(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]
        sync_r = self.client.post(f"/gateway/sources/{source_id}/sync")
        run_id = sync_r.json()["run_id"]

        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/ingestion-session",
            json={"run_id": run_id},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["run_id"], run_id)
        self.assertEqual(body["batch_metadata"]["run_id"], run_id)

    def test_ingestion_session_without_run_id(self):
        create_r = self._create_source()
        source_id = create_r.json()["source_id"]

        r = self.client.post(
            f"/gateway/internal/sources/{source_id}/ingestion-session",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNone(body["run_id"])
        self.assertNotIn("run_id", body["batch_metadata"])


if __name__ == "__main__":
    unittest.main()
