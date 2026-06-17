# Dynamic Ingestion Sequence

## Source creation

```text
WebUI -> Gateway: POST /gateway/sources
Gateway -> Gateway: validate user, connector type, config, target KB
Gateway -> SecretStore: store/associate credentials or validate secret_ref
Gateway -> SourceRepository: persist SourceInstance(BASELINE_PENDING)
Gateway -> WebUI: SourceResponse
```

## First sync

```text
WebUI -> Gateway: POST /gateway/sources/{id}/sync
Gateway -> SourceRunRepository: create run(BASELINE_PENDING)
Gateway -> ConnectorManager: enqueue run
ConnectorManager -> MediaWikiConnector: start baseline
MediaWikiConnector -> Gateway/Internal: heartbeat/events
MediaWikiConnector -> Gateway/Core: submit dynamic ingestion documents
MediaWikiConnector -> Gateway/Internal: save checkpoint and complete run
Gateway -> SourceRepository: status ACTIVE after catch-up
```

## Incremental sync

```text
Scheduler -> ConnectorManager: due source
ConnectorManager -> MediaWikiConnector: incremental run
MediaWikiConnector -> MediaWiki: recentchanges since checkpoint
MediaWikiConnector -> Gateway/Core: upsert/delete changed documents
MediaWikiConnector -> Gateway/Internal: update checkpoint
```
