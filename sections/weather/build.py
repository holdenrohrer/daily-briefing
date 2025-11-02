from __future__ import annotations

import ssl
import urllib.parse
import urllib.request
import json
import math
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib import cm, colors as mcolors
import matplotlib.ticker as mticker
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from tools import config


@dataclass(frozen=True)
class GraphSpec:
    key: str                 # internal key for series dict
    om_key: str              # Open-Meteo 'hourly' field name
    suffix: str              # filename suffix
    label: str               # human label for SILE
    color: str               # hex color for line/fill
    ylim: tuple[float, float] | None = None
    gradient: bool = False
    alpha: float | None = None     # fill alpha; defaults to 0.2 if None
    stroke: str | None = None      # optional stroke color override for the line


# Single-source-of-truth for all graphs we render.
GRAPHS: List[GraphSpec] = [
    GraphSpec("temp", "temperature_2m", "temp", "Temperature (°C)", "#d62728", None, True),
    GraphSpec("hum", "relative_humidity_2m", "humidity", "Humidity (%)", "#000000", (0, 100), False),
    GraphSpec("precip", "precipitation_probability", "precip", "Precipitation chance (%)", "#6baed6", (0, 100), False),
    GraphSpec("wind", "wind_speed_10m", "wind", "Wind (10m) (km/h)", "#2ca02c", None, False),
    GraphSpec("clouds", "cloud_cover", "clouds", "Cloud cover (%)", "#f2f2f2", (0, 100), False, alpha=0.8, stroke="#bfbfbf"),
    GraphSpec("pressure", "surface_pressure", "pressure", "Surface pressure (hPa)", "#8c564b", None, False, alpha=0.3),
]


def _fetch_open_meteo(lat: float, lon: float) -> Dict[str, Any]:
    """
    Fetch up-to-24h hourly forecast from Open-Meteo.

    Includes: temperature_2m (°C), relative_humidity_2m (%), precipitation_probability (%),
    wind_speed_10m (km/h), cloud_cover (%), surface_pressure (hPa).
    No API key required. Docs: https://open-meteo.com/en/docs
    """
    params = {
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "hourly": ",".join(list(dict.fromkeys(gs.om_key for gs in GRAPHS))),
        "windspeed_unit": "kmh",
        "forecast_days": "1",
        "timezone": "auto",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)

    # Open-Meteo requires a sensible UA; also be robust to environments with strict SSL.
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "holden-report/0.1 (+https://example.invalid)",
            "Accept": "application/json",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return typing_cast_dict_any(json.loads(resp.read().decode("utf-8")))


def _reverse_geocode_name(lat: float, lon: float) -> str | None:
    """
    Reverse geocode lat/lon to a human-readable place name.

    Recommended APIs (choose one; first is free, no key required):
    - Nominatim / OpenStreetMap reverse geocoding (free; requires a descriptive User-Agent and rate limiting):
      https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}
      Returns fields like 'name', 'display_name', and 'address' with 'city/town/village',
      'state', and 'country_code'.
    - Google Maps Geocoding API (paid, API key): https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lon}&key=KEY
    - Mapbox Geocoding API (paid, token): https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json?access_token=TOKEN

    We implement Nominatim here to avoid requiring an API key.
    Be a good citizen: set a proper User-Agent and keep request rate low.
    """
    url = (
        "https://nominatim.openstreetmap.org/reverse?"
        + urllib.parse.urlencode(
            {
                "format": "jsonv2",
                "lat": f"{lat:.5f}",
                "lon": f"{lon:.5f}",
                "accept-language": "en",
            }
        )
    )
    req = urllib.request.Request(
        url,
        headers={
            # Per Nominatim policy include a real UA with contact URL/email if possible.
            "User-Agent": "holden-report/0.1 (+https://example.invalid/contact)",
            "Accept": "application/json",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        obj = typing_cast_dict_any(json.loads(resp.read().decode("utf-8")))

    addr = typing_cast_dict_any(obj.get("address") or {})
    # Prefer city/town/village/hamlet; fall back to municipality or county
    locality = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("hamlet")
        or addr.get("municipality")
        or addr.get("county")
        or ""
    ).strip()
    state = (addr.get("state") or "").strip()
    country_code = (addr.get("country_code") or "").strip().upper()

    # Map US state names to postal abbreviations for brevity
    us_state_abbrev = {
        "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
        "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA",
        "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
        "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
        "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
        "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
        "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
        "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
        "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
        "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
        "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
    }
    region = None
    if country_code == "US" and state:
        region = us_state_abbrev.get(state, state)
    else:
        region = country_code or state

    if locality and region:
        return f"{locality}, {region}"
    return locality or region


def typing_cast_dict_any(x: Any) -> Dict[str, Any]:
    return x  # narrow type for mypy/linters without importing typing.cast


def _extract_series(payload: Dict[str, Any]) -> Tuple[List[str], Dict[str, List[float]]]:
    """
    Extract and normalize the hourly arrays we care about into a dict keyed by GraphSpec.key.
    Truncates all series (including time) to the shortest length and limits to 24 points.
    Raises AssertionError if no data points are available.
    """
    hourly = payload.get("hourly") or {}
    times: List[str] = hourly.get("time") or []

    series: Dict[str, List[float]] = {}
    for gs in GRAPHS:
        arr = hourly.get(gs.om_key) or []
        series[gs.key] = arr

    # Ensure equal lengths; truncate to the shortest and to 24 points.
    lengths = [len(times)] + [len(v) for v in series.values()]
    n = min(lengths) if lengths else 0
    n = min(n, 24)
    assert n > 0, "Open-Meteo payload did not contain hourly points"

    times_out = [str(times[i]) for i in range(n)]
    series_out: Dict[str, List[float]] = {
        k: [float(series[k][i]) for i in range(n)] for k in series
    }
    return times_out, series_out


def build_daily_svg(path: str | Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Render PNG charts for the next ~24 hours of the series declared in GRAPHS.

    Requirements:
    - payload must be an Open-Meteo response containing the above hourly series.
    - Raises AssertionError if the payload has no hourly data.
    """
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)

    lat = config.LAT
    lon = config.LON

    # Resolve a human-friendly location name for title
    location_name = _reverse_geocode_name(lat, lon)
    if not location_name:
        location_name = f"{lat:.4f}, {lon:.4f}"

    # Extract normalized series
    times, series = _extract_series(payload)

    def _plot_series_png(
        pth: Path,
        series_times: List[str],
        values: List[float],
        ylabel: str,
        color: str,
        ylim: tuple[float, float] | None = None,
        gradient: bool = False,
        fill_alpha: float = 0.2,
        stroke_color: str | None = None,
    ) -> None:
        fig = Figure(figsize=(6.4, 2.0), dpi=600)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(1, 1, 1)
        # ggplot-like styling without relying on matplotlib.style
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        for spine in ax.spines.values():
            spine.set_color("#CCCCCC")
        ax.grid(True, which="major", axis="both", color="#AAAAAA", linewidth=0.5, zorder=1)

        # Parse ISO times like "YYYY-MM-DDTHH:MM" (possibly with 'Z')
        dts: List[datetime] = []
        for t in series_times:
            t_iso = t.replace("Z", "+00:00") if t.endswith("Z") else t
            dt = datetime.fromisoformat(t_iso)
            dts.append(dt)

        # Normalize arrays
        xs = mdates.date2num(dts)
        y = np.asarray(values, dtype=float)
        if y.size == 0:
            return

        # Determine y-axis limits
        if ylim is not None:
            y_lo, y_hi = float(ylim[0]), float(ylim[1])
        else:
            ymin = float(np.min(y))
            ymax = float(np.max(y))
            if ymin == ymax:
                ymin -= 0.5
                ymax += 0.5
            pad = 0.1
            y0 = math.floor((ymin - pad) * 2) / 2.0
            y1 = math.ceil((ymax + pad) * 2) / 2.0
            y_lo = math.floor(y0)
            y_hi = math.ceil(y1)
            if y_hi <= y_lo:
                y_hi = y_lo + 1.0

        # Choose an integer tick step so that there are at most 6 ticks.
        lo_int = math.ceil(y_lo)
        hi_int = math.floor(y_hi)
        if hi_int < lo_int:
            hi_int = lo_int
        candidates = [1, 2, 3, 5, 10, 20]
        chosen = 1
        for step in candidates:
            count = ((hi_int - lo_int) // step) + 1
            if count <= 6:
                chosen = step
                break

        # Apply axis settings
        ax.set_ylim(y_lo, y_hi)
        ax.yaxis.set_major_locator(mticker.MultipleLocator(base=float(chosen)))
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%d"))
        ax.yaxis.set_minor_locator(mticker.NullLocator())

        base_val = y_lo if ylim is None else float(ylim[0])

        if gradient:
            # Colored line segments by value (blue @<=10 → red @>=26)
            norm = mcolors.Normalize(vmin=10.0, vmax=26.0)
            cmap = cm.get_cmap("coolwarm")
            pts = np.array([xs, y]).T.reshape(-1, 1, 2)
            segments = np.concatenate([pts[:-1], pts[1:]], axis=1)
            lc = LineCollection(segments, cmap=cmap, norm=norm, linewidth=2, zorder=2)
            mids = (y[:-1] + y[1:]) / 2.0
            lc.set_array(mids)
            ax.add_collection(lc)

            # Gradient under-fill: per-segment fill with lighter color
            for i in range(len(xs) - 1):
                midval = (y[i] + y[i + 1]) / 2.0
                c = cmap(norm(midval))
                ax.fill_between(
                    [mdates.num2date(xs[i]), mdates.num2date(xs[i + 1])],
                    [y[i], y[i + 1]],
                    [base_val, base_val],
                    facecolor=c,
                    alpha=fill_alpha,
                    linewidth=0,
                    zorder=1,
                )
        else:
            # Simple colored line + same-color lighter fill
            ax.plot(dts, values, color=(stroke_color or color), linewidth=2, zorder=2)
            ax.fill_between(dts, values, base_val, facecolor=color, alpha=fill_alpha, linewidth=0, zorder=1)

        # Tight x bounds, no LR padding
        ax.set_xlim(mdates.num2date(xs.min()), mdates.num2date(xs.max()))
        ax.set_xmargin(0)
        ax.margins(x=0)

        # Hourly ticks and labels
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))

        fig.autofmt_xdate(rotation=0)
        fig.tight_layout(pad=0.5)
        fig.savefig(pth, format="png", dpi=600)

    # Render charts declared in GRAPHS
    for gs in GRAPHS:
        out_path = base.with_name(base.stem + f"_{gs.suffix}.png")
        _plot_series_png(
            out_path,
            times,
            series[gs.key],
            gs.label,
            gs.color,
            ylim=gs.ylim,
            gradient=gs.gradient,
            fill_alpha=(gs.alpha if gs.alpha is not None else 0.2),
            stroke_color=gs.stroke,
        )

    return {
        "title": f"Weather in {location_name}",
    }



def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the weather section.

    If the Open-Meteo request fails, returns a section with the message
    "Error: openmeteo is down".
    """
    from tools import config
    from tools.util import escape_sile

    # Single failure guard: only treat Open-Meteo fetch failures specially.
    try:
        payload = _fetch_open_meteo(config.LAT, config.LON)
    except Exception:
        msg = escape_sile("Error: openmeteo is down")
        return f"""\\define[command=weathersection]{{
\\vfil
\\vpenalty[penalty=-500]
  \\sectionbox{{
    \\sectiontitle{{Weather}}
    \\font[size=9pt]{{{msg}}}
  }}
}}"""

    data = build_daily_svg(config.WEATHER_SVG_PATH, payload)
    title = escape_sile(data["title"])

    # Compose SILE body from GRAPHS to keep single-source-of-truth
    body_lines: List[str] = []
    for gs in GRAPHS:
        label = escape_sile(gs.label)
        image_path = f"build/charts/weather_{gs.suffix}.png"
        body_lines.append(f"    \\cr\\font[size=9pt]{{{label}}}\n    \\cr\\img[src={image_path}, width=100%lw]")
    body = "\n".join(body_lines)

    return f"""\\define[command=weathersection]{{
\\vfil
\\vpenalty[penalty=-500]
  \\sectionbox{{
    \\sectiontitle{{{title}}}
{body}
  }}
}}"""
