# Walkthrough Guide

## Target Length

Aim for `3-5 minutes`.

## Suggested Structure

### 1. Opening

Suggested script:

`This project is an operator-first grid telemetry console for monitoring substation health without forcing engineers to manually inspect raw logs. I built it as a layered Python application with a desktop shell, a headless CLI, automated tests, and GitHub Actions CI.`

### 2. Problem And Architecture

Cover:

- the operational problem: too much raw telemetry, not enough prioritized context
- the layered architecture: domain, application, infrastructure, presentation
- the shared service layer used by the desktop shell, CLI, and CI

Suggested transition:

`I kept the analytics and ingestion logic independent from the UI so the same core services can power both live operator workflows and headless validation/reporting.`

### 3. Live Desktop Demo

Recommended sequence:

1. Launch the app on the demo dataset.
2. Show the fleet overview and explain the fleet score.
3. Open the alert inbox and highlight the current live signals.
4. Use the explorer to navigate to `NG-006`.
5. Explain stale telemetry detection.
6. Navigate to `SG-005`.
7. Explain sustained temperature drift and the recommended operator action.

Suggested line:

`The UI is designed so an operator can move from fleet-wide posture to one station's telemetry history and recommended action in a single flow.`

### 4. Dataset Workflow

Show:

- the dataset control card
- how staged imports are promoted from `data/imports/`
- how the runtime catalog supports switching between datasets

Suggested line:

`I treated datasets as isolated runtime units so new imports can be validated and promoted without changing the application code or mutating the bundled demo data.`

### 5. CLI And CI

Show:

- `validate --dataset demo`
- `report --dataset demo`
- the GitHub Actions workflow
- the generated demo report artifact

Suggested line:

`Even if a desktop session is unavailable, the same codebase can be validated and exercised through the CLI and CI pipeline.`

### 6. Close

Close on:

- explainable alerting and anomaly logic
- modular architecture
- scalable upgrade path

Suggested closing:

`For the assessment, I prioritized clarity, deterministic behavior, and strong separation of concerns. The current implementation is small enough to review quickly, but structured so storage backends, APIs, and richer operational workflows can be added later without rewriting the core analytics layer.`

## Key Screens To Capture

- fleet overview with score and region cards
- alert inbox with live anomaly cards
- station explorer filtered to `NG-006`
- trend insight deck for `SG-005`
- dataset control card
- CLI validation/report commands
- GitHub Actions workflow run

## Common Mistakes To Avoid

- spending too long on boilerplate setup
- describing every file instead of the architecture
- skipping the import workflow
- forgetting to mention headless validation and CI
- talking only about UI polish without explaining analytics logic
