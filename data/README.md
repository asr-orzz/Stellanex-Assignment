# Data Directory

Shared filesystem conventions for the telemetry console live here:

- `demo/`: bundled example datasets committed to the repository.
- `imports/`: user-supplied files staged for ingestion.
- `runtime/`: generated artifacts created by the application at runtime.

Only `demo/` and documentation are expected to be committed. Runtime outputs are intentionally ignored by Git.

## Import Workflow

The desktop shell now watches `imports/` as a staging area for operator-supplied datasets.

- Drop either a `manifest.json` dataset folder or a pair of `stations.csv` and `telemetry_readings.csv` files into `imports/`.
- Use the shell's `Import Staged` action to validate the staged source and normalize it into `runtime/datasets/`.
- Switch between the bundled demo dataset and imported datasets from the shell's dataset selector.

The `imports/` directory contents are intentionally ignored by Git so large ad hoc drops do not pollute the repository history.

## Demo Dataset

The bundled demo dataset is generated from code so it can be regenerated deterministically during development:

```bash
python -m stellanex_telemetry.infrastructure.demo_dataset
```

Generated files:

- `demo/stations.csv`: station catalog and operating envelopes.
- `demo/telemetry_readings.csv`: two days of 15-minute telemetry samples.
- `demo/manifest.json`: dataset metadata, counts, and injected incident notes.
