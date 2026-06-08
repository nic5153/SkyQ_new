import os
import re
import sys
from html import escape
from pathlib import Path
from urllib.parse import urlencode

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import astropy.units as u
from astropy.coordinates import AltAz, SkyCoord
from astropy.time import Time
from matplotlib.dates import DateFormatter
from matplotlib import font_manager
from tqdm import tqdm

from calc_obs.airmass import airmass_from_alt, obs_location, time_grid
from calc_obs.moon import moon_altaz


PLAN_PATH = Path("data") / "observing_plan.csv"
PRODUCT_DIR = Path("data") / "products" / "latest"

CATEGORY_ORDER = {
        "Prime": 0,
        "Secondary": 1,
        "Non-Observable": 2,
}

DARK_BG = "#05070d"
PANEL_BG = "#0b1020"
TEXT_COLOR = "#f4f7fb"
MUTED_TEXT = "#a8b3cf"
GRID_COLOR = "#374151"
PLOT_BLUE = "#56b4e9"
PLOT_GREEN = "#009e73"
PLOT_ORANGE = "#e69f00"
PLOT_YELLOW = "#f0e442"
PLOT_PURPLE = "#cc79a7"
PLOT_VERMILLION = "#d55e00"


def safe_name(name):
        name = str(name).strip()
        name = re.sub(r"[^A-Za-z0-9_.+-]+", "_", name)
        return name[:120] or "target"


def plot_font_family():
        available = {font.name for font in font_manager.fontManager.ttflist}

        if "Times New Roman" in available:
                return "Times New Roman"

        return "DejaVu Serif"


PLOT_FONT = plot_font_family()
plt.rcParams["font.family"] = PLOT_FONT


def finite_text(value, digits=2):
        if pd.isna(value):
                return "n/a"

        return f"{float(value):.{digits}f}"


def target_altaz(ra, dec, times):
        target = SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg)
        frame = AltAz(obstime=times, location=obs_location)
        return target.transform_to(frame)


def simbad_url(ra, dec, radius_arcmin=2):
        query = urlencode({
                "Coord": f"{float(ra):.7f} {float(dec):.7f}",
                "CooFrame": "ICRS",
                "Radius": radius_arcmin,
                "Radius.unit": "arcmin",
        })
        return f"https://simbad.cds.unistra.fr/simbad/sim-coo?{query}"


def sdss_navigate_url(ra, dec):
        query = urlencode({
                "ra": f"{float(ra):.7f}",
                "dec": f"{float(dec):.7f}",
        })
        return f"https://skyserver.sdss.org/dr18/VisualTools/navi?{query}"


def sdss_finding_chart_url(ra, dec, scale=0.4, width=512, height=512):
        query = urlencode({
                "ra": f"{float(ra):.7f}",
                "dec": f"{float(dec):.7f}",
                "scale": scale,
                "width": width,
                "height": height,
                "opt": "GL",
        })
        return f"https://skyserver.sdss.org/dr18/SkyServerWS/ImgCutout/getjpeg?{query}"


def relative_link(from_dir, target_path):
        return Path(os.path.relpath(target_path, start=from_dir)).as_posix()


def product_link(path):
        return Path(path).as_posix()


def html_anchor(href, label):
        return f'<a href="{escape(str(href), quote=True)}">{escape(str(label), quote=True)}</a>'


def write_target_page(row, page_path, alt_path, sky_path, simbad_link, sdss_link, sdss_chart_link):
        page_path.parent.mkdir(parents=True, exist_ok=True)
        alt_src = relative_link(page_path.parent, alt_path)
        sky_src = relative_link(page_path.parent, sky_path)

        html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SkyQ - {escape(str(row['name']))}</title>
  <style>
    body {{
      margin: 0;
      font-family: "Times New Roman", Times, serif;
      color: #f4f7fb;
      background: #05070d;
    }}
    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px;
    }}
    header {{
      margin-bottom: 22px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 38px;
      font-weight: 700;
      color: #56b4e9;
    }}
    .meta {{
      color: #a8b3cf;
      font-size: 18px;
      line-height: 1.5;
    }}
    .links {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin: 22px 0;
    }}
    .links a {{
      color: #f4f7fb;
      background: #0b1020;
      border: 1px solid #56b4e9;
      border-radius: 6px;
      padding: 10px 13px;
      text-decoration: none;
      box-shadow: 0 0 14px rgba(86, 180, 233, 0.24);
      font-size: 17px;
    }}
    .links a:hover {{
      color: #05070d;
      background: #56b4e9;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(520px, 1fr));
      gap: 22px;
    }}
    section {{
      background: #0b1020;
      border: 1px solid #26324a;
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 0 24px rgba(86, 180, 233, 0.1);
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 24px;
      color: #f0e442;
    }}
    img {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .finding-chart img {{
      filter: invert(1) hue-rotate(180deg) contrast(1.18) brightness(1.05);
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{escape(str(row['name']))}</h1>
      <div class="meta">
        Category: {escape(str(row['skyq_category']))}<br>
        RA: {float(row['ra']):.7f} deg, Dec: {float(row['dec']):.7f} deg<br>
        Window: {escape(str(row.get('window_start', '')))} to {escape(str(row.get('window_end', '')))}<br>
        Best time: {escape(str(row.get('best_time', '')))}
      </div>
    </header>
    <nav class="links">
      <a href="{escape(simbad_link)}">SIMBAD coordinate query</a>
      <a href="{escape(sdss_link)}">SDSS Navigate</a>
      <a href="{escape(sdss_chart_link)}">SDSS finding chart JPEG</a>
    </nav>
    <div class="grid">
      <section>
        <h2>Altitude and Airmass</h2>
        <img src="{escape(alt_src)}" alt="Altitude and airmass plot">
      </section>
      <section>
        <h2>Sky Path</h2>
        <img src="{escape(sky_src)}" alt="Sky path plot">
      </section>
      <section class="finding-chart">
        <h2>SDSS Finding Chart</h2>
        <img src="{escape(sdss_chart_link)}" alt="SDSS finding chart">
      </section>
    </div>
  </main>
</body>
</html>
"""
        page_path.write_text(html, encoding="utf-8")


def plot_altitude_airmass(row, times, out_path, min_alt=30):
        altaz = target_altaz(row["ra"], row["dec"], times)
        altitudes = altaz.alt
        airmass = airmass_from_alt(altitudes)
        moon_alt = moon_altaz(times).alt.to_value(u.deg)

        x = [time.datetime for time in times]
        alt_deg = altitudes.to_value(u.deg)

        fig, ax_alt = plt.subplots(figsize=(13, 7.5), facecolor=DARK_BG)
        ax_alt.set_facecolor(PANEL_BG)

        ax_alt.plot(x, alt_deg, color=PLOT_BLUE, linewidth=2.8, label="Target altitude")
        ax_alt.plot(x, moon_alt, color=PLOT_PURPLE, linestyle="--", linewidth=2.0, label="Moon altitude")
        ax_alt.axhline(min_alt, color=PLOT_VERMILLION, linestyle=":", linewidth=2.0, label=f"{min_alt} deg limit")
        ax_alt.fill_between(x, min_alt, alt_deg, where=alt_deg >= min_alt, color=PLOT_YELLOW, alpha=0.18)

        ax_alt.set_ylabel("Altitude (deg)")
        ax_alt.set_ylim(-10, 95)
        ax_alt.grid(True, color=GRID_COLOR, alpha=0.55)
        ax_alt.tick_params(colors=TEXT_COLOR, labelsize=12)
        ax_alt.yaxis.label.set_color(TEXT_COLOR)
        ax_alt.xaxis.label.set_color(TEXT_COLOR)

        ax_air = ax_alt.twinx()
        ax_air.set_facecolor(PANEL_BG)
        finite = np.isfinite(airmass)

        if np.any(finite):
                ax_air.plot(
                        np.array(x)[finite],
                        airmass[finite],
                        color=PLOT_ORANGE,
                        linewidth=2.5,
                        label="Airmass",
                )

        ax_air.set_ylabel("Airmass")
        ax_air.set_ylim(3.0, 1.0)
        ax_air.tick_params(colors=TEXT_COLOR, labelsize=12)
        ax_air.yaxis.label.set_color(TEXT_COLOR)

        title = f"{row['name']} - {row['skyq_category']}"
        subtitle = (
                f"min airmass={finite_text(row.get('min_airmass'))} | "
                f"hours above {min_alt} deg={finite_text(row.get('hours_above_30'))} | "
                f"moon sep={finite_text(row.get('min_moon_sep_moon_up'), digits=1)} deg"
        )
        ax_alt.set_title(f"{title}\n{subtitle}")
        ax_alt.title.set_color(TEXT_COLOR)
        ax_alt.title.set_fontfamily(PLOT_FONT)
        ax_alt.title.set_fontsize(18)

        ax_alt.xaxis.set_major_formatter(DateFormatter("%H:%M"))
        ax_alt.set_xlabel("UTC time")

        handles1, labels1 = ax_alt.get_legend_handles_labels()
        handles2, labels2 = ax_air.get_legend_handles_labels()
        legend = ax_alt.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
        legend.get_frame().set_facecolor(PANEL_BG)
        legend.get_frame().set_edgecolor(PLOT_BLUE)

        for text in legend.get_texts():
                text.set_color(TEXT_COLOR)
                text.set_fontfamily(PLOT_FONT)

        for axis in [ax_alt, ax_air]:
                for spine in axis.spines.values():
                        spine.set_color(MUTED_TEXT)

        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        plt.close(fig)


def plot_sky_path(row, times, out_path, min_alt=30):
        altaz = target_altaz(row["ra"], row["dec"], times)
        moon = moon_altaz(times)

        alt_deg = altaz.alt.to_value(u.deg)
        az_deg = altaz.az.to_value(u.deg)
        moon_alt_deg = moon.alt.to_value(u.deg)
        moon_az_deg = moon.az.to_value(u.deg)

        target_up = alt_deg > 0
        target_valid = alt_deg >= min_alt
        moon_up = moon_alt_deg > 0

        fig = plt.figure(figsize=(9, 9), facecolor=DARK_BG)
        ax = fig.add_subplot(111, projection="polar")
        ax.set_facecolor(PANEL_BG)

        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_ylim(90, 0)
        ax.set_yticks([0, 30, 60, 90])
        ax.set_yticklabels(["90", "60", "30", "0"])
        ax.set_title(f"{row['name']} sky path - {row['skyq_category']}")
        ax.title.set_color(TEXT_COLOR)
        ax.title.set_fontfamily(PLOT_FONT)
        ax.title.set_fontsize(20)
        ax.tick_params(colors=TEXT_COLOR, labelsize=12)
        ax.grid(True, color=GRID_COLOR, alpha=0.6)
        ax.spines["polar"].set_color(MUTED_TEXT)

        theta = np.deg2rad(az_deg)
        radius = 90.0 - alt_deg

        if np.any(target_up):
                ax.plot(theta[target_up], radius[target_up], color=PLOT_BLUE, linewidth=2.5, label="Target path")

        if np.any(target_valid):
                ax.plot(theta[target_valid], radius[target_valid], color=PLOT_YELLOW, linewidth=3.6, label="Observable path")

        if np.any(moon_up):
                moon_theta = np.deg2rad(moon_az_deg)
                moon_radius = 90.0 - moon_alt_deg
                ax.plot(moon_theta[moon_up], moon_radius[moon_up], color=PLOT_PURPLE, linestyle="--", linewidth=2.0, label="Moon path")

        horizon = np.linspace(0, 2 * np.pi, 361)
        ax.plot(horizon, np.full_like(horizon, 90), color=MUTED_TEXT, linewidth=1.0)
        ax.plot(horizon, np.full_like(horizon, 90 - min_alt), color=PLOT_VERMILLION, linestyle=":", linewidth=1.5)

        best_time = row.get("best_time")

        if pd.notna(best_time) and str(best_time).strip():
                best = Time(best_time)
                best_index = np.argmin(np.abs(times.jd - best.jd))
                ax.scatter(
                        theta[best_index],
                        radius[best_index],
                        marker="*",
                        s=170,
                        color=PLOT_ORANGE,
                        edgecolor=TEXT_COLOR,
                        linewidth=0.5,
                        label="Best time",
                        zorder=5,
                )

        legend = ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.14), ncol=2)
        legend.get_frame().set_facecolor(PANEL_BG)
        legend.get_frame().set_edgecolor(PLOT_BLUE)

        for text in legend.get_texts():
                text.set_color(TEXT_COLOR)
                text.set_fontfamily(PLOT_FONT)

        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        plt.close(fig)


def configured_max_targets(max_targets):
        if max_targets is not None:
                return max_targets

        value = os.environ.get("SKYQ_PRODUCT_MAX_TARGETS")

        if value is None or value == "":
                return None

        return int(value)


def make_observer_products(
        plan_path=PLAN_PATH,
        product_dir=PRODUCT_DIR,
        date=None,
        categories=("Prime", "Secondary", "Non-Observable"),
        max_targets=None,
        min_alt=30,
):
        plan = pd.read_csv(plan_path)
        times = time_grid(date=date)
        max_targets = configured_max_targets(max_targets)

        product_dir = Path(product_dir)
        altitude_dir = product_dir / "altitude_airmass"
        sky_dir = product_dir / "sky_path"
        page_dir = product_dir / "pages"

        altitude_dir.mkdir(parents=True, exist_ok=True)
        sky_dir.mkdir(parents=True, exist_ok=True)
        page_dir.mkdir(parents=True, exist_ok=True)

        targets = plan[plan["skyq_category"].isin(categories)].copy()
        targets["category_order"] = targets["skyq_category"].map(CATEGORY_ORDER)
        targets = targets.sort_values(
                by=["category_order", "hours_above_30", "max_alt", "min_airmass"],
                ascending=[True, False, False, True],
        )

        if max_targets is not None:
                targets = targets.head(max_targets)

        for column in [
                "product_page_html",
                "altitude_airmass_plot",
                "sky_path_plot",
                "simbad_url",
                "sdss_navigate_url",
                "sdss_finding_chart_url",
                "product_page_link_html",
                "altitude_airmass_plot_link_html",
                "sky_path_plot_link_html",
                "simbad_link_html",
                "sdss_navigate_link_html",
                "sdss_finding_chart_link_html",
        ]:
                plan[column] = ""

        manifest_rows = []

        for index, row in tqdm(
                targets.iterrows(),
                total=len(targets),
                desc="Creating observer products",
                unit="target",
                file=sys.stdout,
        ):
                product_id = f"{safe_name(row['name'])}_{int(index):04d}"
                alt_path = altitude_dir / f"{product_id}_altitude_airmass.png"
                sky_path = sky_dir / f"{product_id}_sky_path.png"
                page_path = page_dir / f"{product_id}.html"
                simbad_link = simbad_url(row["ra"], row["dec"])
                sdss_link = sdss_navigate_url(row["ra"], row["dec"])
                sdss_chart_link = sdss_finding_chart_url(row["ra"], row["dec"])

                plot_altitude_airmass(row, times, alt_path, min_alt=min_alt)
                plot_sky_path(row, times, sky_path, min_alt=min_alt)
                write_target_page(
                        row,
                        page_path,
                        alt_path,
                        sky_path,
                        simbad_link,
                        sdss_link,
                        sdss_chart_link,
                )

                page_href = product_link(page_path)
                altitude_href = product_link(alt_path)
                sky_href = product_link(sky_path)

                plan.loc[index, "product_page_html"] = page_href
                plan.loc[index, "altitude_airmass_plot"] = altitude_href
                plan.loc[index, "sky_path_plot"] = sky_href
                plan.loc[index, "simbad_url"] = simbad_link
                plan.loc[index, "sdss_navigate_url"] = sdss_link
                plan.loc[index, "sdss_finding_chart_url"] = sdss_chart_link
                plan.loc[index, "product_page_link_html"] = html_anchor(page_href, "Open observing page")
                plan.loc[index, "altitude_airmass_plot_link_html"] = html_anchor(altitude_href, "Altitude/airmass plot")
                plan.loc[index, "sky_path_plot_link_html"] = html_anchor(sky_href, "Sky-path plot")
                plan.loc[index, "simbad_link_html"] = html_anchor(simbad_link, "SIMBAD")
                plan.loc[index, "sdss_navigate_link_html"] = html_anchor(sdss_link, "SDSS Navigate")
                plan.loc[index, "sdss_finding_chart_link_html"] = html_anchor(sdss_chart_link, "SDSS finding chart")

                manifest_rows.append({
                        "name": row["name"],
                        "ra": row["ra"],
                        "dec": row["dec"],
                        "skyq_category": row["skyq_category"],
                        "window_start": row.get("window_start"),
                        "window_end": row.get("window_end"),
                        "best_time": row.get("best_time"),
                        "min_airmass": row.get("min_airmass"),
                        "hours_above_30": row.get("hours_above_30"),
                        "product_page_html": page_href,
                        "altitude_airmass_plot": altitude_href,
                        "sky_path_plot": sky_href,
                        "simbad_url": simbad_link,
                        "sdss_navigate_url": sdss_link,
                        "sdss_finding_chart_url": sdss_chart_link,
                        "product_page_link_html": html_anchor(page_href, "Open observing page"),
                        "altitude_airmass_plot_link_html": html_anchor(altitude_href, "Altitude/airmass plot"),
                        "sky_path_plot_link_html": html_anchor(sky_href, "Sky-path plot"),
                        "simbad_link_html": html_anchor(simbad_link, "SIMBAD"),
                        "sdss_navigate_link_html": html_anchor(sdss_link, "SDSS Navigate"),
                        "sdss_finding_chart_link_html": html_anchor(sdss_chart_link, "SDSS finding chart"),
                })

        manifest = pd.DataFrame(manifest_rows)
        manifest_path = product_dir / "manifest.csv"
        enriched_plan_path = product_dir / "observing_plan_with_products.csv"

        manifest.to_csv(manifest_path, index=False)
        plan.to_csv(plan_path, index=False)
        plan.to_csv(enriched_plan_path, index=False)

        print(f"[products] Wrote {len(manifest)} observer product rows", flush=True)
        print(f"[products] Manifest: {manifest_path}", flush=True)
        print(f"[products] Updated observing plan: {plan_path}", flush=True)
        print(f"[products] Enriched observing plan: {enriched_plan_path}", flush=True)

        return manifest


if __name__ == "__main__":
        make_observer_products()
