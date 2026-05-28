from pathlib import Path

html = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WFO LIX Flash Flood Guidance</title>

    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />

    <style>
        html, body, #map {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background-color: #1a1a1a;
        }

        #info-banner {
            position: absolute;
            top: 10px;
            left: 50px;
            z-index: 1000;
            background: white;
            padding: 10px 15px;
            border-radius: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.35);
            font-family: Arial, sans-serif;
        }

        #info-banner h3 {
            margin: 0 0 5px 0;
            font-size: 15px;
        }

        #info-banner p {
            margin: 0;
            font-size: 11px;
            color: #555;
        }

        .popup-small {
            font-family: Arial, sans-serif;
            font-size: 13px;
        }

        .bad-value {
            color: #d9534f;
            font-weight: bold;
        }
    </style>
</head>

<body>
    <div id="info-banner">
        <h3>WFO LIX - Latest 1-Hr Flash Flood Guidance</h3>
        <p>Click the map to sample the 1-hour FFG grid</p>
    </div>

    <div id="map"></div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <script>
        // ------------------------------------------------------------
        // Basic map setup
        // ------------------------------------------------------------
        const map = L.map('map').setView([30.2, -90.5], 8);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }).addTo(map);

        // ------------------------------------------------------------
        // NWS Flash Flood Guidance WMS display layer
        // ------------------------------------------------------------
        const ffgWmsUrl = "https://mapservices.weather.noaa.gov/raster/services/precip/rfc_gridded_ffg/MapServer/WmsServer";

        L.tileLayer.wms(ffgWmsUrl, {
            layers: "0",                 // 1-hour FFG visual/display layer
            format: "image/png",
            transparent: true,
            opacity: 0.70,
            attribution: "NOAA / NWS"
        }).addTo(map);

        // ------------------------------------------------------------
        // ArcGIS REST endpoint used for clicking/sampling values
        // ------------------------------------------------------------
        const identifyBaseUrl =
            "https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer/identify";

        // For the NWS FFG service:
        // layer 0 = 1-hour FFG group/display layer
        // layer 3 = 1-hour FFG raster image layer
        const queryLayer = "all:3";

        function getMapExtentString() {
            const b = map.getBounds();

            return [
                b.getWest(),
                b.getSouth(),
                b.getEast(),
                b.getNorth()
            ].join(",");
        }

        function getImageDisplayString() {
            const size = map.getSize();
            return `${size.x},${size.y},96`;
        }

        function findBestNumericValue(result) {
            const attrs = result.attributes || {};

            // Prefer attribute values first. result.value is often garbage for this service.
            const namedCandidates = [
                attrs["Pixel Value"],
                attrs["Pixel value"],
                attrs["PixelValue"],
                attrs["Raster.PixelValue"],
                attrs["Raster.ServicePixelValue"],
                attrs["Classify.Pixel Value"],
                attrs["Stretch.Pixel Value"],
                attrs["Stretched value"],
                attrs["Value"],
                attrs["VALUE"]
            ];

            for (const candidate of namedCandidates) {
                const num = parseFloat(candidate);
                if (Number.isFinite(num) && num > 0 && num <= 20) {
                    return num;
                }
            }

            // Backup scan: look through attributes with pixel/value-looking names.
            for (const [key, val] of Object.entries(attrs)) {
                const keyLower = key.toLowerCase();
                const looksUseful =
                    keyLower.includes("pixel") ||
                    keyLower === "value" ||
                    keyLower.includes("ffg") ||
                    keyLower.includes("guidance");

                if (!looksUseful) continue;

                const num = parseFloat(val);
                if (Number.isFinite(num) && num > 0 && num <= 20) {
                    return num;
                }
            }

            // Last resort, but keep it sanity-limited.
            const resultValue = parseFloat(result.value);
            if (Number.isFinite(resultValue) && resultValue > 0 && resultValue <= 20) {
                return resultValue;
            }

            return null;
        }

        function buildIdentifyUrl(lat, lng) {
            const params = new URLSearchParams({
                f: "json",
                geometry: `${lng},${lat}`,
                geometryType: "esriGeometryPoint",
                sr: "4326",
                layers: queryLayer,
                tolerance: "1",
                mapExtent: getMapExtentString(),
                imageDisplay: getImageDisplayString(),
                returnGeometry: "false",
                returnUnformattedValues: "true"
            });

            return `${identifyBaseUrl}?${params.toString()}`;
        }

        map.on("click", function(e) {
            const lat = e.latlng.lat;
            const lng = e.latlng.lng;

            const popup = L.popup()
                .setLatLng(e.latlng)
                .setContent(`<div class="popup-small"><i>Sampling FFG grid...</i></div>`)
                .openOn(map);

            const identifyUrl = buildIdentifyUrl(lat, lng);

            fetch(identifyUrl)
                .then(response => response.json())
                .then(data => {
                    console.log("Full identify response:", data);

                    if (!data.results || data.results.length === 0) {
                        popup.setContent(`
                            <div class="popup-small">
                                <b>No FFG value returned here.</b><br>
                                <span style="color:#888;">
                                    NOAA did not return a gridded value for this click.
                                </span><br><br>
                                <b>Lat:</b> ${lat.toFixed(4)} |
                                <b>Lng:</b> ${lng.toFixed(4)}
                            </div>
                        `);
                        return;
                    }

                    const result = data.results[0];
                    const ffg = findBestNumericValue(result);

                    console.log("Chosen result:", result);
                    console.log("Chosen FFG value:", ffg);

                    if (ffg === null) {
                        popup.setContent(`
                            <div class="popup-small">
                                <b>No FFG value returned here.</b><br>
                                <span style="color:#888;">
                                    NOAA returned NoData for this raster pixel. This usually means water, marsh,
                                    outside the valid raster area, or a masked grid cell.
                                </span><br><br>
                                <b>Lat:</b> ${lat.toFixed(4)} |
                                <b>Lng:</b> ${lng.toFixed(4)}
                            </div>
                        `);
                        return;
                    }

                    popup.setContent(`
                        <div class="popup-small">
                            <strong>1-Hr FFG:</strong>
                            <span style="color:#d9534f; font-weight:bold;">
                                ${ffg.toFixed(2)} inches
                            </span><br>
                            <span style="color:#666; font-size:11px;">
                                Rainfall required in 1 hour to initiate flash flooding.
                            </span><br><br>
                            <hr style="border:0; border-top:1px solid #ddd; margin:5px 0;">
                            <b>Lat:</b> ${lat.toFixed(4)} |
                            <b>Lng:</b> ${lng.toFixed(4)}
                        </div>
                    `);
                })
                .catch(error => {
                    console.error("Identify error:", error);

                    popup.setContent(`
                        <div class="popup-small">
                            <b>Error:</b> Could not query the NWS FFG service.<br>
                            <span style="color:#888;">Check console with F12.</span>
                        </div>
                    `);
                });
        });
    </script>
</body>
</html>
"""

output_file = Path("index.html")
output_file.write_text(html, encoding="utf-8")

print(f"Created: {output_file.resolve()}")