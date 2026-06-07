import numpy as np
import pandas as pd
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import SkyCoord, EarthLocation, AltAz

obs_location = EarthLocation(
        lat=33.68897 * u.deg,
        lon=-101.99823 * u.deg,
        height=1004 * u.m
)


def time_grid(date=None, hours_before=6, hours_after=6, n_points=200):
        if date is None:
                center = Time.now()
                center = Time(center.strftime("%Y-%m-%d 05:00:00"))
        else:
                center = Time(f"{date} 05:00:00")

        delta_hour = np.linspace(-hours_before, hours_after, n_points) * u.hour
        return center + delta_hour


def alt_target(ra, dec, times):
        target = SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg)
        frame = AltAz(obstime=times, location=obs_location)
        altaz = target.transform_to(frame)
        return altaz.alt


def airmass_from_alt(altitudes):
        alt_deg = altitudes.to_value(u.deg)
        zenith_deg = 90.0 - alt_deg

        airmass = np.full_like(alt_deg, np.nan, dtype=float)
        mask = alt_deg > 0.0

        z = zenith_deg[mask]

        airmass[mask] = 1.0 / (
                np.cos(np.deg2rad(z))
                + 0.50572 * (96.07995 - z) ** -1.6364
        )

        return airmass


def airmass_target(ra, dec, times):
        altitudes = alt_target(ra, dec, times)
        return airmass_from_alt(altitudes)


def max_alt(altitudes):
        return np.max(altitudes).to_value(u.deg)


def min_airmass(airmass):
        finite = np.isfinite(airmass)

        if not np.any(finite):
                return np.nan

        return np.min(airmass[finite])


def hours_above_alt(altitudes, times, min_alt=30):
        mask = altitudes > min_alt * u.deg
        dt = (times[1] - times[0]).to_value(u.hour)
        return np.sum(mask) * dt


def observable(altitudes, min_alt=30):
        return np.any(altitudes > min_alt * u.deg)


def best_observe_time(times, airmass, altitudes=None, min_alt=30):
        finite = np.isfinite(airmass)

        if altitudes is not None:
                finite = finite & (altitudes > min_alt * u.deg)

        if not np.any(finite):
                return None

        valid_indices = np.where(finite)[0]
        best_index = valid_indices[np.nanargmin(airmass[finite])]

        return times[best_index].isot

def observing_window(times, altitudes, min_alt=30):
        mask = altitudes > min_alt * u.deg

        if not np.any(mask):
                return None, None

        start = times[np.where(mask)[0][0]].isot
        end = times[np.where(mask)[0][-1]].isot

        return start, end


def curve_table(ra, dec, times):
        altitudes = alt_target(ra, dec, times)
        airmass = airmass_from_alt(altitudes)

        return pd.DataFrame({
                "time_utc": [time.isot for time in times],
                "altitude_deg": altitudes.to_value(u.deg),
                "airmass": airmass
        })


def target_summary(ra, dec, times, min_alt=30):
        altitudes = alt_target(ra, dec, times)
        airmass = airmass_from_alt(altitudes)

        window_start, window_end = observing_window(times, altitudes, min_alt=min_alt)

        return {
                "max_alt": max_alt(altitudes),
                "min_airmass": min_airmass(airmass),
                "hours_above_30": hours_above_alt(altitudes, times, min_alt=min_alt),
                "observable": observable(altitudes, min_alt=min_alt),
                "window_start": window_start,
                "window_end": window_end,
		"best_time": best_observe_time(times, airmass, altitudes=altitudes, min_alt=min_alt),"best_time": best_observe_time(times, airmass, altitudes=altitudes, min_alt=min_alt),
        }
