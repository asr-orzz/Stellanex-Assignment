# Submission Checklist

## Repository Readiness

- [ ] repository contains the full source code, demo dataset, docs, tests, and CI workflow
- [ ] feature branch has been pushed to GitHub
- [ ] commit history is clean and atomic
- [ ] README explains setup, CLI usage, CI behavior, and architecture docs
- [ ] video walkthrough link at the top of `README.md` has been replaced with the final URL

## Engineering Verification

- [ ] `python -m compileall src`
- [ ] `pytest -q`
- [ ] `python -m stellanex_telemetry validate --dataset demo`
- [ ] `python -m stellanex_telemetry report --dataset demo --top-stations 3`
- [ ] desktop shell launches locally with `python -m stellanex_telemetry`

## Dataset And Demo Readiness

- [ ] bundled demo dataset loads without ingestion errors
- [ ] station explorer shows the full catalog
- [ ] alert inbox surfaces the live anomaly signals
- [ ] trend insight deck updates when a new station is selected
- [ ] dataset control card supports refresh and staged import promotion

## GitHub Readiness

- [ ] GitHub Actions workflow is visible in the repository
- [ ] latest CI run is green
- [ ] demo fleet report artifact is produced by the workflow
- [ ] repository visibility matches the assessment requirement
- [ ] branch / PR naming is professional and easy to review

## Walkthrough Readiness

- [ ] video length is within the requested duration
- [ ] walkthrough shows both the desktop experience and CLI / CI story
- [ ] architecture explanation is consistent with `docs/architecture.md`
- [ ] key signals demonstrated include `NG-006` stale telemetry and `SG-005` drift
- [ ] closing summary explains scalability posture and future evolution path

## Final Sanity Check

- [ ] no local secrets or environment-specific files are staged
- [ ] no runtime-only folders such as `data/runtime/` or `.ci-runtime/` are committed
- [ ] generated JSON report artifacts are only committed if explicitly intended
- [ ] all final docs are readable directly from GitHub
