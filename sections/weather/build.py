from __future__ import annotations

import os
import ssl
import urllib.parse
import urllib.request
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
        return typing_cast_dict_any(__import__("json").loads(resp.read().decode("utf-8")))


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
    Fetch hourly weather (temp C, humidity %, precip %), render a compact SVG line chart,
    and return metadata for JSON consumers.

    MVP behavior:
    - Defaults to San Francisco coordinates unless WEATHER_LAT/LON are set.
    - Draws next (up to) 24 hours as three lines:
        red = temperature (°C, autoscaled),
        blue = humidity (%),
        green = precipitation probability (%).
    - On failure, writes a placeholder SVG with the error message.
    """
    now = datetime.now(timezone.utc).isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    lat = _env_float("WEATHER_LAT", 37.7749)
    lon = _env_float("WEATHER_LON", -122.4194)

    width, height = 640, 220
    pad = (40, 24, 12, 32)  # left, top, right, bottom

    error_msg = None
    points: List[HourPoint] = []
    try:
        payload = _fetch_open_meteo(lat, lon)
        points = _prepare_points(payload)
        if not points:
            error_msg = "No hourly data"
    except Exception as e:  # noqa: BLE001
        error_msg = f"{type(e).__name__}: {e}"

    if error_msg:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="white" stroke="black" stroke-width="1"/>
  <text x="16" y="40" font-family="JetBrains Mono, monospace" font-size="14" fill="black">Weather unavailable</text>
  <text x="16" y="62" font-family="JetBrains Mono, monospace" font-size="12" fill="black">{error_msg}</text>
  <text x="16" y="{height-12}" font-family="JetBrains Mono, monospace" font-size="10" fill="black">Generated {now}</text>
</svg>
"""
        p.write_text(svg, encoding="utf-8")
        return {
            "title": "Weather",
            "svg_path": str(p),
            "generated_at": now,
            "lat": lat,
            "lon": lon,
            "error": error_msg,
            "items": [],
        }

    coords = _scale_points(points, width, height, pad)
    # Axis and grid (simple)
    left, top, right, bottom = pad
    inner_w = width - left - right
    inner_h = height - top - bottom
    x0 = left
    y0 = top + inner_h

    # Build hour tick labels at 0, 6, 12, 18, 23
    tick_indices = [0, 6, 12, 18, len(points) - 1]
    tick_labels = []
    for i in sorted(set(max(0, min(len(points) - 1, t)) for t in tick_indices)):
        t = points[i].time
        # Show "HH:MM" from ISO "YYYY-MM-DDTHH:MM"
        label = (t.split("T", 1)[1] if "T" in t else t)[0:5]
        x = left + inner_w * (i / max(1, (len(points) - 1)))
        tick_labels.append((x, label))

    temp_min = min(p.temperature_c for p in points)
    temp_max = max(p.temperature_c for p in points)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="white" stroke="black" stroke-width="1"/>
  <!-- Plot area -->
  <rect x="{left}" y="{top}" width="{inner_w}" height="{inner_h}" fill="none" stroke="#DDD"/>
  <!-- Gridlines (25%, 50%, 75%) -->
  <g stroke="#EEE" stroke-width="1">
    <line x1="{left}" y1="{top + inner_h*0.25:.1f}" x2="{left+inner_w}" y2="{top + inner_h*0.25:.1f}"/>
    <line x1="{left}" y1="{top + inner_h*0.50:.1f}" x2="{left+inner_w}" y2="{top + inner_h*0.50:.1f}"/>
    <line x1="{left}" y1="{top + inner_h*0.75:.1f}" x2="{left+inner_w}" y2="{top + inner_h*0.75:.1f}"/>
  </g>

  <!-- Series -->
  <polyline fill="none" stroke="#d62728" stroke-width="2" points="{_polyline(coords['temp'])}"/>
  <polyline fill="none" stroke="#1f77b4" stroke-width="2" points="{_polyline(coords['hum'])}"/>
  <polyline fill="none" stroke="#2ca02c" stroke-width="2" points="{_polyline(coords['prec'])}"/>

  <!-- Axes -->
  <line x1="{x0}" y1="{top}" x2="{x0}" y2="{y0}" stroke="#AAA"/>
  <line x1="{x0}" y1="{y0}" x2="{left+inner_w}" y2="{y0}" stroke="#AAA"/>

  <!-- Legend -->
  <g font-family="JetBrains Mono, monospace" font-size="11" fill="#000">
    <rect x="{left}" y="6" width="10" height="2" fill="#d62728"/><text x="{left+14}" y="10">Temp (°C, min {temp_min:.0f}, max {temp_max:.0f})</text>
    <rect x="{left+220}" y="6" width="10" height="2" fill="#1f77b4"/><text x="{left+234}" y="10">Humidity (%)</text>
    <rect x="{left+360}" y="6" width="10" height="2" fill="#2ca02c"/><text x="{left+374}" y="10">Precip (%)</text>
  </g>

  <!-- X ticks -->
  <g font-family="JetBrains Mono, monospace" font-size="10" fill="#000">
{"".join(f'    <text x="{x:.1f}" y="{y0+14}" text-anchor="middle">{label}</text>\\n' for x, label in tick_labels)}  </g>

  <!-- Footer -->
  <g font-family="JetBrains Mono, monospace" font-size="10" fill="#000">
    <text x="{left}" y="{height-10}">Lat {lat:.4f}, Lon {lon:.4f}</text>
    <text x="{width-8}" y="{height-10}" text-anchor="end">Generated {now}</text>
  </g>
</svg>
"""
    p.write_text(svg, encoding="utf-8")

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
        "svg_path": str(p),
        "generated_at": now,
        "lat": lat,
        "lon": lon,
        "items": items,
        "units": {"temperature": "C", "humidity": "%", "precipitation_probability": "%"},
        "source": "open-meteo",
    }
