# Retriva Gateway

Backend-for-Frontend (BFF) service for Retriva WebUI. It sits between the browser and Retriva Core services.

See https://github.com/am-dev-75/retriva for the core project.

## API

API is documented [here](docs/openapi.yaml).

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
Create a `.env` file or set environment variables:
```env
RETRIVA_CORE_INGESTION_URL=http://localhost:8000
RETRIVA_CORE_CHAT_URL=http://localhost:8001
GATEWAY_PORT=8080
```

### 3. Run the gateway
```bash
PYTHONPATH=src python3 -m retriva_gateway.main
```

The API will be available at `http://localhost:8080/gateway`.
OpenAPI documentation is available at `http://localhost:8080/docs`.

## Tests
```bash
PYTHONPATH=src pytest
```

## Chat tools

The gateway executes the CRM Assistant chat tools in a bounded
agent loop (enabled per request via `tools_enabled` + `session_id`;
`AGENT_TOOLS_ENABLED` gates the layer, `AGENT_TOOL_ALLOWLIST` bounds
it). Registered workflows: qualification, ERP import review/commit,
campaign tracking, and the PostgreSQL ACP workflow (15 tools — see
`retriva-crm-assistant/docs/acp-chat-tools.md` and ADR-023). Tool
handlers proxy the CRM API with the authenticated principal
(`X-Retriva-User`, built gateway-side); the model never generates SQL
and tools stop at every human-review boundary.

## Licensing

This project, including all source code, agentic specifications, and documentation, is licensed under the Apache License 2.0. See the LICENSE file for details.