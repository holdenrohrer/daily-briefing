from __future__ import annotations

import os
import ssl
import urllib.parse
import urllib.request
import json
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.backends.backend_svg import FigureCanvasSVG
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple


@dataclass
class HourPoint:
    time: str
    temperature_c: float
    humidity_pct: float
    precip_pct: float


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


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
    Fetch hourly weather (temp C, humidity %, precip %), render three ggplot-like SVG charts
    using matplotlib (one per series), and return metadata for JSON consumers.

    Behavior:
    - Defaults to San Francisco coordinates unless WEATHER_LAT/LON are set.
    - Next (up to) 24 hours of:
        temp (°C, autoscaled),
        humidity (%),
        precipitation probability (%).
    - On failure, writes placeholder SVGs with an error message.
    """
    now = datetime.now(timezone.utc).isoformat()
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)

    lat = _env_float("WEATHER_LAT", 37.7749)
    lon = _env_float("WEATHER_LON", -122.4194)

    error_msg = None
    points: List[HourPoint] = []
    try:
        payload = _fetch_open_meteo(lat, lon)
        points = _prepare_points(payload)
        if not points:
            error_msg = "No hourly data"
    except Exception as e:  # noqa: BLE001
        error_msg = f"{type(e).__name__}: {e}"

    # Derive output file names (relative to provided base path)
    temp_path = base.with_name(base.stem + "_temp.svg")
    hum_path = base.with_name(base.stem + "_humidity.svg")
    prec_path = base.with_name(base.stem + "_precip.svg")

    def _write_error_svg(pth: Path, msg: str) -> None:
        # Minimal placeholder using matplotlib SVG backend for consistency
        fig = Figure(figsize=(6.4, 2.2), dpi=100)
        FigureCanvasSVG(fig)
        ax = fig.add_subplot(1, 1, 1)
        ax.axis("off")
        ax.text(0.02, 0.80, "Weather unavailable", fontsize=12, fontfamily="monospace")
        ax.text(0.02, 0.62, msg, fontsize=10, fontfamily="monospace", wrap=True)
        ax.text(0.02, 0.06, f"Generated {now}", fontsize=8, fontfamily="monospace")
        fig.savefig(pth, format="svg")

    if error_msg:
        # Write placeholders for all expected outputs, including the legacy base path
        for pth in (base, temp_path, hum_path, prec_path):
            _write_error_svg(pth, error_msg)
        return {
            "title": "Weather",
            "svg_path": str(base),
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

    def _plot_series_svg(
        pth: Path,
        series_times: List[str],
        values: List[float],
        ylabel: str,
        color: str,
        ylim: tuple[float, float] | None = None,
    ) -> None:
        fig = Figure(figsize=(6.4, 2.2), dpi=100)
        FigureCanvasSVG(fig)
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

        ax.plot(dts, values, color=color, linewidth=2)

        ax.set_xlabel("Time (24h)")
        ax.set_ylabel(ylabel)
        if ylim is not None:
            ax.set_ylim(*ylim)

        # Hourly ticks and labels
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

        ax.grid(True, which="major", axis="both")
        fig.autofmt_xdate(rotation=0)
        fig.tight_layout(pad=0.5)
        fig.savefig(pth, format="svg")

    # Render three charts (also write the temperature chart to the legacy base path)
    _plot_series_svg(temp_path, times, temps, "Temperature (°C)", "#d62728")
    _plot_series_svg(hum_path, times, hums, "Humidity (%)", "#1f77b4", ylim=(0, 100))
    _plot_series_svg(prec_path, times, precs, "Precipitation chance (%)", "#2ca02c", ylim=(0, 100))
    _plot_series_svg(base, times, temps, "Temperature (°C)", "#d62728")

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
        "title": "Weather",
        "svg_path": str(base),
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
