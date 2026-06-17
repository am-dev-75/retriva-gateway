# Retriva Gateway Dynamic Ingestion — Antigravity SDD Pack

This pack is intended to be copied into the **retriva-gateway** repository root and used with Google Antigravity / Antigravity IDE as a Spec-Driven Development (SDD) kit.

It defines a `/define -> /architect -> /execute -> /verify` flow to add **dynamic ingestion support** to Retriva Gateway, initially for MediaWiki-backed connected sources and later extensible to SharePoint, OneDrive, Google Drive, SFTP, and other connectors.

## What this pack assumes

Retriva architecture:

- **Retriva WebUI**: user-facing interface.
- **Retriva Gateway**: control-plane/BFF layer between WebUI and Core.
- **Retriva Core**: data plane/system of record for ingestion, metadata, KB assignment, chunks, retrieval, ranking, and LLM request construction.
- **Dynamic connectors**: background source-sync adapters managed through Gateway and feeding Core's normal ingestion pipeline.

## Install into an existing repository

From the root of `retriva-gateway`:

```bash
unzip retriva-gateway-dynamic-ingestion-sdd-pack.zip -d /tmp/retriva-sdd
cp -r /tmp/retriva-sdd/retriva-gateway-dynamic-ingestion-sdd-pack/.agent .
cp -r /tmp/retriva-sdd/retriva-gateway-dynamic-ingestion-sdd-pack/memory .
cp -r /tmp/retriva-sdd/retriva-gateway-dynamic-ingestion-sdd-pack/specs .
cp -r /tmp/retriva-sdd/retriva-gateway-dynamic-ingestion-sdd-pack/templates .
cp -r /tmp/retriva-sdd/retriva-gateway-dynamic-ingestion-sdd-pack/prompts .
```

Then open the repository in Antigravity and run the flow:

```text
/define specs/dynamic-ingestion-gateway/feature-brief.md
/architect specs/dynamic-ingestion-gateway/spec.md
/execute specs/dynamic-ingestion-gateway/plan.md
/verify specs/dynamic-ingestion-gateway/verification.md
```

If your Antigravity installation does not auto-register custom slash commands from `.agent/workflows`, paste the corresponding workflow prompt manually from `.agent/workflows/*.md`.

## Deliverables expected from the agent

1. Gateway API endpoints for dynamic source management.
2. Source lifecycle/state model.
3. Connector Manager abstraction.
4. MediaWiki source baseline + catch-up + incremental sync orchestration.
5. Gateway-to-Core ingestion session design.
6. Status/run APIs for WebUI.
7. Security controls: no content logging, secret refs only, RBAC hooks, allowlisted connector types.
8. Tests and verification artifacts.

## Non-goals for the first implementation

- Full connector marketplace.
- Real-time push synchronization.
- Customer self-service OAuth flows.
- SharePoint/Google Drive connector implementations.
- Per-page permission-aware retrieval.
- Direct connector access to Qdrant.
