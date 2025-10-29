from __future__ import annotations

import os
import ssl
import urllib.parse
import urllib.request
import json
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib import cm, colors as mcolors
import numpy as np
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from tools import config


@dataclass
class HourPoint:
    time: str
    temperature_c: float
    humidity_pct: float
    precip_pct: float


def _fetch_open_meteo(lat: float, lon: float) -> Dict[str, Any]:
    """
    Fetch up-to-24h hourly forecast (temp, humidity, precip prob) from Open-Meteo.

    No API key required. Docs: https://open-meteo.com/en/docs#hourly=temperature_2m
    """
    params = {
        "latitude": f"{lat:.5f}",
        "longitude": f"{lon:.5f}",
        "hourly": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "precipitation_probability",
            ]
        ),
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
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            obj = typing_cast_dict_any(json.loads(resp.read().decode("utf-8")))
    except Exception:
        return None

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


def _prepare_points(payload: Dict[str, Any]) -> List[HourPoint]:
    hourly = payload.get("hourly") or {}
    times: List[str] = hourly.get("time") or []
    temps: List[float] = hourly.get("temperature_2m") or []
    hums: List[float] = hourly.get("relative_humidity_2m") or []
    precs: List[float] = hourly.get("precipitation_probability") or []

    # Ensure equal lengths; truncate to the shortest and to 24 points.
    n = min(len(times), len(temps), len(hums), len(precs), 24)
    points: List[HourPoint] = []
    for i in range(n):
        points.append(
            HourPoint(
                time=str(times[i]),
                temperature_c=float(temps[i]),
                humidity_pct=float(hums[i]),
                precip_pct=float(precs[i]),
            )
        )
    return points


def _scale_points(
    pts: List[HourPoint],
    width: int,
    height: int,
    pad: Tuple[int, int, int, int],
) -> Dict[str, List[Tuple[float, float]]]:
    """
    Map data to SVG coordinates. Humidity and precip are 0..100.
    Temperature scales to its own min..max across the window.
    """
    left, top, right, bottom = pad
    inner_w = width - left - right
    inner_h = height - top - bottom
    if not pts:
        return {"temp": [], "hum": [], "prec": []}

    xs = [left + (inner_w * i) / max(1, (len(pts) - 1)) for i in range(len(pts))]

    tvals = [p.temperature_c for p in pts]
    t_min = min(tvals)
    t_max = max(tvals)
    # Guard against flat lines
    t_span = (t_max - t_min) or 1.0

    def y_from_pct(pct: float) -> float:
        # 0 at bottom -> top coordinate
        return top + (inner_h * (1.0 - max(0.0, min(100.0, pct)) / 100.0))

    def y_from_temp(t: float) -> float:
        norm = (t - t_min) / t_span
        return top + (inner_h * (1.0 - norm))

    temp_xy = [(xs[i], y_from_temp(p.temperature_c)) for i, p in enumerate(pts)]
    hum_xy = [(xs[i], y_from_pct(p.humidity_pct)) for i, p in enumerate(pts)]
    prec_xy = [(xs[i], y_from_pct(p.precip_pct)) for i, p in enumerate(pts)]
    return {"temp": temp_xy, "hum": hum_xy, "prec": prec_xy}


def _polyline(points: List[Tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def build_daily_svg(path: str | Path) -> Dict[str, Any]:
    """
    Fetch hourly weather (temp C, humidity %, precip %), render three ggplot-like PNG charts
    using matplotlib (one per series), and return metadata for JSON consumers.

    Behavior:
    - Defaults to San Francisco coordinates unless WEATHER_LAT/LON are set.
    - Next (up to) 24 hours of:
        temp (°C, autoscaled),
        humidity (%),
        precipitation probability (%).
    - On failure, writes placeholder PNGs with an error message.
    """
    now = datetime.now(timezone.utc).isoformat()
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)

    lat = config.LAT
    lon = config.LON

    error_msg = None
    points: List[HourPoint] = []

    # Resolve a human-friendly location name for title
    location_name = None
    try:
        location_name = _reverse_geocode_name(lat, lon)
    except Exception:
        location_name = None
    if not location_name:
        location_name = f"{lat:.4f}, {lon:.4f}"

    try:
        payload = _fetch_open_meteo(lat, lon)
        points = _prepare_points(payload)
        if not points:
            error_msg = "No hourly data"
    except Exception as e:  # noqa: BLE001
        error_msg = f"{type(e).__name__}: {e}"

    # Derive output file names (relative to provided base path)
    base_png = base.with_suffix(".png")
    temp_path = base.with_name(base.stem + "_temp.png")
    hum_path = base.with_name(base.stem + "_humidity.png")
    prec_path = base.with_name(base.stem + "_precip.png")

    def _write_error_png(pth: Path, msg: str) -> None:
        # Minimal placeholder using matplotlib PNG backend for consistency
        fig = Figure(figsize=(6.4, 2.0), dpi=600)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(1, 1, 1)
        ax.axis("off")
        ax.text(0.02, 0.80, "Weather unavailable", fontsize=12, fontfamily="monospace")
        ax.text(0.02, 0.62, msg, fontsize=10, fontfamily="monospace", wrap=True)
        ax.text(0.02, 0.06, f"Generated {now}", fontsize=8, fontfamily="monospace")
        fig.savefig(pth, format="png", dpi=600)

    if error_msg:
        # Write placeholders for all expected outputs (PNG)
        for pth in (base_png, temp_path, hum_path, prec_path):
            _write_error_png(pth, error_msg)
        return {
            "title": f"Weather in {location_name}",
            "svg_path": str(base_png),
            "svg_paths": {
                "temperature": str(temp_path),
                "humidity": str(hum_path),
                "precip": str(prec_path),
            },
            "generated_at": now,
            "lat": lat,
            "lon": lon,
            "error": error_msg,
            "items": [],
            "units": {
                "temperature": "C",
                "humidity": "%",
                "precipitation_probability": "%",
            },
            "source": "open-meteo",
        }

    # Prepare arrays
    times = [hp.time for hp in points]
    temps = [hp.temperature_c for hp in points]
    hums = [hp.humidity_pct for hp in points]
    precs = [hp.precip_pct for hp in points]

    def _plot_series_png(
        pth: Path,
        series_times: List[str],
        values: List[float],
        ylabel: str,
        color: str,
        ylim: tuple[float, float] | None = None,
        gradient: bool = False,
    ) -> None:
        fig = Figure(figsize=(6.4, 2.0), dpi=600)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(1, 1, 1)
        # ggplot-like styling without relying on matplotlib.style
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#EBEBEB")
        for spine in ax.spines.values():
            spine.set_color("#CCCCCC")
        ax.grid(True, which="major", axis="both", color="white", linewidth=1)

        # Parse ISO times like "YYYY-MM-DDTHH:MM" (possibly with 'Z')
        dts: List[datetime] = []
        for t in series_times:
            dt = None
            try:
                dt = datetime.fromisoformat(t)
            except Exception:
                if t.endswith("Z"):
                    try:
                        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                    except Exception:
                        dt = None
            if dt is None:
                dt = datetime.now()
            dts.append(dt)

        # Apply y-limits if requested (e.g., for % series)
        if ylim is not None:
            ax.set_ylim(*ylim)

        # Determine baseline for fill (0 for % series, min(values) otherwise)
        base = ylim[0] if ylim is not None else (min(values) if values else 0.0)

        if gradient:
            # Temperature: color by value (blue @<=10 → red @>=26)
            xs = mdates.date2num(dts)
            y = np.asarray(values, dtype=float)
            if y.size == 0:
                return
            # Build colored line segments
            points = np.array([xs, y]).T.reshape(-1, 1, 2)
            segments = np.concatenate([points[:-1], points[1:]], axis=1)
            norm = mcolors.Normalize(vmin=10.0, vmax=26.0)
            cmap = cm.get_cmap("coolwarm")
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
                    [base, base],
                    facecolor=c,
                    alpha=0.2,
                    linewidth=0,
                    zorder=1,
                )

            # Tight x bounds, no LR padding
            ax.set_xlim(mdates.num2date(xs.min()), mdates.num2date(xs.max()))
            ax.set_xmargin(0)
            ax.margins(x=0)

            # Ensure reasonable y-bounds if not given
            ymin = float(np.min(y))
            ymax = float(np.max(y))
            if ymin == ymax:
                ymin -= 0.5
                ymax += 0.5
            # Snap temperature axis to "nice" rounded bounds and limit tick count to <= 6 with integer labels.
            import math
            y0_raw = ymin
            y1_raw = ymax
            pad = 0.1
            y0 = math.floor((y0_raw - pad) * 2) / 2.0
            y1 = math.ceil((y1_raw + pad) * 2) / 2.0
            if y1 <= y0:
                y1 = y0 + 1.0
            # Choose an integer tick step so that there are at most 6 ticks.
            span = y1 - y0
            try:
                import matplotlib.ticker as mticker
                # Candidate integer steps
                candidates = [1, 2, 3, 5, 10]
                chosen = 1
                for step in candidates:
                    # number of ticks if we start from ceil(y0) to floor(y1) with this step
                    lo = math.ceil(y0)
                    hi = math.floor(y1)
                    if hi < lo:
                        hi = lo
                    count = ((hi - lo) // step) + 1
                    if count <= 6:
                        chosen = step
                        break
                # Expand limits to integers to align ticks nicely
                y_lo = math.floor(y0)
                y_hi = math.ceil(y1)
                if y_hi <= y_lo:
                    y_hi = y_lo + chosen
                ax.set_ylim(y_lo, y_hi)
                # Locator: integer multiples with chosen step
                ax.yaxis.set_major_locator(mticker.MultipleLocator(base=float(chosen)))
                # Formatter: integer labels
                ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%d"))
                ax.yaxis.set_minor_locator(mticker.NullLocator())
            except Exception:
                # Fallback if ticker import fails
                ax.set_ylim(math.floor(y0), math.ceil(y1))
        else:
            # Simple colored line + same-color lighter fill
            ax.plot(dts, values, color=color, linewidth=2, zorder=2)
            ax.fill_between(dts, values, base, facecolor=color, alpha=0.2, linewidth=0, zorder=1)
            # Tight x bounds, no LR padding
            ax.set_xlim(min(dts), max(dts))
            ax.set_xmargin(0)
            ax.margins(x=0)

        # Hourly ticks and labels
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H"))

        ax.grid(True, which="major", axis="both")
        fig.autofmt_xdate(rotation=0)
        fig.tight_layout(pad=0.5)
        fig.savefig(pth, format="png", dpi=600)

    # Render three charts (also write the temperature chart to a base PNG path)
    _plot_series_png(temp_path, times, temps, "Temperature (°C)", "#d62728", gradient=True)
    _plot_series_png(hum_path, times, hums, "Humidity (%)", "#000000", ylim=(0, 100))
    _plot_series_png(prec_path, times, precs, "Precipitation chance (%)", "#6baed6", ylim=(0, 100))
    _plot_series_png(base_png, times, temps, "Temperature (°C)", "#d62728", gradient=True)

    items = [
        {
            "time": hp.time,
            "temperature_c": hp.temperature_c,
            "humidity_pct": hp.humidity_pct,
            "precip_pct": hp.precip_pct,
        }
        for hp in points
    ]
    return {
        "title": f"Weather in {location_name}",
        "svg_path": str(base_png),
        "svg_paths": {
            "temperature": str(temp_path),
            "humidity": str(hum_path),
            "precip": str(prec_path),
        },
        "generated_at": now,
        "lat": lat,
        "lon": lon,
        "items": items,
        "units": {"temperature": "C", "humidity": "%", "precipitation_probability": "%"},
        "source": "open-meteo",
    }


def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the weather section.
    """
    from tools import config
    from tools.util import escape_sile

    data = build_daily_svg(config.WEATHER_SVG_PATH)
    title = escape_sile(data["title"])

    # Use build paths for charts
    temp_path = "build/charts/weather_temp.png"
    humidity_path = "build/charts/weather_humidity.png"
    precip_path = "build/charts/weather_precip.png"

    return f"""\\define[command=weathersection]{{
\\vfil
\\vpenalty[penalty=-500]
  \\sectionbox{{
    \\sectiontitle{{{title}}}
    \\font[size=9pt]{{Temperature (°C)}}
    \\cr\\img[src={temp_path}, width=100%lw]
    \\cr\\font[size=9pt]{{Humidity (\\%)}}
    \\cr\\img[src={humidity_path}, width=100%lw]
    \\cr\\font[size=9pt]{{Precipitation chance (\\%)}}
    \\cr\\img[src={precip_path}, width=100%lw]
  }}
}}"""
