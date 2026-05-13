from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DEFAULT_ZIP = DATA_DIR / "export_6221222.zip"
EXPORT_DIR = DATA_DIR / "export"


def unzip(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        print(f"Extracting {len(members)} files to {dest} ...")
        zf.extractall(dest)
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Strava export zip to data/export/")
    parser.add_argument("zip", nargs="?", default=str(DEFAULT_ZIP), help="Path to the export zip (default: data/export_6221222.zip)")
    args = parser.parse_args()

    zip_path = Path(args.zip)
    if not zip_path.exists():
        raise SystemExit(f"Zip file not found: {zip_path}")

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    unzip(zip_path, EXPORT_DIR)


if __name__ == "__main__":
    main()
