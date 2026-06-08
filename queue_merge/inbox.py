import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import astropy.units as u
from astropy.coordinates import SkyCoord

from queue_merge.merge import alias_check, check_cols, standardize


PROJECT_DIR = Path.cwd()
INBOX_DIR = PROJECT_DIR / "data" / "inbox"
RAW_DIR = PROJECT_DIR / "data" / "raw"
ARCHIVE_DIR = PROJECT_DIR / "data" / "archive"
REJECTED_DIR = PROJECT_DIR / "data" / "rejected"
REPORT_DIR = PROJECT_DIR / "reports"

SUPPORTED_SUFFIXES = {".csv", ".tsv", ".txt"}


def read_submission(path):
        suffix = path.suffix.lower()

        if suffix == ".csv":
                return pd.read_csv(path)

        return pd.read_csv(path, sep=r"\s+")


def validate_coordinates(df):
        ra = df["ra"].astype(str)
        dec = df["dec"].astype(str)
        sexagesimal = ra.str.contains(":").any() or dec.str.contains(":").any()

        if sexagesimal:
                SkyCoord(ra=ra.values, dec=dec.values, unit=(u.hourangle, u.deg))
                return

        SkyCoord(
                ra=pd.to_numeric(df["ra"], errors="raise").values * u.deg,
                dec=pd.to_numeric(df["dec"], errors="raise").values * u.deg,
        )


def unique_path(directory, filename):
        path = directory / filename

        if not path.exists():
                return path

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return directory / f"{path.stem}_{stamp}{path.suffix}"


def process_one_file(path):
        df = read_submission(path)
        df = alias_check(df)
        normalized = standardize(df.columns)

        if not check_cols(normalized):
                return False, f"missing required columns. Found columns: {normalized}", 0

        if len(df) == 0:
                return False, "file contains no target rows", 0

        if df[["name", "ra", "dec"]].isna().any().any():
                return False, "one or more rows have blank name, ra, or dec", len(df)

        try:
                validate_coordinates(df)
        except Exception as exc:
                return False, f"coordinate validation failed: {exc}", len(df)

        raw_path = unique_path(RAW_DIR, path.name)
        archive_path = unique_path(ARCHIVE_DIR, path.name)

        shutil.copy2(path, raw_path)
        shutil.move(path, archive_path)

        return True, f"accepted {len(df)} targets -> {raw_path}", len(df)


def process_inbox():
        for directory in [INBOX_DIR, RAW_DIR, ARCHIVE_DIR, REJECTED_DIR, REPORT_DIR]:
                directory.mkdir(parents=True, exist_ok=True)

        files = sorted(
                path for path in INBOX_DIR.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        )

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"inbox_report_{stamp}.txt"

        accepted_files = 0
        rejected_files = 0
        accepted_targets = 0
        lines = [
                f"SkyQ inbox report: {stamp}",
                f"Inbox directory: {INBOX_DIR}",
                f"Files found: {len(files)}",
                "",
        ]

        for path in files:
                ok, message, rows = process_one_file(path)

                if ok:
                        accepted_files += 1
                        accepted_targets += rows
                        lines.append(f"ACCEPT {path.name}: {message}")
                        continue

                rejected_files += 1
                rejected_path = unique_path(REJECTED_DIR, path.name)
                shutil.move(path, rejected_path)
                lines.append(f"REJECT {path.name}: {message}")

        lines.extend([
                "",
                f"Accepted files: {accepted_files}",
                f"Rejected files: {rejected_files}",
                f"Accepted target rows: {accepted_targets}",
        ])

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        return {
                "files_found": len(files),
                "accepted_files": accepted_files,
                "rejected_files": rejected_files,
                "accepted_targets": accepted_targets,
                "report_path": str(report_path),
        }


if __name__ == "__main__":
        print(process_inbox())
