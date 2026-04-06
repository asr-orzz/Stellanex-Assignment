# Data Directory

Shared filesystem conventions for the telemetry console live here:

- `demo/`: bundled example datasets committed to the repository.
- `imports/`: user-supplied files staged for ingestion.
- `runtime/`: generated artifacts created by the application at runtime.

Only `demo/` and documentation are expected to be committed. Runtime outputs are intentionally ignored by Git.

## Demo Dataset

The bundled demo dataset is generated from code so it can be regenerated deterministically during development:

```bash
python -m stellanex_telemetry.infrastructure.demo_dataset
```

Generated files:

- `demo/stations.csv`: station catalog and operating envelopes.
- `demo/telemetry_readings.csv`: two days of 15-minute telemetry samples.
- `demo/manifest.json`: dataset metadata, counts, and injected incident notes.
