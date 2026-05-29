from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pygrib
import requests
from matplotlib.colors import BoundaryNorm, ListedColormap
from scipy.interpolate import griddata

BASE_URL = "https://ftp-wpc.ncep.noaa.gov/workoff/ffg/"
FILE_RE = re.compile(r"5kmffg_\d{10}\.grb2")
DATA_DIR = Path("data")
GRIB_PATH = DATA_DIR / "latest_lmrfc_ffg.grb2"
JSON_PATH = DATA_DIR / "ffg_grid.json"
PNG_PATH = DATA_DIR / "ffg_overlay.png"
INDEX_PATH = Path("index.html")

# LA/MS plus immediate LMRFC operational context.
XMIN, YMIN, XMAX, YMAX = -94.15, 28.70, -87.80, 35.20
PAN_XMIN, PAN_YMIN, PAN_XMAX, PAN_YMAX = -94.65, 28.25, -87.35, 35.65
NX, NY = 420, 430


def newest_ffg_url() -> tuple[str, str]:
    response = requests.get(BASE_URL, timeout=45)
    response.raise_for_status()
    files = sorted(set(FILE_RE.findall(response.text)))
    if not files:
        raise RuntimeError(f"No 5kmffg_YYYYMMDDHH.grb2 files found at {BASE_URL}")
    filename = files[-1]
    return urljoin(BASE_URL, filename), filename


def download_grib(url: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with requests.get(url, timeout=120, stream=True) as response:
        response.raise_for_status()
        with GRIB_PATH.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def intersects_local_box(lons: np.ndarray, lats: np.ndarray) -> bool:
    lon_min, lon_max = np.nanmin(lons), np.nanmax(lons)
    lat_min, lat_max = np.nanmin(lats), np.nanmax(lats)
    return not (lon_max < XMIN or lon_min > XMAX or lat_max < YMIN or lat_min > YMAX)


def message_score(grb) -> tuple[float, float, float]:
    lats, lons = grb.latlons()
    if not intersects_local_box(lons, lats):
        return (999999.0, 999999.0, 999999.0)

    lon_span = float(np.nanmax(lons) - np.nanmin(lons))
    lat_span = float(np.nanmax(lats) - np.nanmin(lats))
    area = lon_span * lat_span

    # Prefer 1-hour FFG if the GRIB metadata exposes a duration-like clue.
    step_range = str(getattr(grb, "stepRange", ""))
    forecast_time = getattr(grb, "forecastTime", None)
    duration_penalty = 0.0 if (step_range in {"0-1", "1"} or forecast_time in {0, 1}) else 1000.0

    # Prefer smaller native RFC-sized grids over a full CONUS mosaic if both appear.
    return (duration_penalty + area, lon_span, lat_span)


def pick_lmrfc_message():
    candidates = []
    with pygrib.open(str(GRIB_PATH)) as grbs:
        for grb in grbs:
            text = " ".join([
                str(getattr(grb, "name", "")),
                str(getattr(grb, "shortName", "")),
                str(getattr(grb, "parameterName", "")),
                str(getattr(grb, "typeOfLevel", "")),
            ]).lower()
            if "ffg" not in text and "flash flood guidance" not in text:
                # Some files have weak names, so still allow precipitation-like candidates,
                # but they will only be selected if they intersect the local domain.
                if "precip" not in text and "rain" not in text:
                    continue

            try:
                score = message_score(grb)
            except Exception:
                continue

            if score[0] < 999999.0:
                candidates.append((score, grb.messagenumber))

    if not candidates:
        raise RuntimeError("No usable FFG-like GRIB2 message intersected the LA/MS domain.")

    candidates.sort(key=lambda item: item[0])
    chosen_message_number = candidates[0][1]

    grbs = pygrib.open(str(GRIB_PATH))
    return grbs, grbs.message(chosen_message_number)


def values_to_inches(values: np.ndarray, units: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    arr[arr > 10000] = np.nan
    arr[arr <= 0] = np.nan

    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return arr

    units_lower = (units or "").lower()
    median_value = float(np.nanmedian(finite))

    if "kg" in units_lower or "mm" in units_lower or median_value > 20:
        arr = arr / 25.4
    elif units_lower in {"m", "meter", "meters"}:
        arr = arr * 39.3701

    arr[(arr <= 0) | (arr > 20)] = np.nan
    return arr


def build_grid() -> dict:
    url, filename = newest_ffg_url()
    print(f"Downloading {url}")
    download_grib(url)

    grbs, grb = pick_lmrfc_message()
    try:
        lats, lons = grb.latlons()
        values = np.ma.filled(grb.values, np.nan)
        values_in = values_to_inches(values, getattr(grb, "units", ""))

        mask = (
            np.isfinite(lats) & np.isfinite(lons) & np.isfinite(values_in) &
            (lons >= PAN_XMIN) & (lons <= PAN_XMAX) &
            (lats >= PAN_YMIN) & (lats <= PAN_YMAX)
        )

        if np.count_nonzero(mask) < 10:
            raise RuntimeError("Selected GRIB message had too few valid local points.")

        grid_lon = np.linspace(XMIN, XMAX, NX)
        grid_lat = np.linspace(YMIN, YMAX, NY)
        gx, gy = np.meshgrid(grid_lon, grid_lat)

        points = np.column_stack([lons[mask].ravel(), lats[mask].ravel()])
        vals = values_in[mask].ravel()
        local_grid = griddata(points, vals, (gx, gy), method="nearest")
        local_grid[(local_grid <= 0) | (local_grid > 20)] = np.nan

        metadata = {
            "source_url": url,
            "source_file": filename,
            "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
            "grib_name": str(getattr(grb, "name", "")),
            "grib_short_name": str(getattr(grb, "shortName", "")),
            "grib_units": str(getattr(grb, "units", "")),
            "grib_data_date": str(getattr(grb, "dataDate", "")),
            "grib_data_time": str(getattr(grb, "dataTime", "")),
            "grib_forecast_time": str(getattr(grb, "forecastTime", "")),
            "grib_step_range": str(getattr(grb, "stepRange", "")),
            "grib_message_number": int(getattr(grb, "messagenumber", -1)),
        }
    finally:
        grbs.close()

    return {
        "extent": {"xmin": XMIN, "ymin": YMIN, "xmax": XMAX, "ymax": YMAX},
        "panLimit": {"xmin": PAN_XMIN, "ymin": PAN_YMIN, "xmax": PAN_XMAX, "ymax": PAN_YMAX},
        "nx": NX,
        "ny": NY,
        "metadata": metadata,
        "values": [[None if not np.isfinite(v) else round(float(v), 2) for v in row] for row in local_grid],
    }


def write_overlay(grid: dict) -> None:
    arr = np.array([[np.nan if v is None else float(v) for v in row] for row in grid["values"]])

    colors = [
        "#0033cc", "#0066ff", "#00a6ff", "#00d0d0", "#00b050",
        "#80d000", "#ffd000", "#ff9900", "#ff0000", "#cc00cc"
    ]
    bounds = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 7, 20]
    cmap = ListedColormap(colors)
    cmap.set_bad((0, 0, 0, 0))
    norm = BoundaryNorm(bounds, cmap.N)

    fig = plt.figure(figsize=(10, 10), dpi=160)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(
        arr,
        origin="lower",
        extent=[XMIN, XMAX, YMIN, YMAX],
        cmap=cmap,
        norm=norm,
        interpolation="nearest",
    )
    ax.set_xlim(XMIN, XMAX)
    ax.set_ylim(YMIN, YMAX)
    ax.axis("off")
    fig.savefig(PNG_PATH, transparent=True, bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def write_json(grid: dict) -> None:
    JSON_PATH.write_text(json.dumps(grid, separators=(",", ":")), encoding="utf-8")


def write_index() -> None:
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LMRFC Flash Flood Guidance</title>
    <link rel="stylesheet" href="https://js.arcgis.com/4.30/esri/themes/dark/main.css" />
    <style>
        html, body, #viewDiv {{ margin:0; padding:0; width:100%; height:100%; background:#111; overflow:hidden; }}
        #info-banner {{ position:absolute; top:12px; left:58px; z-index:10; background:rgba(255,255,255,.96); color:#222; padding:10px 14px; border-radius:7px; box-shadow:0 2px 8px rgba(0,0,0,.35); font-family:Arial,sans-serif; max-width:410px; }}
        #info-banner h3 {{ margin:0 0 4px 0; font-size:15px; line-height:1.2; }}
        #info-banner p, #ffg-status {{ margin:0; font-size:11px; color:#555; line-height:1.35; }}
        #ffg-status {{ margin-top:5px; font-weight:600; }}
        .popup-small {{ font-family:Arial,sans-serif; font-size:13px; line-height:1.35; }}
        .ffg-value {{ color:#d9534f; font-weight:bold; }}
    </style>
</head>
<body>
    <div id="info-banner">
        <h3>LMRFC Native 1-Hr Flash Flood Guidance</h3>
        <p>Built from WPC raw GRIB2 FFG dump, locally regridded for LA/MS.</p>
        <div id="ffg-status">Loading native FFG grid...</div>
    </div>
    <div id="viewDiv"></div>
    <script src="https://js.arcgis.com/4.30/"></script>
    <script>
        require([
            "esri/Map", "esri/views/MapView", "esri/geometry/Extent",
            "esri/layers/MediaLayer", "esri/layers/support/ImageElement",
            "esri/layers/support/ExtentAndRotationGeoreference", "esri/widgets/Home", "esri/widgets/LayerList"
        ], function(Map, MapView, Extent, MediaLayer, ImageElement, ExtentAndRotationGeoreference, Home, LayerList) {{
            const gridUrl = "data/ffg_grid.json?v={datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}";
            const imageUrl = "data/ffg_overlay.png?v={datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}";
            let ffgGrid = null;

            function setStatus(msg) {{ document.getElementById("ffg-status").textContent = msg; }}

            fetch(gridUrl).then(r => r.json()).then(data => {{
                ffgGrid = data;
                const e = data.extent;
                const p = data.panLimit;
                const localExtent = new Extent({{ xmin:e.xmin, ymin:e.ymin, xmax:e.xmax, ymax:e.ymax, spatialReference:{{ wkid:4326 }} }});
                const panLimit = new Extent({{ xmin:p.xmin, ymin:p.ymin, xmax:p.xmax, ymax:p.ymax, spatialReference:{{ wkid:4326 }} }});

                const imageElement = new ImageElement({{
                    image: imageUrl,
                    georeference: new ExtentAndRotationGeoreference({{ extent: localExtent }})
                }});

                const ffgLayer = new MediaLayer({{
                    title: "Native LMRFC 1-Hr FFG",
                    source: [imageElement],
                    opacity: 0.82
                }});

                const map = new Map({{ basemap:"dark-gray-vector", layers:[ffgLayer] }});
                const view = new MapView({{
                    container:"viewDiv",
                    map,
                    extent: localExtent,
                    constraints: {{ geometry: panLimit, minZoom:6, maxZoom:12, rotationEnabled:false }},
                    popup: {{ dockEnabled:false, collapseEnabled:false }}
                }});

                view.when(() => {{
                    view.ui.add(new Home({{ view }}), "top-left");
                    view.ui.add(new LayerList({{ view }}), "top-right");
                    const m = data.metadata || {{}};
                    setStatus(`Loaded ${{m.source_file || "native GRIB2"}} | msg ${{m.grib_message_number || "?"}} | ${{m.created_utc || ""}}`);
                }});

                function sampleGrid(lon, lat) {{
                    if (!ffgGrid) return null;
                    const e = ffgGrid.extent;
                    if (lon < e.xmin || lon > e.xmax || lat < e.ymin || lat > e.ymax) return null;
                    const col = Math.round((lon - e.xmin) / (e.xmax - e.xmin) * (ffgGrid.nx - 1));
                    const row = Math.round((lat - e.ymin) / (e.ymax - e.ymin) * (ffgGrid.ny - 1));
                    if (row < 0 || row >= ffgGrid.ny || col < 0 || col >= ffgGrid.nx) return null;
                    const value = ffgGrid.values[row][col];
                    return Number.isFinite(value) ? value : null;
                }}

                view.on("click", (event) => {{
                    const lon = event.mapPoint.longitude;
                    const lat = event.mapPoint.latitude;
                    const value = sampleGrid(lon, lat);
                    if (value === null) {{
                        view.popup.open({{
                            title:"No current local FFG data",
                            location:event.mapPoint,
                            content:`<div class="popup-small"><b>No current local FFG data available for this sector.</b><br><span style="color:#666;font-size:11px;">This pixel is outside the local grid, masked, missing, or unissued.</span><br><br><b>Lat:</b> ${{lat.toFixed(4)}} | <b>Lng:</b> ${{lon.toFixed(4)}}</div>`
                        }});
                        return;
                    }}
                    view.popup.open({{
                        title:"Native 1-Hr Flash Flood Guidance",
                        location:event.mapPoint,
                        content:`<div class="popup-small"><strong>1-Hr FFG:</strong> <span class="ffg-value">${{value.toFixed(2)}} inches</span><br><span style="color:#666;font-size:11px;">Sampled from locally generated native LMRFC/WPC GRIB2 grid.</span><br><br><b>Lat:</b> ${{lat.toFixed(4)}} | <b>Lng:</b> ${{lon.toFixed(4)}}</div>`
                    }});
                }});
            }}).catch(err => {{
                console.error(err);
                setStatus("Native FFG grid failed to load. Check workflow/data output.");
            }});
        }});
    </script>
</body>
</html>'''
    INDEX_PATH.write_text(html, encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    grid = build_grid()
    write_json(grid)
    write_overlay(grid)
    write_index()
    print(f"Created {INDEX_PATH}, {JSON_PATH}, and {PNG_PATH}")


if __name__ == "__main__":
    main()
