import json
from datetime import datetime
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path.cwd()
METADATA_DIR = PROJECT_DIR / "reports" / "r2_submissions"
REPORT_DIR = PROJECT_DIR / "reports"
SUBMISSION_CSV = REPORT_DIR / "submissions.csv"
LATEST_REPORT = REPORT_DIR / "submissions_latest.txt"


def load_metadata_file(path):
        with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)

        return {
                "submitted_at_utc": data.get("submitted_at_utc", ""),
                "observer_name": data.get("observer_name", ""),
                "observer_email": data.get("observer_email", ""),
                "program": data.get("program", ""),
                "original_filename": data.get("original_filename", ""),
                "target_count_estimate": data.get("target_count_estimate", ""),
                "size_bytes": data.get("size_bytes", ""),
                "content_type": data.get("content_type", ""),
                "stored_file_key": data.get("stored_file_key", ""),
                "stored_metadata_key": data.get("stored_metadata_key", ""),
                "local_metadata_file": str(path),
                "notes": data.get("notes", ""),
        }


def collect_submissions():
        if not METADATA_DIR.exists():
                return pd.DataFrame()

        rows = []

        for path in sorted(METADATA_DIR.glob("*.metadata.json")):
                try:
                        rows.append(load_metadata_file(path))
                except Exception as exc:
                        rows.append({
                                "submitted_at_utc": "",
                                "observer_name": "",
                                "observer_email": "",
                                "program": "",
                                "original_filename": path.name,
                                "target_count_estimate": "",
                                "size_bytes": "",
                                "content_type": "",
                                "stored_file_key": "",
                                "stored_metadata_key": "",
                                "local_metadata_file": str(path),
                                "notes": f"metadata parse failed: {exc}",
                        })

        if not rows:
                return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.sort_values("submitted_at_utc", ascending=False, na_position="last")
        return df


def write_text_report(df, path):
        lines = [
                f"SkyQ submission report generated: {datetime.now().isoformat(timespec='seconds')}",
                f"Total known submissions: {len(df)}",
                "",
        ]

        if df.empty:
                lines.append("No R2 submission metadata files found.")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return

        for _, row in df.iterrows():
                lines.extend([
                        f"Submitted UTC: {row.get('submitted_at_utc', '')}",
                        f"Observer: {row.get('observer_name', '')} <{row.get('observer_email', '')}>",
                        f"Program: {row.get('program', '')}",
                        f"File: {row.get('original_filename', '')}",
                        f"Estimated targets: {row.get('target_count_estimate', '')}",
                        f"Size bytes: {row.get('size_bytes', '')}",
                        f"R2 key: {row.get('stored_file_key', '')}",
                        f"Notes: {row.get('notes', '')}",
                        "",
                ])

        path.write_text("\n".join(lines), encoding="utf-8")


def print_submission_summary(df, max_rows=8):
        print("Submission summary:", flush=True)

        if df.empty:
                print("No known R2 submissions.", flush=True)
                return

        columns = [
                "submitted_at_utc",
                "observer_name",
                "program",
                "original_filename",
                "target_count_estimate",
        ]
        print(df[columns].head(max_rows).to_string(index=False), flush=True)

        if len(df) > max_rows:
                print(f"... {len(df) - max_rows} more submissions in {SUBMISSION_CSV}", flush=True)


def make_submission_report():
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        df = collect_submissions()

        if df.empty:
                df.to_csv(SUBMISSION_CSV, index=False)
        else:
                df.to_csv(SUBMISSION_CSV, index=False)

        write_text_report(df, LATEST_REPORT)
        print_submission_summary(df)
        print(f"Submission CSV: {SUBMISSION_CSV}", flush=True)
        print(f"Submission report: {LATEST_REPORT}", flush=True)

        return {
                "submission_count": len(df),
                "csv_path": str(SUBMISSION_CSV),
                "report_path": str(LATEST_REPORT),
        }


if __name__ == "__main__":
        print(make_submission_report())
