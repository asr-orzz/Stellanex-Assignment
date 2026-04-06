# Video Walkthrough

Add your final 2-5 minute walkthrough link here before submission.

# Stellanex Grid Telemetry Console

An operator-focused desktop telemetry workbench for monitoring hundreds of municipal power sub-stations without manually combing through raw device logs.

## Problem Definition

The brief describes an engineering team that is overwhelmed by raw telemetry and lacks a shared operational view of station health. The MVP for this repository will focus on three user needs:

1. Surface abnormal stations quickly instead of forcing engineers to inspect every raw log.
2. Show telemetry trends in enough context to support diagnosis.
3. Keep the codebase modular enough that ingestion rules, analytics, and the desktop interface can evolve independently.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
python -m stellanex_telemetry
pytest
```

The package now exposes both the desktop shell and headless CLI workflows. Running `python -m stellanex_telemetry` still opens the desktop experience by default, while `validate` and `report` provide automation-friendly commands for ingestion checks and fleet summaries.

### Runtime Layout

The application resolves paths from the repository root and uses the following layout:

- `data/demo/`: deterministic bundled datasets for local development and demos.
- `data/imports/`: operator-provided CSV drops that will be parsed by the ingestion layer.
- `data/runtime/`: generated runtime artifacts such as exports, caches, and logs.

You can override the defaults with environment variables when needed:

```bash
set STELLANEX_DATA_DIR=C:\path\to\data
set STELLANEX_RUNTIME_DIR=C:\path\to\runtime
```

## Technical Architecture

The codebase is being structured as a layered Python application:

- `domain`: core entities and invariants for substations, telemetry readings, alerts, and fleet state.
- `application`: orchestration and analytics services that transform raw telemetry into operator-facing insights.
- `infrastructure`: file-backed ingestion, sample datasets, and future adapters for external sources.
- `presentation`: the desktop UI and view models that render the analyzed fleet state.

This separation keeps business logic independent from the UI so the analytics layer can be tested headlessly and reused by a CLI or future API.

## Current Operator Workflow

1. Launch the desktop shell with `python -m stellanex_telemetry`.
2. Review the live demo dataset in the fleet overview, alert inbox, station explorer, and trend insight deck.
3. Stage new import-ready data under `data/imports/`, then use `Import Staged` from the shell's dataset control card.
4. Switch the active dataset from the catalog selector and use `Refresh Active` when files on disk change.

## CLI Workflows

Use the same package for headless validation and report generation:

```bash
python -m stellanex_telemetry validate --dataset demo
python -m stellanex_telemetry report --dataset demo --format json --output data/runtime/exports/demo_report.json
python -m stellanex_telemetry validate --source data/imports/my_drop
python -m stellanex_telemetry report --source data/demo --top-stations 3
```

The `validate` command returns a non-zero exit code when dataset errors are present, which makes it suitable for CI or submission-time checks. The `report` command emits a fleet summary in text or JSON without requiring a desktop session.

## CI Workflow

GitHub Actions now runs an automated CI pipeline on every push, on pull requests to `main`, and on manual dispatch:

- installs the package on Python `3.10` and `3.12`
- compiles the source tree
- runs `pytest`
- validates the bundled demo dataset with the CLI
- generates and uploads a JSON demo fleet report artifact

This keeps the submission reproducible and gives reviewers a headless verification path even when the desktop shell cannot be launched in CI.

## Delivery Strategy

To satisfy the assessment's GitHub workflow requirement, implementation will be delivered as small conventional commits on a feature branch created from `main`. The plan is to grow the repository in atomic slices: bootstrap, domain modeling, ingestion, analytics, desktop UX, testing, and final documentation polish.

## Critical Reflection

The biggest product uncertainty at the outset is how much analytical sophistication is needed for the MVP. A simple threshold-driven alerting engine is easier to reason about and explain in an interview, while a richer anomaly detector may better capture subtle failures. The plan is to start with transparent rules and then layer in bounded anomaly detection so the trade-off remains explicit.
