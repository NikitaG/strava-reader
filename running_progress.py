from __future__ import annotations

import argparse
import csv
import gzip
import math
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

try:
    from fitparse import FitFile  # type: ignore
except Exception:  # pragma: no cover
    FitFile = None

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "export"
ACTIVITIES_CSV = DATA_DIR / "activities.csv"
ACTIVITY_FILES_DIR = DATA_DIR / "activities"
OUTPUT_DIR = ROOT / "analysis"
CHARTS_DIR = OUTPUT_DIR / "charts"

GPX_NS = {
    "g": "http://www.topografix.com/GPX/1/1",
    "gpxtpx": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
}


@dataclass
class Activity:
    activity_id: str
    date: datetime
    start_time: str
    activity_name: str
    activity_type: str
    distance_km: float
    moving_time_min: float
    elapsed_time_min: float
    avg_pace_per_km: float | None
    avg_speed_mps: float | None
    max_speed_mps: float | None
    elevation_gain_m: float
    avg_hr: float | None
    max_hr: float | None
    avg_cadence: float | None
    calories: float | None
    relative_effort: float | None
    training_load: float | None
    intensity: float | None
    flagged: bool
    avg_temp_c: float | None
    weather_temp_c: float | None
    apparent_temp_c: float | None
    dirt_distance_km: float | None
    avg_grade: float | None
    max_grade: float | None
    total_steps: float | None
    filename: str
    description: str
    flags: dict[str, bool]
    primary_class: str
    file_format: str
    split_source: str
    split_count: int
    workout_split_source: str = "none"
    pace_fade_last_third_pct: float | None = None
    hr_drift_pct: float | None = None
    days_since_last_hard: float | None = None
    easy_pace_after_hard: float | None = None
    fatigue_flag: bool = False
    pace_at_hr140_est: float | None = None
    hr_at_6min_est: float | None = None
    tempo_fitness_pace: float | None = None
    longest_continuous_tempo_min: float | None = None
    best_20min_pace: float | None = None
    avg_tempo_hr: float | None = None


@dataclass
class Sample:
    timestamp: datetime
    distance_m: float
    altitude_m: float | None
    heart_rate: float | None
    speed_mps: float | None
    cadence: float | None


@dataclass
class Split:
    activity_id: str
    lap_number: int
    lap_distance_km: float
    lap_time_min: float
    lap_pace_per_km: float | None
    lap_hr: float | None
    lap_elevation_m: float | None
    source: str


@dataclass
class WeeklyAggregate:
    week_start: datetime
    total_distance_km: float
    total_running_time_min: float
    run_count: int
    avg_run_distance: float
    longest_run_km: float
    total_elevation_gain: float
    hard_sessions_count: int
    easy_sessions_count: int
    easy_km: float
    hard_km: float
    avg_hr_all_runs: float | None


def parse_float(value: str | None) -> float | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_date(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%b %d, %Y, %I:%M:%S %p")


def parse_bool(value: str | None) -> bool:
    raw = (value or "").strip().lower()
    return raw in {"1", "1.0", "true", "yes"}


def week_start_for(dt: datetime) -> datetime:
    return (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def pace_from_distance_time(distance_km: float, moving_time_min: float) -> float | None:
    if distance_km <= 0 or moving_time_min <= 0:
        return None
    return moving_time_min / distance_km


def format_pace(minutes_per_km: float | None) -> str:
    if minutes_per_km is None or math.isnan(minutes_per_km):
        return "-"
    total_seconds = round(minutes_per_km * 60)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}/km"


def median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    return statistics.median(vals) if vals else None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_runs() -> list[Activity]:
    runs: list[Activity] = []
    with ACTIVITIES_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("Activity Type") or "").strip() != "Run":
                continue
            dt = parse_date(row["Activity Date"])
            distance_km = (parse_float(row.get("Distance")) or 0.0) / 1000.0
            moving_time_min = (parse_float(row.get("Moving Time")) or 0.0) / 60.0
            elapsed_time_min = (parse_float(row.get("Elapsed Time")) or 0.0) / 60.0
            avg_speed_mps = parse_float(row.get("Average Speed"))
            max_speed_mps = parse_float(row.get("Max Speed"))
            avg_pace = pace_from_distance_time(distance_km, moving_time_min)
            filename = (row.get("Filename") or "").strip()
            suffix = ""
            if filename.endswith(".fit.gz"):
                suffix = "fit.gz"
            elif filename.endswith(".gpx"):
                suffix = "gpx"
            else:
                suffix = Path(filename).suffix.lstrip(".")
            runs.append(
                Activity(
                    activity_id=(row.get("Activity ID") or "").strip(),
                    date=dt,
                    start_time=dt.strftime("%H:%M:%S"),
                    activity_name=(row.get("Activity Name") or "").strip(),
                    activity_type=(row.get("Activity Type") or "").strip(),
                    distance_km=distance_km,
                    moving_time_min=moving_time_min,
                    elapsed_time_min=elapsed_time_min,
                    avg_pace_per_km=avg_pace,
                    avg_speed_mps=avg_speed_mps,
                    max_speed_mps=max_speed_mps,
                    elevation_gain_m=parse_float(row.get("Elevation Gain")) or 0.0,
                    avg_hr=parse_float(row.get("Average Heart Rate")),
                    max_hr=parse_float(row.get("Max Heart Rate")),
                    avg_cadence=parse_float(row.get("Average Cadence")),
                    calories=parse_float(row.get("Calories")),
                    relative_effort=parse_float(row.get("Relative Effort")),
                    training_load=parse_float(row.get("Training Load")),
                    intensity=parse_float(row.get("Intensity")),
                    flagged=parse_bool(row.get("Flagged")),
                    avg_temp_c=parse_float(row.get("Average Temperature")),
                    weather_temp_c=parse_float(row.get("Weather Temperature")),
                    apparent_temp_c=parse_float(row.get("Apparent Temperature")),
                    dirt_distance_km=(parse_float(row.get("Dirt Distance")) or 0.0) / 1000.0 if row.get("Dirt Distance") else None,
                    avg_grade=parse_float(row.get("Average Grade")),
                    max_grade=parse_float(row.get("Max Grade")),
                    total_steps=parse_float(row.get("Total Steps")),
                    filename=filename,
                    description=(row.get("Activity Description") or "").strip(),
                    flags={},
                    primary_class="unclassified",
                    file_format=suffix,
                    split_source="none",
                    split_count=0,
                    workout_split_source="none",
                )
            )
    runs.sort(key=lambda run: run.date)
    return runs


def split_pace_sec(split: Split) -> float | None:
    return split.lap_pace_per_km * 60.0 if split.lap_pace_per_km is not None else None


def weighted_pace_minutes(splits: list[Split]) -> float | None:
    usable = [s for s in splits if s.lap_pace_per_km is not None and s.lap_distance_km > 0]
    if not usable:
        return None
    total_time = sum(s.lap_time_min for s in usable)
    total_dist = sum(s.lap_distance_km for s in usable)
    return total_time / total_dist if total_dist > 0 else None


def weighted_hr(splits: list[Split]) -> float | None:
    usable = [s for s in splits if s.lap_hr is not None and s.lap_time_min > 0]
    if not usable:
        return None
    total_time = sum(s.lap_time_min for s in usable)
    return sum((s.lap_hr or 0.0) * s.lap_time_min for s in usable) / total_time if total_time > 0 else None


def parse_fit_laps(path: Path, activity_id: str) -> list[Split]:
    if FitFile is None:
        return []
    laps: list[Split] = []
    with gzip.open(path, "rb") as handle:
        fit = FitFile(handle)
        lap_num = 1
        for message in fit.get_messages("lap"):
            values = {field.name: field.value for field in message}
            trigger = values.get("lap_trigger")
            distance_m = values.get("total_distance")
            timer_s = values.get("total_timer_time") or values.get("total_elapsed_time")
            if trigger == "session_end" or distance_m is None or timer_s is None:
                continue
            distance_km = float(distance_m) / 1000.0
            if distance_km < 0.2:
                continue
            lap_time_min = float(timer_s) / 60.0
            pace = lap_time_min / distance_km if distance_km > 0 else None
            elevation = float(values["total_ascent"]) if values.get("total_ascent") is not None else None
            if elevation is None and values.get("enhanced_avg_altitude") is not None:
                elevation = float(values["enhanced_avg_altitude"])
            laps.append(
                Split(
                    activity_id=activity_id,
                    lap_number=lap_num,
                    lap_distance_km=distance_km,
                    lap_time_min=lap_time_min,
                    lap_pace_per_km=pace,
                    lap_hr=float(values["avg_heart_rate"]) if values.get("avg_heart_rate") is not None else None,
                    lap_elevation_m=elevation,
                    source="fit_lap",
                )
            )
            lap_num += 1
    return laps


def enrich_lap_splits_from_km(lap_splits: list[Split], km_splits: list[Split]) -> list[Split]:
    if not lap_splits or not km_splits:
        return lap_splits
    enriched: list[Split] = []
    km_boundaries = []
    cumulative = 0.0
    for split in km_splits:
        start = cumulative
        cumulative += split.lap_distance_km
        km_boundaries.append((start, cumulative, split))

    lap_start = 0.0
    for lap in lap_splits:
        lap_end = lap_start + lap.lap_distance_km
        overlaps = []
        for seg_start, seg_end, km_split in km_boundaries:
            overlap = max(0.0, min(lap_end, seg_end) - max(lap_start, seg_start))
            if overlap > 0:
                overlaps.append((overlap, km_split))
        lap_hr = lap.lap_hr
        if lap_hr is None and overlaps:
            weighted_hr_sum = 0.0
            weighted_hr_dist = 0.0
            for overlap, km_split in overlaps:
                if km_split.lap_hr is not None:
                    weighted_hr_sum += km_split.lap_hr * overlap
                    weighted_hr_dist += overlap
            if weighted_hr_dist > 0:
                lap_hr = weighted_hr_sum / weighted_hr_dist
        lap_elevation = lap.lap_elevation_m
        if lap_elevation is None and overlaps:
            lap_elevation = sum((km_split.lap_elevation_m or 0.0) * (overlap / km_split.lap_distance_km) for overlap, km_split in overlaps if km_split.lap_distance_km > 0)
        enriched.append(
            Split(
                activity_id=lap.activity_id,
                lap_number=lap.lap_number,
                lap_distance_km=lap.lap_distance_km,
                lap_time_min=lap.lap_time_min,
                lap_pace_per_km=lap.lap_pace_per_km,
                lap_hr=lap_hr,
                lap_elevation_m=lap_elevation,
                source=lap.source,
            )
        )
        lap_start = lap_end
    return enriched


def choose_workout_splits(km_splits: list[Split], lap_splits: list[Split], run: Activity) -> tuple[list[Split], str]:
    if not lap_splits:
        return km_splits, km_splits[0].source if km_splits else "none"
    lap_dist = sum(s.lap_distance_km for s in lap_splits)
    informative_laps = sum(1 for s in lap_splits if s.lap_hr is not None or s.lap_elevation_m is not None)
    structured_laps = len(lap_splits) >= 2 and lap_dist >= max(1.0, run.distance_km * 0.8)
    coarse_workout_blocks = structured_laps and all(s.lap_distance_km >= 2.0 for s in lap_splits)
    if structured_laps and (informative_laps >= 1 or coarse_workout_blocks):
        return lap_splits, "fit_lap"
    return km_splits, km_splits[0].source if km_splits else "none"


def best_20min_pace_from_splits(splits: list[Split]) -> float | None:
    best: float | None = None
    for start in range(len(splits)):
        total_time = 0.0
        total_dist = 0.0
        for end in range(start, len(splits)):
            total_time += splits[end].lap_time_min
            total_dist += splits[end].lap_distance_km
            if total_time >= 20.0 and total_dist > 0:
                pace = total_time / total_dist
                if best is None or pace < best:
                    best = pace
                break
    return best


def contiguous_fast_blocks(splits: list[Split], pace_threshold_sec: float) -> list[list[Split]]:
    blocks: list[list[Split]] = []
    current: list[Split] = []
    for split in splits:
        pace = split_pace_sec(split)
        if pace is not None and pace <= pace_threshold_sec:
            current.append(split)
        else:
            if current:
                blocks.append(current)
                current = []
    if current:
        blocks.append(current)
    return blocks


def longest_fast_block(splits: list[Split], pace_threshold_sec: float) -> tuple[float, float | None, float | None]:
    blocks = contiguous_fast_blocks(splits, pace_threshold_sec)
    if not blocks:
        return 0.0, None, None
    best = max(blocks, key=lambda block: sum(s.lap_time_min for s in block))
    duration = sum(s.lap_time_min for s in best)
    return duration, weighted_pace_minutes(best), weighted_hr(best)


def best_tempo_block_metrics(splits: list[Split], pace_threshold_sec: float, min_duration_min: float = 15.0) -> tuple[float | None, float | None, float | None]:
    qualifying = [block for block in contiguous_fast_blocks(splits, pace_threshold_sec) if sum(s.lap_time_min for s in block) >= min_duration_min]
    if not qualifying:
        return None, None, None
    best = min(qualifying, key=lambda block: weighted_pace_minutes(block) or 10**9)
    return weighted_pace_minutes(best), weighted_hr(best), sum(s.lap_time_min for s in best)


def detect_interval_blocks(splits: list[Split], fast_threshold_sec: float, recovery_threshold_sec: float) -> bool:
    if len(splits) < 3:
        return False
    fast_blocks = 0
    saw_recovery_between = False
    in_fast = False
    for split in splits:
        pace = split_pace_sec(split)
        if pace is None:
            continue
        if pace <= fast_threshold_sec:
            if not in_fast:
                fast_blocks += 1
                in_fast = True
        else:
            if in_fast and pace >= recovery_threshold_sec:
                saw_recovery_between = True
            in_fast = False
    return fast_blocks >= 2 and saw_recovery_between


def apply_split_derived_metrics(runs: list[Activity], km_split_map: dict[str, list[Split]]) -> None:
    for run in runs:
        splits = km_split_map.get(run.activity_id, [])
        if run.flags.get("long_run") and len(splits) >= 3:
            third = max(1, len(splits) // 3)
            first = splits[:third]
            last = splits[-third:]
            first_pace = weighted_pace_minutes(first)
            last_pace = weighted_pace_minutes(last)
            if first_pace and last_pace and first_pace > 0:
                run.pace_fade_last_third_pct = ((last_pace - first_pace) / first_pace) * 100.0
        if run.flags.get("easy") and len(splits) >= 4:
            half = len(splits) // 2
            first_eff = efficiency_score(splits[:half])
            last_eff = efficiency_score(splits[half:])
            if first_eff and last_eff:
                run.hr_drift_pct = ((last_eff - first_eff) / first_eff) * 100.0


def classify_runs(runs: list[Activity], workout_split_map: dict[str, list[Split]]) -> None:
    history_easy_paces: list[tuple[datetime, float]] = []
    for idx, run in enumerate(runs):
        workout_splits = workout_split_map.get(run.activity_id, [])
        name_desc = f"{run.activity_name} {run.description}".lower()
        elev_per_km = run.elevation_gain_m / run.distance_km if run.distance_km > 0 else 0.0
        rolling_window_start = run.date - timedelta(days=42)
        recent_easy_paces = [pace for dt, pace in history_easy_paces if dt >= rolling_window_start]
        easy_baseline_sec = statistics.median(recent_easy_paces) if recent_easy_paces else None
        fast_threshold_sec = easy_baseline_sec * 0.88 if easy_baseline_sec is not None else None
        recovery_threshold_sec = easy_baseline_sec * 1.03 if easy_baseline_sec is not None else None

        tempo_duration = 0.0
        tempo_pace = None
        tempo_hr = None
        has_fast_segments = False
        intervals = any(token in name_desc for token in ["interval", "repeat", "repeats", "track", "workout", "fartlek"])
        if fast_threshold_sec is not None and recovery_threshold_sec is not None:
            longest_duration, _, _ = longest_fast_block(workout_splits, fast_threshold_sec)
            tempo_pace, tempo_hr, qualifying_duration = best_tempo_block_metrics(workout_splits, fast_threshold_sec, min_duration_min=15.0)
            tempo_duration = qualifying_duration or 0.0
            has_fast_segments = any((split_pace_sec(split) or 10**9) <= fast_threshold_sec for split in workout_splits)
            intervals = intervals or detect_interval_blocks(workout_splits, fast_threshold_sec, recovery_threshold_sec)
            if tempo_duration == 0.0:
                tempo_duration = longest_duration

        best20 = best_20min_pace_from_splits(workout_splits)
        race = any(token in name_desc for token in ["race", "5k race", "10k race", "half marathon", "hm race", "marathon"]) or ((run.relative_effort or 0) >= 120 and (run.avg_hr or 0) >= 160)
        long_run = run.distance_km >= 14.0
        trail_hilly = elev_per_km >= 20.0
        tempo = easy_baseline_sec is not None and tempo_pace is not None and tempo_duration >= 15.0 and not intervals and not race
        recovery = run.distance_km <= 8.0 and (run.avg_hr or 999.0) <= 140.0
        easy = (run.avg_hr or 999.0) <= 145.0 and not has_fast_segments and not intervals and not race

        if idx > 0:
            prior_hard = next((prior for prior in reversed(runs[:idx]) if prior.flags.get("hard")), None)
            if prior_hard and (run.date - prior_hard.date).total_seconds() / 86400.0 <= 2.0 and run.distance_km <= 8.0 and (run.avg_hr or 999.0) <= 140.0:
                recovery = True

        flags = {
            "easy": easy,
            "recovery": recovery,
            "long_run": long_run,
            "tempo_threshold": tempo,
            "intervals": intervals,
            "race": race,
            "trail_hilly": trail_hilly,
        }
        flags["hard"] = flags["tempo_threshold"] or flags["intervals"] or flags["race"]

        if flags["race"]:
            primary = "race"
        elif flags["intervals"]:
            primary = "intervals"
        elif flags["tempo_threshold"]:
            primary = "tempo_threshold"
        elif flags["long_run"]:
            primary = "long_run"
        elif flags["recovery"]:
            primary = "recovery"
        elif flags["easy"]:
            primary = "easy"
        elif flags["trail_hilly"]:
            primary = "trail_hilly"
        else:
            primary = "steady"

        run.flags = flags
        run.primary_class = primary
        run.longest_continuous_tempo_min = tempo_duration if tempo and tempo_duration > 0 else None
        run.tempo_fitness_pace = tempo_pace if tempo else None
        run.avg_tempo_hr = tempo_hr if tempo else None
        run.best_20min_pace = best20

        if flags["easy"] and run.avg_hr is not None and 135.0 <= run.avg_hr <= 145.0 and elev_per_km < 15.0 and run.avg_pace_per_km is not None:
            history_easy_paces.append((run.date, run.avg_pace_per_km * 60.0))


def parse_gpx_samples(path: Path) -> list[Sample]:
    root = ET.parse(path).getroot()
    samples: list[Sample] = []
    last_lat = None
    last_lon = None
    last_time: datetime | None = None
    cumulative = 0.0
    for point in root.findall(".//g:trkpt", GPX_NS):
        lat = float(point.attrib["lat"])
        lon = float(point.attrib["lon"])
        ele_text = point.findtext("g:ele", default="", namespaces=GPX_NS)
        time_text = point.findtext("g:time", default="", namespaces=GPX_NS)
        hr_text = point.findtext(".//gpxtpx:hr", default="", namespaces=GPX_NS)
        cad_text = point.findtext(".//gpxtpx:cad", default="", namespaces=GPX_NS)
        if not time_text:
            continue
        timestamp = datetime.fromisoformat(time_text.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        segment_distance = 0.0
        if last_lat is not None and last_lon is not None and last_time is not None:
            dt = (timestamp - last_time).total_seconds()
            if dt <= 0:
                continue
            segment_distance = haversine_m(last_lat, last_lon, lat, lon)
            if segment_distance / dt > 7.0:
                continue
            cumulative += segment_distance
        samples.append(
            Sample(
                timestamp=timestamp,
                distance_m=cumulative,
                altitude_m=float(ele_text) if ele_text else None,
                heart_rate=float(hr_text) if hr_text else None,
                speed_mps=(segment_distance / (timestamp - last_time).total_seconds()) if last_time is not None and timestamp != last_time else None,
                cadence=float(cad_text) if cad_text else None,
            )
        )
        last_lat, last_lon, last_time = lat, lon, timestamp
    return samples


def parse_fit_samples(path: Path) -> list[Sample]:
    if FitFile is None:
        return []
    samples: list[Sample] = []
    with gzip.open(path, "rb") as handle:
        fit = FitFile(handle)
        for message in fit.get_messages("record"):
            values = {field.name: field.value for field in message}
            timestamp = values.get("timestamp")
            distance_m = values.get("distance")
            if timestamp is None or distance_m is None:
                continue
            samples.append(
                Sample(
                    timestamp=timestamp,
                    distance_m=float(distance_m),
                    altitude_m=float(values["altitude"]) if values.get("altitude") is not None else None,
                    heart_rate=float(values["heart_rate"]) if values.get("heart_rate") is not None else None,
                    speed_mps=float(values["speed"]) if values.get("speed") is not None else None,
                    cadence=float(values["cadence"]) if values.get("cadence") is not None else None,
                )
            )
    samples.sort(key=lambda item: item.timestamp)
    return samples


def interpolate_sample(prev: Sample, curr: Sample, target_distance: float) -> Sample:
    if curr.distance_m == prev.distance_m:
        ratio = 0.0
    else:
        ratio = (target_distance - prev.distance_m) / (curr.distance_m - prev.distance_m)
    dt = curr.timestamp - prev.timestamp
    timestamp = prev.timestamp + timedelta(seconds=dt.total_seconds() * ratio)

    def interp(a: float | None, b: float | None) -> float | None:
        if a is None and b is None:
            return None
        if a is None:
            return b
        if b is None:
            return a
        return a + (b - a) * ratio

    return Sample(
        timestamp=timestamp,
        distance_m=target_distance,
        altitude_m=interp(prev.altitude_m, curr.altitude_m),
        heart_rate=interp(prev.heart_rate, curr.heart_rate),
        speed_mps=interp(prev.speed_mps, curr.speed_mps),
        cadence=interp(prev.cadence, curr.cadence),
    )


def derive_splits(activity_id: str, samples: list[Sample], source: str) -> list[Split]:
    if len(samples) < 2:
        return []
    splits: list[Split] = []
    total_distance = samples[-1].distance_m
    if total_distance < 400:
        return []

    boundaries = [1000.0 * i for i in range(1, int(total_distance // 1000) + 1)]
    if total_distance - (boundaries[-1] if boundaries else 0) >= 400:
        boundaries.append(total_distance)
    elif not boundaries:
        boundaries.append(total_distance)

    boundary_samples = [samples[0]]
    idx = 1
    for target in boundaries:
        while idx < len(samples) and samples[idx].distance_m < target:
            idx += 1
        if idx >= len(samples):
            boundary_samples.append(samples[-1])
            continue
        boundary_samples.append(interpolate_sample(samples[idx - 1], samples[idx], target))

    for lap_number in range(1, len(boundary_samples)):
        start = boundary_samples[lap_number - 1]
        end = boundary_samples[lap_number]
        lap_distance_km = (end.distance_m - start.distance_m) / 1000.0
        lap_time_min = (end.timestamp - start.timestamp).total_seconds() / 60.0
        if lap_distance_km <= 0 or lap_time_min <= 0:
            continue
        in_range = [s for s in samples if start.distance_m <= s.distance_m <= end.distance_m]
        hrs = [s.heart_rate for s in in_range if s.heart_rate is not None]
        elevations = [s.altitude_m for s in in_range if s.altitude_m is not None]
        gain = None
        if len(elevations) >= 2:
            gain = 0.0
            for a, b in zip(elevations, elevations[1:]):
                if b > a:
                    gain += b - a
        splits.append(
            Split(
                activity_id=activity_id,
                lap_number=lap_number,
                lap_distance_km=lap_distance_km,
                lap_time_min=lap_time_min,
                lap_pace_per_km=lap_time_min / lap_distance_km,
                lap_hr=statistics.mean(hrs) if hrs else None,
                lap_elevation_m=gain,
                source=source,
            )
        )
    return splits


def attach_split_metrics(runs: list[Activity]) -> tuple[list[Split], dict[str, list[Split]], list[Split], dict[str, list[Split]], list[Split], dict[str, list[Split]]]:
    all_km_splits: list[Split] = []
    km_split_map: dict[str, list[Split]] = {}
    all_lap_splits: list[Split] = []
    lap_split_map: dict[str, list[Split]] = {}
    all_workout_splits: list[Split] = []
    workout_split_map: dict[str, list[Split]] = {}

    for run in runs:
        file_path = ACTIVITY_FILES_DIR / Path(run.filename).name if run.filename else None
        km_splits: list[Split] = []
        lap_splits: list[Split] = []
        if file_path and file_path.exists():
            if run.file_format == "gpx":
                km_splits = derive_splits(run.activity_id, parse_gpx_samples(file_path), "gpx_record")
            elif run.file_format == "fit.gz":
                km_splits = derive_splits(run.activity_id, parse_fit_samples(file_path), "fit_record")
                lap_splits = enrich_lap_splits_from_km(parse_fit_laps(file_path, run.activity_id), km_splits)
        workout_splits, workout_source = choose_workout_splits(km_splits, lap_splits, run)
        run.split_source = workout_source if workout_splits else "none"
        run.workout_split_source = workout_source if workout_splits else "none"
        run.split_count = len(workout_splits)
        km_split_map[run.activity_id] = km_splits
        lap_split_map[run.activity_id] = lap_splits
        workout_split_map[run.activity_id] = workout_splits
        all_km_splits.extend(km_splits)
        all_lap_splits.extend(lap_splits)
        all_workout_splits.extend(workout_splits)

    return all_km_splits, km_split_map, all_lap_splits, lap_split_map, all_workout_splits, workout_split_map


def efficiency_score(splits: list[Split]) -> float | None:
    usable = [s for s in splits if s.lap_pace_per_km and s.lap_hr]
    if not usable:
        return None
    speeds = [1.0 / s.lap_pace_per_km for s in usable]
    hrs = [s.lap_hr for s in usable if s.lap_hr]
    if not hrs:
        return None
    return statistics.mean(speeds) / statistics.mean(hrs)


def linear_projection(xs: list[float], ys: list[float], target_x: float | None = None, target_y: float | None = None) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom
    intercept = y_mean - slope * x_mean
    if target_x is not None:
        return intercept + slope * target_x
    if target_y is not None and slope != 0:
        return (target_y - intercept) / slope
    return None


def add_rolling_metrics(runs: list[Activity]) -> None:
    for idx, run in enumerate(runs):
        window_start = run.date - timedelta(days=42)
        recent = [r for r in runs[: idx + 1] if r.date >= window_start]
        easy_window = [r for r in recent if r.flags.get("easy") and r.avg_hr and r.avg_pace_per_km and 135 <= r.avg_hr <= 145 and ((r.elevation_gain_m / r.distance_km) if r.distance_km > 0 else 999) < 15]
        if len(easy_window) >= 3:
            xs = [r.avg_hr for r in easy_window if r.avg_hr is not None]
            ys = [r.avg_pace_per_km for r in easy_window if r.avg_pace_per_km is not None]
            run.pace_at_hr140_est = linear_projection(xs, ys, target_x=140.0)
            run.hr_at_6min_est = linear_projection(xs, ys, target_y=6.0)

        tempo_window = [r for r in recent if r.flags.get("tempo_threshold")]
        if tempo_window:
            run.tempo_fitness_pace = median(r.tempo_fitness_pace for r in tempo_window if r.tempo_fitness_pace is not None)
            run.longest_continuous_tempo_min = max((r.longest_continuous_tempo_min for r in tempo_window if r.longest_continuous_tempo_min is not None), default=None)
            run.avg_tempo_hr = median(r.avg_tempo_hr for r in tempo_window if r.avg_tempo_hr is not None)
            run.best_20min_pace = median(r.best_20min_pace for r in tempo_window if r.best_20min_pace is not None)

        last_hard = next((r for r in reversed(runs[:idx]) if r.flags.get("hard")), None)
        if last_hard:
            run.days_since_last_hard = (run.date - last_hard.date).total_seconds() / 86400.0
        if last_hard and run.flags.get("easy") and 0 < (run.date - last_hard.date).total_seconds() / 86400.0 <= 3:
            run.easy_pace_after_hard = run.avg_pace_per_km

    pace_values = [r.pace_at_hr140_est for r in runs if r.pace_at_hr140_est]
    hr140_baseline = statistics.median(pace_values) if pace_values else None
    for run in runs:
        if run.avg_hr and run.avg_pace_per_km:
            hot = (run.apparent_temp_c or run.weather_temp_c or run.avg_temp_c or -999) >= 24
            low_efficiency = hr140_baseline is not None and run.avg_pace_per_km > hr140_baseline * 1.08 and (run.avg_hr or 0) > 145
            run.fatigue_flag = bool(hot or low_efficiency)


def weekly_aggregates(runs: list[Activity]) -> list[WeeklyAggregate]:
    grouped: dict[datetime, list[Activity]] = defaultdict(list)
    for run in runs:
        grouped[week_start_for(run.date)].append(run)

    output: list[WeeklyAggregate] = []
    for week_start in sorted(grouped):
        items = grouped[week_start]
        distance = sum(r.distance_km for r in items)
        time_min = sum(r.moving_time_min for r in items)
        hr_values = [r.avg_hr for r in items if r.avg_hr is not None]
        output.append(
            WeeklyAggregate(
                week_start=week_start,
                total_distance_km=distance,
                total_running_time_min=time_min,
                run_count=len(items),
                avg_run_distance=distance / len(items) if items else 0.0,
                longest_run_km=max((r.distance_km for r in items), default=0.0),
                total_elevation_gain=sum(r.elevation_gain_m for r in items),
                hard_sessions_count=sum(1 for r in items if r.flags.get("hard")),
                easy_sessions_count=sum(1 for r in items if r.flags.get("easy") or r.flags.get("recovery")),
                easy_km=sum(r.distance_km for r in items if r.flags.get("easy") or r.flags.get("recovery")),
                hard_km=sum(r.distance_km for r in items if r.flags.get("hard")),
                avg_hr_all_runs=(statistics.mean(hr_values) if hr_values else None),
            )
        )
    return output


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def rolling_average(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    for idx in range(len(values)):
        start = max(0, idx - window + 1)
        chunk = [v for v in values[start : idx + 1] if v is not None]
        result.append(sum(chunk) / len(chunk) if chunk else None)
    return result


def svg_line_chart(path: Path, title: str, labels: list[str], values: list[float | None], color: str = "#d95f19") -> None:
    usable = [(i, v) for i, v in enumerate(values) if v is not None]
    if not usable:
        return
    width, height = 900, 320
    margin = 50
    xs = [i for i, _ in usable]
    ys = [v for _, v in usable]
    min_y = min(ys)
    max_y = max(ys)
    if math.isclose(min_y, max_y):
        max_y = min_y + 1.0

    def project_x(i: int) -> float:
        return margin + (i / max(1, len(values) - 1)) * (width - 2 * margin)

    def project_y(v: float) -> float:
        return height - margin - ((v - min_y) / (max_y - min_y)) * (height - 2 * margin)

    points = " ".join(f"{project_x(i):.1f},{project_y(v):.1f}" for i, v in usable)
    x_ticks = [labels[i] for i in range(0, len(labels), max(1, len(labels) // 6))]
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fffaf2"/>',
        f'<text x="{margin}" y="30" font-size="20" font-family="Georgia" fill="#24160f">{title}</text>',
        f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="#b9aa98"/>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="#b9aa98"/>',
        f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{points}"/>',
    ]
    for val in [min_y, (min_y + max_y) / 2, max_y]:
        y = project_y(val)
        svg.append(f'<text x="10" y="{y+4:.1f}" font-size="12" font-family="Georgia" fill="#6f5c50">{val:.1f}</text>')
        svg.append(f'<line x1="{margin}" y1="{y:.1f}" x2="{width-margin}" y2="{y:.1f}" stroke="#eee3d7"/>')
    for i in range(0, len(labels), max(1, len(labels) // 6)):
        x = project_x(i)
        svg.append(f'<text x="{x:.1f}" y="{height-20}" text-anchor="middle" font-size="11" font-family="Georgia" fill="#6f5c50">{labels[i]}</text>')
    svg.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(svg), encoding="utf-8")


def svg_bar_chart(path: Path, title: str, labels: list[str], values: list[float], color: str = "#3a8f68") -> None:
    if not values:
        return
    width, height = 900, 320
    margin = 50
    max_y = max(values) or 1.0
    bar_width = max(6, (width - 2 * margin) / max(1, len(values)) - 4)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fffaf2"/>',
        f'<text x="{margin}" y="30" font-size="20" font-family="Georgia" fill="#24160f">{title}</text>',
    ]
    for i, value in enumerate(values):
        x = margin + i * ((width - 2 * margin) / max(1, len(values)))
        h = ((value / max_y) * (height - 2 * margin))
        y = height - margin - h
        svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{h:.1f}" fill="{color}" opacity="0.8"/>')
    for i in range(0, len(labels), max(1, len(labels) // 6)):
        x = margin + i * ((width - 2 * margin) / max(1, len(values))) + bar_width / 2
        svg.append(f'<text x="{x:.1f}" y="{height-20}" text-anchor="middle" font-size="11" font-family="Georgia" fill="#6f5c50">{labels[i]}</text>')
    svg.append('</svg>')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(svg), encoding="utf-8")


def hm_readiness(runs: list[Activity], weeks: list[WeeklyAggregate]) -> tuple[int, str, list[str]]:
    cutoff = runs[-1].date - timedelta(days=42)
    recent_runs = [r for r in runs if r.date >= cutoff]
    recent_weeks = [w for w in weeks if w.week_start >= cutoff - timedelta(days=cutoff.weekday())]

    tempo_runs = [r for r in recent_runs if r.flags.get("tempo_threshold")]
    easy_eff = median(r.pace_at_hr140_est for r in recent_runs if r.pace_at_hr140_est)
    longest = max((r.distance_km for r in recent_runs), default=0.0)
    weekly_distances = [w.total_distance_km for w in recent_weeks]
    avg_weekly = statistics.mean(weekly_distances) if weekly_distances else 0.0
    cv = statistics.pstdev(weekly_distances) / avg_weekly if weekly_distances and avg_weekly else 1.0
    recovery_gaps = [r.days_since_last_hard for r in recent_runs if r.days_since_last_hard is not None and r.flags.get("easy")]
    fatigue_rate = sum(1 for r in recent_runs if r.fatigue_flag) / len(recent_runs) if recent_runs else 1.0
    tempo_pace = median(r.avg_pace_per_km for r in tempo_runs if r.avg_hr and 155 <= r.avg_hr <= 160 and r.avg_pace_per_km)

    score = 0
    notes: list[str] = []

    if tempo_pace is not None and tempo_pace <= 5.33:
        score += 30
        notes.append(f"Recent tempo pace around HR155-160 is {format_pace(tempo_pace)}, which is close to or faster than sub-1:50 HM pace.")
    elif tempo_pace is not None and tempo_pace <= 5.55:
        score += 20
        notes.append(f"Recent tempo pace around HR155-160 is {format_pace(tempo_pace)}. This is in range but still needs consolidation.")
    else:
        notes.append("Recent tempo data is limited or slower than ideal for a sub-1:50 half marathon.")

    if easy_eff is not None and easy_eff <= 6.1:
        score += 20
        notes.append(f"Estimated pace at HR140 is {format_pace(easy_eff)}, a strong aerobic signal.")
    elif easy_eff is not None and easy_eff <= 6.4:
        score += 12
        notes.append(f"Estimated pace at HR140 is {format_pace(easy_eff)}, which is decent but still improvable.")
    else:
        notes.append("Easy-run efficiency is not yet strong enough or lacks enough steady data.")

    if avg_weekly >= 35 and cv <= 0.35:
        score += 20
        notes.append(f"Recent weekly volume is consistent at {avg_weekly:.1f} km/week.")
    elif avg_weekly >= 25:
        score += 12
        notes.append(f"Recent weekly volume averages {avg_weekly:.1f} km/week, workable but a bit light.")
    else:
        notes.append("Weekly running volume is on the low side for confident sub-1:50 readiness.")

    if longest >= 18:
        score += 15
        notes.append(f"Longest recent run is {longest:.1f} km, which supports HM durability.")
    elif longest >= 15:
        score += 10
        notes.append(f"Longest recent run is {longest:.1f} km, close but still short of ideal HM support.")
    else:
        notes.append("Long runs are shorter than ideal for half-marathon readiness.")

    avg_gap = statistics.mean(recovery_gaps) if recovery_gaps else None
    if avg_gap is not None and avg_gap >= 2.0 and fatigue_rate <= 0.2:
        score += 15
        notes.append("Recovery spacing between hard sessions looks healthy.")
    elif avg_gap is not None and avg_gap >= 1.5:
        score += 8
        notes.append("Recovery is acceptable, but there are some tighter turnarounds or fatigue flags.")
    else:
        notes.append("Recovery quality is hard to confirm or may need more spacing between harder sessions.")

    verdict = "Not ready yet"
    if score >= 75:
        verdict = "Likely ready"
    elif score >= 55:
        verdict = "Close, but not fully proven"
    return score, verdict, notes


def write_dashboard(runs: list[Activity], splits: list[Split], weeks: list[WeeklyAggregate]) -> None:
    score, verdict, notes = hm_readiness(runs, weeks)
    latest = runs[-1]
    recent = [r for r in runs if r.date >= runs[-1].date - timedelta(days=42)]
    pace140 = median(r.pace_at_hr140_est for r in recent if r.pace_at_hr140_est)
    tempo_pace = median(r.avg_pace_per_km for r in recent if r.flags.get("tempo_threshold") and r.avg_hr and 155 <= r.avg_hr <= 160 and r.avg_pace_per_km)
    long_runs = [r for r in recent if r.flags.get("long_run")]
    avg_long_hr = median(r.avg_hr for r in long_runs if r.avg_hr)
    avg_pace_fade = median(r.pace_fade_last_third_pct for r in long_runs if r.pace_fade_last_third_pct is not None)
    avg_easy_drift = median(r.hr_drift_pct for r in recent if r.flags.get("easy") and r.hr_drift_pct is not None)

    lines = [
        "# Running Progress Dashboard",
        "",
        f"Generated from Strava export through {latest.date.strftime('%Y-%m-%d')}",
        "",
        "## Half-Marathon Readiness",
        "",
        f"- Verdict: {verdict}",
        f"- Score: {score}/100",
        "- Goal pace: 5:13/km for sub-1:50 HM",
        "",
    ]
    for note in notes:
        lines.append(f"- {note}")

    lines += [
        "",
        "## Key Metrics",
        "",
        f"- Pace at HR140 (6-week median estimate): {format_pace(pace140)}",
        f"- Tempo pace at HR155-160: {format_pace(tempo_pace)}",
        f"- Average HR during long runs: {avg_long_hr:.0f} bpm" if avg_long_hr is not None else "- Average HR during long runs: -",
        f"- Pace fade in last third of long runs: {avg_pace_fade:.1f}%" if avg_pace_fade is not None else "- Pace fade in last third of long runs: unavailable",
        f"- HR drift on easy runs: {avg_easy_drift:.1f}%" if avg_easy_drift is not None else "- HR drift on easy runs: unavailable",
        "",
        "## Notes",
        "",
        "- Session classification is inferred from distance, heart rate, elevation, and naming patterns, so treat it as a coaching aid rather than ground truth.",
        "- Split-based metrics are derived from GPX/FIT record streams when present; activities without enough raw samples stay at activity-level only.",
        "- Weather adjustment is limited by missing weather fields in many activities, so unusually slow/high-HR days are flagged conservatively.",
        "",
        "## Output Files",
        "",
        "- `analysis/per_activity_runs.csv`",
        "- `analysis/run_splits.csv`",
        "- `analysis/weekly_aggregates.csv`",
        "- `analysis/key_metrics.csv`",
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "dashboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_outputs() -> None:
    runs = load_runs()
    km_splits, km_split_map, lap_splits, lap_split_map, workout_splits, workout_split_map = attach_split_metrics(runs)
    classify_runs(runs, workout_split_map)
    apply_split_derived_metrics(runs, km_split_map)
    add_rolling_metrics(runs)
    weeks = weekly_aggregates(runs)

    per_activity_rows = []
    for run in runs:
        row = {
            "activity_id": run.activity_id,
            "date": run.date.strftime("%Y-%m-%d"),
            "week_start": week_start_for(run.date).strftime("%Y-%m-%d"),
            "name": run.activity_name,
            "type": run.activity_type,
            "distance_km": round(run.distance_km, 3),
            "moving_time_min": round(run.moving_time_min, 3),
            "elapsed_time_min": round(run.elapsed_time_min, 3),
            "elevation_gain_m": round(run.elevation_gain_m, 1),
            "avg_hr": round(run.avg_hr, 1) if run.avg_hr is not None else None,
            "max_hr": round(run.max_hr, 1) if run.max_hr is not None else None,
            "avg_speed_mps": round(run.avg_speed_mps, 3) if run.avg_speed_mps is not None else None,
            "avg_pace_sec_km": round(run.avg_pace_per_km * 60, 1) if run.avg_pace_per_km is not None else None,
            "cadence": round(run.avg_cadence, 1) if run.avg_cadence is not None else None,
            "calories": round(run.calories, 1) if run.calories is not None else None,
            "relative_effort": run.relative_effort,
            "training_load": run.training_load,
            "flagged": run.flagged,
            "raw_file": run.filename,
            "workout_split_source": run.workout_split_source,
            "is_run": True,
            "run_class": run.primary_class,
            "is_hard": run.flags.get("hard", False),
            "is_easy": bool(run.flags.get("easy") or run.flags.get("recovery")),
        }
        per_activity_rows.append(row)

    write_csv(
        OUTPUT_DIR / "per_activity_runs.csv",
        list(per_activity_rows[0].keys()) if per_activity_rows else [],
        per_activity_rows,
    )
    write_csv(
        OUTPUT_DIR / "normalized_activities.csv",
        list(per_activity_rows[0].keys()) if per_activity_rows else [],
        per_activity_rows,
    )

    km_split_rows = [
        {
            "activity_id": s.activity_id,
            "split_num": s.lap_number,
            "split_distance_km": round(s.lap_distance_km, 3),
            "split_time_sec": round(s.lap_time_min * 60, 1),
            "split_pace_sec_km": round(s.lap_pace_per_km * 60, 1) if s.lap_pace_per_km is not None else None,
            "split_avg_hr": round(s.lap_hr, 1) if s.lap_hr is not None else None,
            "split_elevation_m": round(s.lap_elevation_m, 1) if s.lap_elevation_m is not None else None,
            "source": s.source,
        }
        for s in km_splits
    ]
    lap_split_rows = [
        {
            "activity_id": s.activity_id,
            "split_num": s.lap_number,
            "split_distance_km": round(s.lap_distance_km, 3),
            "split_time_sec": round(s.lap_time_min * 60, 1),
            "split_pace_sec_km": round(s.lap_pace_per_km * 60, 1) if s.lap_pace_per_km is not None else None,
            "split_avg_hr": round(s.lap_hr, 1) if s.lap_hr is not None else None,
            "split_elevation_m": round(s.lap_elevation_m, 1) if s.lap_elevation_m is not None else None,
            "source": s.source,
        }
        for s in lap_splits
    ]
    workout_split_rows = [
        {
            "activity_id": s.activity_id,
            "split_num": s.lap_number,
            "split_distance_km": round(s.lap_distance_km, 3),
            "split_time_sec": round(s.lap_time_min * 60, 1),
            "split_pace_sec_km": round(s.lap_pace_per_km * 60, 1) if s.lap_pace_per_km is not None else None,
            "split_avg_hr": round(s.lap_hr, 1) if s.lap_hr is not None else None,
            "split_elevation_m": round(s.lap_elevation_m, 1) if s.lap_elevation_m is not None else None,
            "source": s.source,
        }
        for s in workout_splits
    ]
    write_csv(OUTPUT_DIR / "run_splits.csv", list(km_split_rows[0].keys()) if km_split_rows else ["activity_id"], km_split_rows)
    write_csv(OUTPUT_DIR / "splits.csv", list(km_split_rows[0].keys()) if km_split_rows else ["activity_id"], km_split_rows)
    write_csv(OUTPUT_DIR / "splits_km.csv", list(km_split_rows[0].keys()) if km_split_rows else ["activity_id"], km_split_rows)
    write_csv(OUTPUT_DIR / "splits_laps.csv", list(lap_split_rows[0].keys()) if lap_split_rows else ["activity_id"], lap_split_rows)
    write_csv(OUTPUT_DIR / "workout_splits.csv", list(workout_split_rows[0].keys()) if workout_split_rows else ["activity_id"], workout_split_rows)

    week_rows = [
        {
            "week_start": w.week_start.strftime("%Y-%m-%d"),
            "total_runs": w.run_count,
            "total_distance_km": round(w.total_distance_km, 2),
            "total_time_min": round(w.total_running_time_min, 2),
            "avg_run_distance": round(w.avg_run_distance, 2),
            "longest_run_km": round(w.longest_run_km, 2),
            "total_elevation_gain_m": round(w.total_elevation_gain, 1),
            "hard_sessions": w.hard_sessions_count,
            "easy_sessions": w.easy_sessions_count,
            "easy_km": round(w.easy_km, 2),
            "hard_km": round(w.hard_km, 2),
            "avg_hr_all_runs": round(w.avg_hr_all_runs, 1) if w.avg_hr_all_runs is not None else None,
        }
        for w in weeks
    ]
    write_csv(OUTPUT_DIR / "weekly_aggregates.csv", list(week_rows[0].keys()) if week_rows else ["week_start"], week_rows)
    write_csv(OUTPUT_DIR / "weekly_summary.csv", list(week_rows[0].keys()) if week_rows else ["week_start"], week_rows)

    key_rows = []
    for run in runs:
        key_rows.append(
            {
                "date": run.date.strftime("%Y-%m-%d"),
                "activity_id": run.activity_id,
                "pace_at_hr140": round(run.pace_at_hr140_est * 60, 1) if run.pace_at_hr140_est is not None else None,
                "hr_at_600_pace": round(run.hr_at_6min_est, 2) if run.hr_at_6min_est is not None else None,
                "best_20min_pace": round(run.best_20min_pace * 60, 1) if run.best_20min_pace is not None else None,
                "avg_tempo_pace": round(run.tempo_fitness_pace * 60, 1) if run.tempo_fitness_pace is not None else None,
                "avg_tempo_hr": round(run.avg_tempo_hr, 1) if run.avg_tempo_hr is not None else None,
                "longest_continuous_tempo_min": round(run.longest_continuous_tempo_min, 2) if run.longest_continuous_tempo_min is not None else None,
                "longest_run_last6w": round(run.distance_km, 2) if run.flags.get("long_run") else None,
                "easy_pace_48h_after_hard": round(run.easy_pace_after_hard * 60, 1) if run.easy_pace_after_hard is not None else None,
                "days_since_last_hard": round(run.days_since_last_hard, 2) if run.days_since_last_hard is not None else None,
                "fatigue_flag": run.fatigue_flag,
                "avg_long_run_hr_drift": round(run.hr_drift_pct, 2) if run.hr_drift_pct is not None else None,
            }
        )
    write_csv(OUTPUT_DIR / "key_metrics.csv", list(key_rows[0].keys()) if key_rows else ["date"], key_rows)

    write_dashboard(runs, km_splits, weeks)

    week_labels = [w.week_start.strftime("%Y-%m-%d") for w in weeks]
    svg_line_chart(CHARTS_DIR / "weekly_mileage_trend.svg", "Weekly Mileage Trend", week_labels, [w.total_distance_km for w in weeks])
    svg_line_chart(CHARTS_DIR / "pace_at_hr140_trend.svg", "Pace at HR140 Trend", [r.date.strftime("%Y-%m-%d") for r in runs], [r.pace_at_hr140_est for r in runs], color="#3a8f68")
    svg_line_chart(CHARTS_DIR / "tempo_pace_trend.svg", "Tempo Pace Trend", [r.date.strftime("%Y-%m-%d") for r in runs], [r.tempo_fitness_pace for r in runs], color="#3e6fb6")
    svg_line_chart(CHARTS_DIR / "long_run_distance_trend.svg", "Long Run Distance Trend", [r.date.strftime("%Y-%m-%d") for r in runs], [r.distance_km if r.flags.get("long_run") else None for r in runs], color="#b64d3e")
    svg_bar_chart(CHARTS_DIR / "elevation_load_trend.svg", "Weekly Elevation Load Trend", week_labels, [w.total_elevation_gain for w in weeks], color="#8a6b2c")
    ratio_values = [w.hard_sessions_count / w.easy_sessions_count if w.easy_sessions_count else float(w.hard_sessions_count) for w in weeks]
    svg_line_chart(CHARTS_DIR / "hard_vs_easy_ratio.svg", "Hard vs Easy Sessions Ratio", week_labels, ratio_values, color="#7d4fb3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract running progress data from a Strava export.")
    parser.add_argument("command", choices=["build"], help="Generate structured analysis outputs")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "build":
        build_outputs()
        print(f"Wrote analysis outputs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
