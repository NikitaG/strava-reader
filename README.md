# strava-reader

Toolkit for learning the Strava export format, extracting running metrics, and exporting analysis-ready files and notes.

## Main Workflows

Basic export inspection:

```bash
python3 analyze_export.py summary
python3 analyze_export.py fields
python3 analyze_export.py inspect 18105126154
```

Running progress extraction and dashboard generation:

```bash
uv run --with fitparse python running_progress.py build
```

## Generated Outputs

The running analysis command writes:

- `analysis/per_activity_runs.csv`
- `analysis/run_splits.csv`
- `analysis/weekly_aggregates.csv`
- `analysis/key_metrics.csv`
- `analysis/dashboard.md`
- `analysis/charts/*.svg`

## Data Sources

- `data/export/activities.csv`: primary activity summary table
- `data/export/activities/*.gpx`: older raw activity tracks, parsed directly
- `data/export/activities/*.fit.gz`: newer raw activity files, parsed with `fitparse` via `uv`
- `data/export/media/*`: exported photos referenced by activities

## Notes

- Session classification is heuristic and intended for analysis, not absolute truth.
- Split-level metrics are derived from GPX/FIT record streams and may differ slightly from Strava’s own app views.
- Weather adjustment is limited by the fields present in the export.
