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
```

The application is currently in bootstrap mode. Later commits will add the ingestion pipeline, fleet analytics, anomaly detection, and the desktop UI.

## Technical Architecture

The codebase is being structured as a layered Python application:

- `domain`: core entities and invariants for substations, telemetry readings, alerts, and fleet state.
- `application`: orchestration and analytics services that transform raw telemetry into operator-facing insights.
- `infrastructure`: file-backed ingestion, sample datasets, and future adapters for external sources.
- `presentation`: the desktop UI and view models that render the analyzed fleet state.

This separation keeps business logic independent from the UI so the analytics layer can be tested headlessly and reused by a CLI or future API.

## Delivery Strategy

To satisfy the assessment's GitHub workflow requirement, implementation will be delivered as small conventional commits on a feature branch created from `main`. The plan is to grow the repository in atomic slices: bootstrap, domain modeling, ingestion, analytics, desktop UX, testing, and final documentation polish.

## Critical Reflection

The biggest product uncertainty at the outset is how much analytical sophistication is needed for the MVP. A simple threshold-driven alerting engine is easier to reason about and explain in an interview, while a richer anomaly detector may better capture subtle failures. The plan is to start with transparent rules and then layer in bounded anomaly detection so the trade-off remains explicit.

