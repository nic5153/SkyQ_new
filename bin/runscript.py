from queue_merge.r2_sync import sync_r2_submissions
from queue_merge.submission_report import make_submission_report
from queue_merge.inbox import process_inbox
from queue_merge.merge import make_master
from queue_merge.operator_report import write_operator_report
from calc_obs.calc_obs_run import make_observing_plan
from calc_obs.products import make_observer_products


def finish(summary, status="complete", error=None):
        summary["status"] = status

        if error is not None:
                summary["error"] = error

        write_operator_report(summary)


def main():
        summary = {
                "status": "running",
                "r2": {},
                "submissions": {},
                "inbox": {},
                "master_count": None,
                "plan": None,
                "product_count": None,
        }

        print("[1/5] Syncing Cloudflare R2 submissions...", flush=True)
        r2 = sync_r2_submissions()
        summary["r2"] = r2

        if r2["enabled"]:
                print(
                        f"[1/5] R2 sync complete: "
                        f"{r2['downloaded_files']} target files, "
                        f"{r2['downloaded_metadata']} metadata files",
                        flush=True,
                )

        submissions = make_submission_report()
        summary["submissions"] = submissions
        print(
                f"[1/5] Known submissions: {submissions['submission_count']}",
                flush=True,
        )

        print("[2/5] Processing observer inbox...", flush=True)
        inbox = process_inbox()
        summary["inbox"] = inbox
        print(
                f"[2/5] Inbox complete: "
                f"{inbox['files_found']} files found, "
                f"{inbox['accepted_files']} accepted, "
                f"{inbox['rejected_files']} rejected",
                flush=True,
        )
        print(f"[2/5] Inbox report: {inbox['report_path']}", flush=True)

        print("[3/5] Building master table...", flush=True)
        master = make_master()

        if master is not None:
                summary["master_count"] = len(master)
                print(f"[3/5] Master table complete: {len(master)} targets", flush=True)
        else:
                print("[3/5] Master table failed or no valid targets found", flush=True)
                finish(summary, status="failed", error="Master table failed or no valid targets found")
                return

        print("[4/5] Building observing plan...", flush=True)
        plan = make_observing_plan()

        if plan is not None:
                summary["plan"] = plan
                print(f"[4/5] Observing plan complete: {len(plan)} targets", flush=True)

                if "skyq_category" in plan.columns:
                        print("SkyQ category counts:", flush=True)
                        print(plan["skyq_category"].value_counts().to_string(), flush=True)
        else:
                print("[4/5] Observing plan failed", flush=True)
                finish(summary, status="failed", error="Observing plan failed")
                return

        print("[5/5] Creating observer products...", flush=True)
        products = make_observer_products()
        summary["product_count"] = len(products)
        print(f"[5/5] Observer products complete: {len(products)} targets", flush=True)

        finish(summary)
        print("SkyQ pipeline complete.", flush=True)


if __name__ == "__main__":
        main()
