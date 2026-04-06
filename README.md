# Stellanex Grid Telemetry Console

An operator-first telemetry monitoring platform for electrical substations. The project ingests station metadata and time-series telemetry, evaluates fleet health, detects threshold breaches and anomalies, and presents the result through both a desktop control room UI and a headless CLI.

## What This Project Does

- loads substation catalog data and telemetry readings from CSV datasets
- validates ingestion inputs before they are used at runtime
- computes fleet health scores and regional rollups
- detects threshold-based issues such as voltage, load, temperature, and connectivity problems
- detects bounded anomalies such as spikes, drift, and stale telemetry
- provides a desktop shell for operations teams
- provides CLI commands for validation and report generation
- supports staged dataset imports and dataset switching without code changes

## Architecture

The codebase follows a layered architecture so business logic stays reusable and testable.

- `domain`
  core entities and invariants for substations, telemetry readings, alerts, and status semantics
- `application`
  orchestration services for alerting, anomaly detection, fleet health scoring, station detail assembly, reporting, and dataset management
- `infrastructure`
  CSV parsing, deterministic demo dataset generation, indexed repositories, and filesystem-backed dataset workspace operations
- `presentation`
  Tkinter desktop shell, UI view models, station explorer, alert inbox, trend charts, and insight panels

This structure lets the desktop shell, CLI, and CI pipeline share the same analytics layer instead of maintaining separate implementations.

For deeper design notes:

- `docs/architecture.md`
- `docs/system-design-notes.md`

## Repository Layout

```text
src/stellanex_telemetry/
  domain/          Core models and invariants
  application/     Analytics and orchestration services
  infrastructure/  Parsers, repositories, dataset workspace
  presentation/    Desktop UI and view models

data/
  demo/            Bundled deterministic dataset
  imports/         Staged import drop zone
  runtime/         Generated runtime artifacts

docs/              Architecture, runbook, and project notes
tests/             Automated test suite
```

## Requirements

- Python `3.10` or newer
- Windows PowerShell is used in the examples below

## How To Run Locally

### 1. Create A Virtual Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .[dev]
```

### 2. Launch The Desktop Application

```powershell
python -m stellanex_telemetry
```

You can also use the console script:

```powershell
stellanex-console desktop
```

The desktop shell starts with the bundled demo dataset and shows:

- fleet overview KPIs
- regional health cards
- priority station watchlist
- active alerts inbox
- station explorer with search, filter, and sorting
- trend charts and operator insight recommendations
- dataset selector with refresh and staged import support

## CLI Commands

### Validate A Dataset

Validate the bundled demo dataset:

```powershell
python -m stellanex_telemetry validate --dataset demo
```

Validate a dataset directly from a path:

```powershell
python -m stellanex_telemetry validate --source data\demo
```

### Generate A Fleet Report

Generate a text report:

```powershell
python -m stellanex_telemetry report --dataset demo --top-stations 3
```

Generate a JSON report:

```powershell
python -m stellanex_telemetry report --dataset demo --format json --output data\runtime\exports\demo_report.json
```

Run through the console script:

```powershell
stellanex-console report --dataset demo --top-stations 3
```

## Dataset Workflow

The project uses three dataset locations:

- `data/demo/`
  bundled deterministic demo dataset committed to the repository
- `data/imports/`
  staging area for operator-provided dataset folders or CSV drops
- `data/runtime/`
  generated runtime workspace for imported datasets, exports, caches, and logs

### Import A New Dataset

1. Put a compatible dataset in `data/imports/`
2. Launch the desktop app
3. Use `Import Staged` from the dataset control card
4. Select the new dataset from the catalog dropdown

Supported import shapes include:

- a dataset directory containing `manifest.json`, `stations.csv`, and `telemetry_readings.csv`
- compatible CSV and manifest sources that the parser can resolve

## Demo Dataset

The bundled demo dataset is deterministic and intentionally includes realistic signals for demos and tests.

- `24` substations
- `4600` telemetry readings
- `4` grid regions
- seeded incidents including:
  - `NG-006` stale telemetry
  - `SG-005` sustained temperature drift
  - `NG-003` metadata-driven critical state
  - earlier overload and voltage sag patterns inside history windows

## How To Test

Run the full local verification flow:

```powershell
python -m compileall src
pytest -q
python -m stellanex_telemetry validate --dataset demo
python -m stellanex_telemetry report --dataset demo --top-stations 3
```

Current automated coverage includes:

- CSV ingestion validation
- malformed dataset handling
- deterministic fleet reporting on the demo dataset
- CLI validation behavior
- CLI JSON export behavior

## CI

GitHub Actions runs the following pipeline:

- source compilation
- automated tests
- CLI validation of the demo dataset
- generation of a JSON demo fleet report artifact

Workflow file:

- `.github/workflows/ci.yml`

## Helpful Docs

- `docs/operator-runbook.md`
- `docs/architecture.md`
- `docs/system-design-notes.md`
- `docs/final-handoff.md`

## Notes

- If the desktop shell cannot open in your environment, you can still validate datasets and generate reports through the CLI.
- Runtime-only folders such as `data/runtime/` and `.ci-runtime/` are intentionally ignored by Git.
