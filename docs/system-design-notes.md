# System Design Notes

## Assessment Scope

This repository is intentionally optimized for an assessment-friendly MVP:

- single-user desktop operator workflow
- file-backed dataset ingestion
- deterministic demo data for repeatable review
- transparent rule-based analytics
- headless validation and reporting for CI and reviewer walkthroughs

The design avoids infrastructure that would add operational overhead without materially improving the submission.

## Key Architectural Decisions

### 1. Shared Core, Multiple Entry Points

The desktop shell and CLI both sit on top of the same application services.

Why:

- avoids duplicated business logic
- keeps automated verification aligned with operator behavior
- makes CI useful, not cosmetic

### 2. File-Backed Dataset Workspace

Datasets are discovered from `data/demo/`, `data/imports/`, and `data/runtime/datasets/`.

Why:

- dead simple to reason about locally
- easy for reviewers to inspect
- supports staged import, validation, and promotion without extra infrastructure

Trade-off:

- suitable for bounded datasets, not unbounded streaming ingestion

### 3. Indexed In-Memory Read Models

Station and telemetry repositories are optimized for read-heavy operator workflows.

Why:

- desktop interaction needs fast filter, latest-value, and time-window queries
- assessment datasets fit comfortably in memory
- repository contracts leave room for future persistence backends

Trade-off:

- not the final answer for very large historical datasets

### 4. Transparent Rules Before Machine Learning

Threshold alerts and bounded anomaly detection drive the product behavior.

Why:

- explainable in interviews and code reviews
- debuggable by operators
- deterministic enough for tests and CI

Trade-off:

- subtler failure modes may still require richer modeling later

### 5. View Models At The UI Boundary

The presentation layer consumes prepared view models rather than raw repositories.

Why:

- keeps Tkinter code straightforward
- localizes formatting and status text
- makes it easier to swap the UI technology later

## Reliability Notes

Current reliability mechanisms:

- strict row-level parser validation
- import promotion only after successful parsing
- runtime dataset isolation
- deterministic demo dataset generation
- automated test coverage for ingestion, analytics, and CLI flows
- GitHub Actions validation and report generation

The system is intentionally defensive around bad input because operator trust depends on ingestion clarity as much as analytics accuracy.

## Performance Notes

Expected hot paths today:

- explorer filtering and sorting
- latest telemetry retrieval
- recent history chart rendering
- active anomaly and alert summaries

Current mitigations:

- repository indexing
- query result caching
- prebuilt fleet snapshot rollups
- station detail caching inside the desktop shell

## Security And Operations Notes

Out of scope for the assessment, but important in a real deployment:

- user authentication and authorization
- audit trail for import actions and dataset switching
- signed or checksum-verified import bundles
- alert acknowledgment persistence
- encrypted storage for sensitive telemetry feeds

The current structure leaves clear insertion points for those concerns, especially around dataset workspace operations and future service/API boundaries.

## Recommended Next Production Steps

1. Introduce a persistent metadata store for datasets, imports, and operator actions.
2. Add an API boundary so multiple operators can view the same fleet state.
3. Move telemetry history into a time-series database while preserving repository contracts.
4. Add scheduled import jobs and notification hooks.
5. Version threshold and anomaly policies separately from code.

## Non-Goals For This Repo

The repository deliberately does not attempt to solve:

- real-time distributed stream processing
- multi-tenant access control
- long-term archival storage
- HA desktop synchronization across operators
- dynamic configuration UIs for policy management

Those are valid future concerns, but they would distract from the assessment objective: a clear, scalable, well-structured operator telemetry MVP.
