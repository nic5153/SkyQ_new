import numpy as np
import pandas as pd
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import get_sun


def sun_ra(date=None):
        if date is None:
                time = Time.now()
        else:
                time = Time(date)

        return get_sun(time).ra.to_value(u.deg)


def ra_sep_from_sun(ra, date=None):
        sun = sun_ra(date)
        sep = (ra - sun + 180.0) % 360.0 - 180.0
        return abs(sep)


def season_category(ra, date=None):
        sep = ra_sep_from_sun(ra, date)

        if sep >= 120:
                return "Prime"
        elif sep >= 75:
                return "Secondary"
        else:
                return "Non-Observable"


def season_score(ra, date=None):
        sep = ra_sep_from_sun(ra, date)
        score = (sep - 75.0) / (180.0 - 75.0)
        return np.clip(score, 0.0, 1.0)


def add_season_check(df, date=None):
        df = df.copy()
        df["ra"] = pd.to_numeric(df["ra"], errors="coerce")

        df["sun_ra_sep"] = df["ra"].apply(lambda ra: ra_sep_from_sun(ra, date))
        df["season_score"] = df["ra"].apply(lambda ra: season_score(ra, date))
        df["season_category"] = df["ra"].apply(lambda ra: season_category(ra, date))

        return df
