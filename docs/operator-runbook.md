# Operator Runbook

## Purpose

This runbook describes how to use the Stellanex Grid Telemetry Console during a review, demo, or local operator workflow.

## Prerequisites

- Python `3.10+`
- repository cloned locally
- optional virtual environment activated

## Startup

Install the package and launch the desktop shell:

```bash
pip install -e .[dev]
python -m stellanex_telemetry
```

The shell boots against the bundled `demo` dataset by default.

## Primary Desktop Workflow

### 1. Review Fleet Overview

Use the overview cards to answer:

- overall fleet health score
- stations in warning or critical state
- regions with the weakest average score
- current anomaly or watchlist pressure

### 2. Review Alert Inbox

The alert inbox highlights the currently active signals:

- threshold-driven alerts
- anomaly-driven alerts
- severity and category context
- latest station telemetry context

Use this panel to identify the first station worth investigating.

### 3. Investigate In Station Explorer

Use the explorer to:

- search by station name or station id
- filter by region
- filter by status
- focus only on priority stations
- sort by load, temperature, recency, or signal count

Selecting a row updates the right-side trend and insight panels.

### 4. Review Trend Insight Deck

The lower-right panel combines:

- recent voltage, load, and temperature history
- active signal context
- operator narrative summaries
- recommended next actions

This is the fastest way to explain why a station appears risky.

## Dataset Operations

### Refresh The Active Dataset

Use `Refresh Active` when the files on disk backing the current dataset have changed and you want the shell to reload them.

### Import A New Dataset

1. Place either:
   - a dataset folder containing `manifest.json`, `stations.csv`, and `telemetry_readings.csv`, or
   - a compatible CSV/manifest source
   into `data/imports/`
2. Click `Import Staged`
3. Wait for the dataset control card to confirm promotion into the runtime catalog
4. Select the new dataset key from the catalog dropdown

Imported datasets are normalized into `data/runtime/datasets/`.

## Headless Operator / Reviewer Commands

Validate a dataset:

```bash
python -m stellanex_telemetry validate --dataset demo
python -m stellanex_telemetry validate --source data/demo
```

Generate a report:

```bash
python -m stellanex_telemetry report --dataset demo
python -m stellanex_telemetry report --dataset demo --format json --output data/runtime/exports/demo_report.json
```

These commands are useful when a desktop session is unavailable.

## Demo Talking Points

If you are presenting the application live, a strong sequence is:

1. show the fleet score and priority station list
2. open the alert inbox and call out the live anomaly signals
3. filter to `NG-006` and explain stale telemetry detection
4. filter to `SG-005` and explain thermal drift detection
5. show dataset controls and explain staged import promotion
6. close with the CLI and CI story

## Troubleshooting

### Desktop Window Does Not Open

Possible cause:

- running in a headless terminal session

Fallback:

- use `validate` and `report` CLI commands instead

### Imported Dataset Does Not Appear

Check:

- files were placed in `data/imports/`
- the staged source contains both station metadata and telemetry data
- parser validation errors are not blocking promotion

### Validation Fails

Common causes:

- missing required CSV columns
- duplicate station ids
- duplicate telemetry timestamps per station
- missing timezone information in `recorded_at`
- telemetry rows referencing unknown stations

Use the CLI validation output to identify the exact row and field.
