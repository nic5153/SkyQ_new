import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from queue_merge.r2_sync import build_s3_client, is_target_sheet, list_objects, missing_env


PROJECT_DIR = Path.cwd()
STATE_PATH = PROJECT_DIR / "data" / "r2_trigger_state.json"
REPORT_DIR = PROJECT_DIR / "reports"
LATEST_REPORT = REPORT_DIR / "trigger_latest.txt"


def load_state():
        if not STATE_PATH.exists():
                return {"seen": {}}

        with STATE_PATH.open("r", encoding="utf-8") as handle:
                return json.load(handle)


def save_state(state):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

        with STATE_PATH.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)


def target_objects():
        missing = missing_env()

        if missing:
                raise RuntimeError(f"R2 trigger missing required environment variables: {', '.join(missing)}")

        bucket = os.environ.get("R2_BUCKET", "skyq-submissions")
        prefix = os.environ.get("R2_PREFIX", "incoming/")
        client = build_s3_client()
        objects = {}

        for item in list_objects(client, bucket, prefix):
                key = item["Key"]

                if not is_target_sheet(key):
                        continue

                objects[key] = {
                        "etag": str(item.get("ETag", "")).strip('"'),
                        "size": int(item.get("Size", 0)),
                        "last_modified": item.get("LastModified").isoformat() if item.get("LastModified") else "",
                }

        return bucket, prefix, objects


def active_skyq_jobs(job_name):
        command = [
                "squeue",
                "-h",
                "-u",
                os.environ.get("USER", ""),
                "-n",
                job_name,
                "-t",
                "PENDING,RUNNING,CONFIGURING,COMPLETING",
                "-o",
                "%i %T %j",
        ]

        try:
                result = subprocess.run(command, check=False, capture_output=True, text=True)
        except FileNotFoundError:
                return []

        if result.returncode != 0:
                return []

        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def submit_pipeline(sbatch_path):
        result = subprocess.run(
                ["sbatch", str(sbatch_path)],
                check=False,
                capture_output=True,
                text=True,
        )

        output = (result.stdout + result.stderr).strip()

        if result.returncode != 0:
                raise RuntimeError(f"sbatch failed with exit code {result.returncode}: {output}")

        match = re.search(r"Submitted batch job\s+(\d+)", output)
        job_id = match.group(1) if match else ""

        return job_id, output


def write_report(summary):
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"trigger_{stamp}.txt"

        lines = [
                "SkyQ Submission Trigger Report",
                "==============================",
                "",
                f"Generated local time: {datetime.now().isoformat(timespec='seconds')}",
                f"Status: {summary['status']}",
                f"Bucket: {summary['bucket']}",
                f"Prefix: {summary['prefix']}",
                f"Objects seen: {summary['objects_seen']}",
                f"New submissions: {len(summary['new_submissions'])}",
                f"Active jobs: {len(summary['active_jobs'])}",
                f"Submitted job ID: {summary.get('submitted_job_id', '')}",
                "",
                "New Submission Keys",
                "-------------------",
        ]

        if summary["new_submissions"]:
                lines.extend(summary["new_submissions"])
        else:
                lines.append("None")

        lines.extend(["", "Active Jobs", "-----------"])

        if summary["active_jobs"]:
                lines.extend(summary["active_jobs"])
        else:
                lines.append("None")

        report_text = "\n".join(lines) + "\n"
        report_path.write_text(report_text, encoding="utf-8")
        LATEST_REPORT.write_text(report_text, encoding="utf-8")

        return report_path


def trigger_if_needed(sbatch_path="runscript_skyq.sbatch", job_name=None, dry_run=False, force=False, mark_seen=False):
        job_name = job_name or os.environ.get("SKYQ_JOB_NAME", "skyq")
        sbatch_path = Path(sbatch_path)
        state = load_state()
        seen = state.setdefault("seen", {})
        bucket, prefix, objects = target_objects()

        new_submissions = [
                key for key, details in objects.items()
                if force or seen.get(key) != details["etag"]
        ]

        active_jobs = active_skyq_jobs(job_name)
        status = "no_new_submissions"
        submitted_job_id = ""
        sbatch_output = ""

        if mark_seen:
                for key, details in objects.items():
                        seen[key] = details["etag"]

                state["last_mark_seen_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                save_state(state)
                status = "marked_seen"
                new_submissions = []
        elif new_submissions:
                if active_jobs:
                        status = "skyq_job_already_active"
                elif dry_run:
                        status = "dry_run_would_submit"
                else:
                        submitted_job_id, sbatch_output = submit_pipeline(sbatch_path)
                        status = "submitted"

                        for key, details in objects.items():
                                seen[key] = details["etag"]

                        state["last_trigger_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                        state["last_submitted_job_id"] = submitted_job_id
                        save_state(state)

        summary = {
                "status": status,
                "bucket": bucket,
                "prefix": prefix,
                "objects_seen": len(objects),
                "new_submissions": new_submissions,
                "active_jobs": active_jobs,
                "submitted_job_id": submitted_job_id,
                "sbatch_output": sbatch_output,
        }
        report_path = write_report(summary)
        summary["report_path"] = str(report_path)

        print(f"[trigger] Status: {status}", flush=True)
        print(f"[trigger] R2 target objects seen: {len(objects)}", flush=True)
        print(f"[trigger] New submissions: {len(new_submissions)}", flush=True)
        print(f"[trigger] Active {job_name} jobs: {len(active_jobs)}", flush=True)

        if submitted_job_id:
                print(f"[trigger] Submitted SkyQ job: {submitted_job_id}", flush=True)

        print(f"[trigger] Report: {report_path}", flush=True)
        return summary


def main():
        parser = argparse.ArgumentParser(description="Submit the SkyQ Slurm pipeline when new R2 submissions exist.")
        parser.add_argument("--sbatch", default=os.environ.get("SKYQ_SBATCH", "runscript_skyq.sbatch"))
        parser.add_argument("--job-name", default=os.environ.get("SKYQ_JOB_NAME", "skyq"))
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--mark-seen", action="store_true", help="Record current R2 submissions as already seen without submitting a job.")
        args = parser.parse_args()

        trigger_if_needed(
                sbatch_path=args.sbatch,
                job_name=args.job_name,
                dry_run=args.dry_run,
                force=args.force,
                mark_seen=args.mark_seen,
        )


if __name__ == "__main__":
        main()
