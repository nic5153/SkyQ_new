from queue_merge.merge import make_master
from calc_obs.calc_obs_run import make_observing_plan


def main():
        print("[1/2] Building master table...", flush=True)
        master = make_master()

        if master is not None:
                print(f"[1/2] Master table complete: {len(master)} targets", flush=True)
        else:
                print("[1/2] Master table failed or no valid targets found", flush=True)
                return

        print("[2/2] Building observing plan...", flush=True)
        plan = make_observing_plan()

        if plan is not None:
                print(f"[2/2] Observing plan complete: {len(plan)} targets", flush=True)

                if "skyq_category" in plan.columns:
                        print("SkyQ category counts:", flush=True)
                        print(plan["skyq_category"].value_counts().to_string(), flush=True)
        else:
                print("[2/2] Observing plan failed", flush=True)
                return

        print("SkyQ pipeline complete.", flush=True)


if __name__ == "__main__":
        main()
