import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord, AltAz, get_body, get_sun

from calc_obs.airmass import obs_location


def moon_coord(times):
        return get_body("moon", times, obs_location)


def moon_altaz(times):
        frame = AltAz(obstime=times, location=obs_location)
        moon = moon_coord(times)
        return moon.transform_to(frame)


def moon_illumination(times):
        moon = get_body("moon", times)
        sun = get_sun(times)

        elongation = sun.separation(moon).to_value(u.rad)
        illumination = (1.0 - np.cos(elongation)) / 2.0

        return illumination


def moon_target_separation(ra, dec, times):
        frame = AltAz(obstime=times, location=obs_location)

        target = SkyCoord(
                ra=float(ra) * u.deg,
                dec=float(dec) * u.deg,
        ).transform_to(frame)

        moon = moon_coord(times).transform_to(frame)

        return target.separation(moon).to_value(u.deg)


def moon_up_mask(times):
        moon_altitudes = moon_altaz(times).alt
        return moon_altitudes > 0 * u.deg


def moon_up_hours(times):
        mask = moon_up_mask(times)
        dt = (times[1] - times[0]).to_value(u.hour)

        return np.sum(mask) * dt


def moon_summary(ra, dec, times):
        moon_altitudes = moon_altaz(times).alt
        illumination = moon_illumination(times)
        separation = moon_target_separation(ra, dec, times)
        moon_up = moon_altitudes > 0 * u.deg

        if np.any(moon_up):
                min_sep_moon_up = np.min(separation[moon_up])
        else:
                min_sep_moon_up = np.nan

        return {
                "moon_illumination": float(np.mean(illumination)),
                "moon_alt_max": float(np.max(moon_altitudes).to_value(u.deg)),
                "moon_up_hours": float(moon_up_hours(times)),
                "min_moon_sep": float(np.min(separation)),
                "min_moon_sep_moon_up": float(min_sep_moon_up),
        }
