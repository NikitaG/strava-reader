# Strava Running Progress Analytics Dashboard

Designed for half-marathon readiness, aerobic progress, recovery, and training load.

---

# 1. Data Tables

## activities.csv -> base table

One row per activity.

Required normalized columns:

- activity_id
- date
- week_start
- name
- type
- distance_km
- moving_time_min
- elapsed_time_min
- elevation_gain_m
- avg_hr
- max_hr
- avg_speed_mps
- avg_pace_sec_km
- cadence
- calories
- relative_effort
- training_load
- flagged
- raw_file

Derived:

- is_run
- run_class
- is_hard
- is_easy

Notes:

- `avg_speed_mps` should stay in meters/second in the normalized table, even if dashboards also display `kph`.
- `avg_pace_sec_km` should be computed from moving time and distance rather than copied from a display string.
- `week_start` should be normalized to Monday 00:00 local date unless a different reporting standard is chosen.

---

## splits table

One row per km split or lap:

- activity_id
- split_num
- split_distance_km
- split_time_sec
- split_pace_sec_km
- split_avg_hr
- split_elevation_m

Notes:

- Prefer 1 km derived splits for consistency across GPX and FIT files.
- Store the split source if possible, for example `fit_record`, `gpx_record`, or `lap_message`.
- Partial final splits can be kept, but should be explicitly marked if downstream logic assumes full kilometers.

---

# 2. Classification Rules

## easy

avg_hr <= 145  
and no fast segments

## recovery

distance <= 8 km  
avg_hr <= 140

## long_run

distance >= 14 km

## tempo_threshold

continuous block >= 15 min at pace faster than rolling easy pace by 12%+

## intervals

multiple hard blocks with recoveries

## trail_hilly

elevation_gain_m >= 20 m/km

## race

contains race keyword or max effort pattern

Implementation notes:

- `run_class` should be a primary label, but keep individual booleans too because a run may satisfy multiple tags.
- `is_hard` should usually be true for `tempo_threshold`, `intervals`, and `race`.
- `is_easy` should usually be true for `easy` and `recovery`, but not for `trail_hilly` unless the effort profile is still easy.

---

# 3. Weekly Summary Table

Group by week_start.

Columns:

- total_runs
- total_distance_km
- total_time_min
- avg_run_distance
- longest_run_km
- total_elevation_gain_m
- hard_sessions
- easy_sessions
- easy_km
- hard_km
- avg_hr_all_runs

Notes:

- Weekly summary should be computed from runs only unless a multi-sport dashboard is explicitly requested.
- Add 4-week and 6-week rolling averages on top of this table rather than mixing raw weekly values and rolling values in the same columns.

---

# 4. Rolling Metrics (4-week / 6-week)

## Aerobic Efficiency

Use only easy runs:
- avg_hr between 135 and 145
- elevation_gain_m / distance_km < 15

Compute:

- median_easy_pace_sec_km
- pace_at_hr140
- hr_at_600_pace

## Threshold Fitness

Use tempo runs:

- best_20min_pace
- avg_tempo_pace
- avg_tempo_hr

## Endurance

- longest_run_last6w
- avg_long_run_distance
- avg_long_run_hr_drift

## Recovery

- easy_pace_48h_after_hard
- days_since_last_hard
- fatigue_flags_last14d

Notes:

- Use rolling windows anchored on activity date for per-run metrics and on `week_start` for weekly views.
- Temperature and elevation should be used as adjustment flags where possible, even if not deeply modeled.
- Keep raw metrics and adjusted interpretations separate.

---

# 5. HM Readiness Score (Sub 1:50 = 5:13/km)

Score 0-100.

## Tempo Evidence (35%)

- 5 km @ <=5:15 strong score
- 2x3 km @ <=5:10 strong score

## Easy Efficiency (25%)

- pace_at_hr140 <= 5:50 = strong
- <= 6:05 = moderate

## Weekly Consistency (15%)

- >=30 km/week steady = good
- >=40 = strong

## Long Run Readiness (15%)

- 16 km = moderate
- 18+ km = strong

## Recovery / Freshness (10%)

- no fatigue spike
- normal easy HR

## Readiness Bands

- 85-100 = strongly ready
- 70-84 = ready
- 55-69 = possible on good day
- <55 = more build needed

Implementation notes:

- Score components should be stored separately before combining into a final score.
- A single exceptional workout should not dominate the score; prefer best-of-recent plus consistency checks.
- Missing data should lower confidence, not silently count as failure.

---

# 6. Charts

## Volume

1. weekly_distance_km
2. weekly_time_min
3. longest_run_trend

## Fitness

4. pace_at_hr140_trend
5. best_20min_pace_trend
6. avg_tempo_hr_trend

## Recovery

7. easy_pace_after_hard_trend
8. hr_drift_trend

## Goal

9. hm_readiness_score_trend

Notes:

- Prefer weekly resolution for volume and readiness charts.
- Prefer activity-date resolution for per-run fitness and recovery charts.
- Store chart inputs in tables so the visualization layer stays thin.

---

# 7. Python / Pandas Core Formulas

## pace sec/km

```python
df["avg_pace_sec_km"] = (df["moving_time_sec"] / df["distance_m"]) * 1000
```

## distance km

```python
df["distance_km"] = df["distance_m"] / 1000
```

## week start

```python
df["week_start"] = df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")
```

## pace at HR140 (easy runs)

```python
easy = df[(df.avg_hr.between(135,145)) & (df.run_class=="easy")]
pace140 = easy["avg_pace_sec_km"].median()
```

## rolling weekly distance

```python
weekly["dist_4w_avg"] = weekly["total_distance_km"].rolling(4).mean()
```

Notes:

- `avg_speed_mps` should be derived as `distance_m / moving_time_sec` if raw speed is missing.
- A display conversion to kph is `avg_speed_kph = avg_speed_mps * 3.6`.
- A display conversion from pace seconds to `mm:ss/km` should be handled only in the presentation layer.

---

# 8. Personal Targets (Current Athlete)

## Strong signs for sub-1:50:

- pace_at_hr140 <= 5:50
- best tempo 5 km <= 5:15
- weekly volume >= 32 km
- long run >= 17 km
- no fatigue spike

## Strong signs for sub-1:45:

- pace_at_hr140 <= 5:35
- 8 km tempo <= 5:10
- weekly volume >= 40 km
- long run >= 19 km

Notes:

- These targets should be treated as athlete-specific heuristics, not universal race prediction rules.
- Threshold targets should be revisited whenever recent training style changes materially.

---

# 9. Output Example Weekly Summary

Week of 2026-04-06

- Distance: 34.2 km
- Runs: 4
- Hard sessions: 1
- Longest run: 17.1 km
- Easy pace @ HR140: 5:47/km
- Best tempo pace: 5:12/km
- HM readiness: 74/100
- Status: Ready with pacing discipline

---

# 10. Implementation Alignment For This Repo

Current repo outputs that already map to this spec:

- `analysis/per_activity_runs.csv`
- `analysis/run_splits.csv`
- `analysis/weekly_aggregates.csv`
- `analysis/key_metrics.csv`
- `analysis/dashboard.md`

Recommended next alignment steps:

1. Rename or add output columns so they exactly match the normalized names in this document.
2. Keep `avg_speed_mps` as the canonical speed field and move `kph` to presentation only.
3. Add explicit `week_start`, `easy_km`, `hard_km`, and `avg_hr_all_runs` to the weekly summary.
4. Upgrade tempo detection from activity-level heuristics to split-block detection.
5. Add a chart input table and a readiness score history table.
