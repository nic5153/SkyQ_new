import os
import platform
import sys
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path.cwd()
REPORT_DIR = PROJECT_DIR / "reports"
LATEST_REPORT = REPORT_DIR / "skyq_run_latest.txt"


def bool_text(value):
        return "yes" if value else "no"


def as_text(value):
        if value is None:
                return ""

        return str(value)


def write_section(lines, title, values):
        lines.extend([title, "-" * len(title)])

        for key, value in values:
                lines.append(f"{key}: {as_text(value)}")

        lines.append("")


def category_counts(plan):
        if plan is None or "skyq_category" not in plan.columns:
                return []

        counts = plan["skyq_category"].value_counts()
        return [(str(category), int(count)) for category, count in counts.items()]


def observer_product_paths():
        product_dir = PROJECT_DIR / "data" / "products" / "latest"

        return [
                ("Product directory", product_dir),
                ("Manifest CSV", product_dir / "manifest.csv"),
                ("Observing plan with products", product_dir / "observing_plan_with_products.csv"),
                ("Pages directory", product_dir / "pages"),
                ("Altitude/airmass directory", product_dir / "altitude_airmass"),
                ("Sky-path directory", product_dir / "sky_path"),
        ]


def write_operator_report(summary):
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"skyq_run_{stamp}.txt"

        lines = [
                "SkyQ Operator Run Report",
                "========================",
                "",
        ]

        write_section(lines, "Run", [
                ("Generated local time", datetime.now().isoformat(timespec="seconds")),
                ("Status", summary.get("status", "unknown")),
                ("Project directory", PROJECT_DIR),
                ("Python executable", sys.executable),
                ("Python version", sys.version.replace("\n", " ")),
                ("Host", platform.node()),
                ("Platform", platform.platform()),
        ])

        r2 = summary.get("r2", {})
        write_section(lines, "Cloudflare R2 Sync", [
                ("Enabled", bool_text(r2.get("enabled"))),
                ("Bucket", r2.get("bucket", os.environ.get("R2_BUCKET", ""))),
                ("Prefix", r2.get("prefix", os.environ.get("R2_PREFIX", ""))),
                ("Objects seen", r2.get("objects_seen", "")),
                ("Target files downloaded", r2.get("downloaded_files", 0)),
                ("Metadata files downloaded", r2.get("downloaded_metadata", 0)),
        ])

        submissions = summary.get("submissions", {})
        write_section(lines, "Submissions", [
                ("Known submissions", submissions.get("submission_count", 0)),
                ("Submission CSV", submissions.get("csv_path", "")),
                ("Submission report", submissions.get("report_path", "")),
        ])

        inbox = summary.get("inbox", {})
        write_section(lines, "Inbox Processing", [
                ("Files found", inbox.get("files_found", 0)),
                ("Accepted files", inbox.get("accepted_files", 0)),
                ("Rejected files", inbox.get("rejected_files", 0)),
                ("Accepted target rows", inbox.get("accepted_targets", "")),
                ("Inbox report", inbox.get("report_path", "")),
        ])

        write_section(lines, "Master Table", [
                ("Master target rows", summary.get("master_count", "")),
                ("Master CSV", PROJECT_DIR / "data" / "master.csv"),
        ])

        plan = summary.get("plan")
        write_section(lines, "Observing Plan", [
                ("Observing plan rows", len(plan) if plan is not None else ""),
                ("Observing plan CSV", PROJECT_DIR / "data" / "observing_plan.csv"),
        ])

        counts = category_counts(plan)
        lines.extend(["SkyQ Category Counts", "-------------------"])

        if counts:
                for category, count in counts:
                        lines.append(f"{category}: {count}")
        else:
                lines.append("No category counts available.")

        lines.append("")

        write_section(lines, "Observer Products", [
                ("Product rows", summary.get("product_count", "")),
                *observer_product_paths(),
        ])

        error = summary.get("error")

        if error:
                write_section(lines, "Error", [
                        ("Message", error),
                ])

        report_text = "\n".join(lines)
        report_path.write_text(report_text + "\n", encoding="utf-8")
        LATEST_REPORT.write_text(report_text + "\n", encoding="utf-8")

        print(f"Operator run report: {report_path}", flush=True)
        print(f"Latest operator report: {LATEST_REPORT}", flush=True)

        return {
                "report_path": str(report_path),
                "latest_report_path": str(LATEST_REPORT),
        }
