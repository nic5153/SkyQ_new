import sys
from tqdm import tqdm
import pandas as pd

from calc_obs.airmass import time_grid, target_summary
from calc_obs.moon import moon_summary
from calc_obs.season_check import add_season_check


MASTER_PATH = "data/master.csv"
PLAN_PATH = "data/observing_plan.csv"

CATEGORY_ORDER = {
        "Prime": 0,
        "Secondary": 1,
        "Non-Observable": 2,
}


def skyq_category(row):
        if not row["observable"]:
                return "Non-Observable"

        if row["season_category"] == "Non-Observable":
                return "Non-Observable"

        if (
                row["season_category"] == "Prime"
                and row["min_airmass"] <= 1.5
                and row["hours_above_30"] >= 2.0
        ):
                return "Prime"

        return "Secondary"


def make_observing_plan(date=None):
        df = pd.read_csv(MASTER_PATH)
        times = time_grid(date=date)

        summaries = []

        for _, row in tqdm(df.iterrows(), total=len(df), desc="Building observing plan", unit="target", file=sys.stdout):
                ra = row["ra"]
                dec = row["dec"]

                obs_info = target_summary(ra, dec, times)
                moon_info = moon_summary(ra, dec, times)

                summaries.append({
                        **obs_info,
                        **moon_info,
                })

        summary_df = pd.DataFrame(summaries)
        plan = pd.concat([df.reset_index(drop=True), summary_df], axis=1)

        plan = add_season_check(plan, date=date)
        plan["skyq_category"] = plan.apply(skyq_category, axis=1)
        plan["category_order"] = plan["skyq_category"].map(CATEGORY_ORDER)

        plan = plan.sort_values(
                by=[
                        "category_order",
                        "season_score",
                        "hours_above_30",
                        "max_alt",
                        "min_airmass",
                ],
                ascending=[
                        True,
                        False,
                        False,
                        False,
                        True,
                ],
        )

        plan = plan.drop(columns=["category_order"])
        plan.to_csv(PLAN_PATH, index=False)

        return plan


if __name__ == "__main__":
        make_observing_plan()
