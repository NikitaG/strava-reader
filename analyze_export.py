from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "export"
ACTIVITIES_CSV = DATA_DIR / "activities.csv"
NOTES_DIR = ROOT / "notes"


@dataclass
class Activity:
    activity_id: str
    date: datetime
    name: str
    sport: str
    description: str
    distance_m: float
    moving_time_s: int
    elapsed_time_s: int
    elevation_gain_m: float
    avg_heartrate: float | None
    max_heartrate: float | None
    calories: float | None
    gear: str
    filename: str
    media: list[str]
    raw: dict[str, str]

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def pace_min_per_km(self) -> float | None:
        if self.sport.lower() not in {"run", "walk", "hike"}:
            return None
        if self.distance_km <= 0 or self.moving_time_s <= 0:
            return None
        return (self.moving_time_s / 60.0) / self.distance_km

    @property
    def speed_kph(self) -> float | None:
        if self.distance_km <= 0 or self.moving_time_s <= 0:
            return None
        return self.distance_km / (self.moving_time_s / 3600.0)


def parse_float(raw: str) -> float | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(raw: str) -> int:
    value = parse_float(raw)
    return int(value or 0)


def parse_date(raw: str) -> datetime:
    return datetime.strptime(raw.strip(), "%b %d, %Y, %I:%M:%S %p")


def format_seconds(total_seconds: int) -> str:
    hours, remainder = divmod(max(total_seconds, 0), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_pace(pace: float | None) -> str:
    if pace is None:
        return "-"
    total_seconds = round(pace * 60)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d} /km"


def format_speed(speed: float | None) -> str:
    if speed is None:
        return "-"
    return f"{speed:.1f} kph"


def load_activities() -> tuple[list[str], list[Activity]]:
    with ACTIVITIES_CSV.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        activities: list[Activity] = []
        for row in reader:
            media = [item for item in (row.get("Media", "") or "").split("|") if item]
            activities.append(
                Activity(
                    activity_id=(row.get("Activity ID", "") or "").strip(),
                    date=parse_date(row.get("Activity Date", "")),
                    name=(row.get("Activity Name", "") or "Untitled activity").strip(),
                    sport=(row.get("Activity Type", "") or row.get("Type", "Unknown")).strip() or "Unknown",
                    description=(row.get("Activity Description", "") or "").strip(),
                    distance_m=parse_float(row.get("Distance", "")) or 0.0,
                    moving_time_s=parse_int(row.get("Moving Time", "")),
                    elapsed_time_s=parse_int(row.get("Elapsed Time", "")),
                    elevation_gain_m=parse_float(row.get("Elevation Gain", "")) or 0.0,
                    avg_heartrate=parse_float(row.get("Average Heart Rate", "")),
                    max_heartrate=parse_float(row.get("Max Heart Rate", "")),
                    calories=parse_float(row.get("Calories", "")),
                    gear=(row.get("Activity Gear", "") or row.get("Gear", "")).strip(),
                    filename=(row.get("Filename", "") or "").strip(),
                    media=media,
                    raw=row,
                )
            )
    activities.sort(key=lambda item: item.date, reverse=True)
    return fieldnames, activities


def filter_activities(
    activities: Iterable[Activity],
    sport: str | None = None,
    year: int | None = None,
    query: str | None = None,
) -> list[Activity]:
    items = list(activities)
    if sport:
        wanted = sport.lower()
        items = [item for item in items if item.sport.lower() == wanted]
    if year is not None:
        items = [item for item in items if item.date.year == year]
    if query:
        lowered = query.lower()
        items = [item for item in items if lowered in item.name.lower() or lowered in item.description.lower()]
    return items


def summarize(activities: list[Activity]) -> str:
    total_distance = sum(item.distance_km for item in activities)
    total_moving_time = sum(item.moving_time_s for item in activities)
    by_sport: dict[str, dict[str, float | int]] = defaultdict(lambda: {"count": 0, "distance": 0.0, "time": 0})
    by_year: dict[int, dict[str, float | int]] = defaultdict(lambda: {"count": 0, "distance": 0.0, "time": 0})

    for item in activities:
        by_sport[item.sport]["count"] += 1
        by_sport[item.sport]["distance"] += item.distance_km
        by_sport[item.sport]["time"] += item.moving_time_s

        by_year[item.date.year]["count"] += 1
        by_year[item.date.year]["distance"] += item.distance_km
        by_year[item.date.year]["time"] += item.moving_time_s

    lines = [
        f"Activities: {len(activities)}",
        f"Distance: {total_distance:.1f} km",
        f"Moving time: {format_seconds(total_moving_time)}",
        "",
        "By sport:",
    ]
    for sport, stats in sorted(by_sport.items(), key=lambda pair: pair[1]["distance"], reverse=True):
        lines.append(f"- {sport}: {stats['count']} activities, {stats['distance']:.1f} km, {format_seconds(int(stats['time']))}")

    lines.append("")
    lines.append("By year:")
    for year, stats in sorted(by_year.items(), reverse=True):
        lines.append(f"- {year}: {stats['count']} activities, {stats['distance']:.1f} km, {format_seconds(int(stats['time']))}")

    return "\n".join(lines)


def markdown_note(activities: list[Activity], title: str) -> str:
    lines = [f"# {title}", "", f"Activities: {len(activities)}", ""]
    for item in activities:
        lines.append(f"## {item.date.strftime('%Y-%m-%d')} - {item.name}")
        lines.append("")
        lines.append(f"- Sport: {item.sport}")
        lines.append(f"- Distance: {item.distance_km:.2f} km")
        lines.append(f"- Moving time: {format_seconds(item.moving_time_s)}")
        lines.append(f"- Elapsed time: {format_seconds(item.elapsed_time_s)}")
        lines.append(f"- Pace: {format_pace(item.pace_min_per_km)}")
        lines.append(f"- Speed: {format_speed(item.speed_kph)}")
        lines.append(f"- Elevation gain: {item.elevation_gain_m:.1f} m")
        lines.append(f"- Avg HR: {int(item.avg_heartrate) if item.avg_heartrate is not None else '-'}")
        lines.append(f"- Max HR: {int(item.max_heartrate) if item.max_heartrate is not None else '-'}")
        lines.append(f"- Calories: {int(item.calories) if item.calories is not None else '-'}")
        lines.append(f"- Gear: {item.gear or '-'}")
        lines.append(f"- Raw file: {item.filename or '-'}")
        lines.append(f"- Media count: {len(item.media)}")
        if item.description:
            lines.append(f"- Description: {item.description}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze a Strava export without running a web server.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("fields", help="List all CSV columns in activities.csv")
    subparsers.add_parser("summary", help="Print a high-level summary of the export")

    notes = subparsers.add_parser("notes", help="Export filtered activities to a Markdown note")
    notes.add_argument("--sport", help="Filter by exact sport, e.g. Run")
    notes.add_argument("--year", type=int, help="Filter by year, e.g. 2026")
    notes.add_argument("--query", help="Filter by activity name or description")
    notes.add_argument("--limit", type=int, default=50, help="Maximum number of activities to include")
    notes.add_argument("--out", type=Path, default=NOTES_DIR / "activities.md", help="Output markdown path")
    notes.add_argument("--title", default="Strava Activities", help="Markdown title")

    inspect_cmd = subparsers.add_parser("inspect", help="Show all raw fields for one activity")
    inspect_cmd.add_argument("activity_id", help="Activity ID from activities.csv")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    fieldnames, activities = load_activities()

    if args.command == "fields":
        print(f"activities.csv columns: {len(fieldnames)}")
        for name in fieldnames:
            print(f"- {name}")
        return

    if args.command == "summary":
        print(summarize(activities))
        return

    if args.command == "notes":
        filtered = filter_activities(activities, sport=args.sport, year=args.year, query=args.query)
        if args.limit > 0:
            filtered = filtered[: args.limit]
        content = markdown_note(filtered, args.title)
        write_note(args.out, content)
        print(f"Wrote {len(filtered)} activities to {args.out}")
        return

    if args.command == "inspect":
        target = next((item for item in activities if item.activity_id == args.activity_id), None)
        if target is None:
            raise SystemExit(f"Activity not found: {args.activity_id}")
        for key, value in target.raw.items():
            print(f"{key}: {value}")
        return


if __name__ == "__main__":
    if not ACTIVITIES_CSV.exists():
        raise SystemExit(f"Missing export file: {ACTIVITIES_CSV}")
    main()
