from pathlib import Path

html = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LA/MS Flash Flood Guidance</title>

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

        #info-banner h3 { margin: 0 0 5px 0; font-size: 15px; }
        #info-banner p { margin: 0; font-size: 11px; color: #555; }
        #ffg-status { margin-top: 4px; font-size: 11px; color: #666; }
        .popup-small { font-family: Arial, sans-serif; font-size: 13px; }
    </style>
</head>

<body>
    <div id="info-banner">
        <h3>LA/MS - Latest 1-Hr Flash Flood Guidance</h3>
        <p>NOAA/NWS raster display layer. Click map for identify response.</p>
        <div id="ffg-status">Loading FFG layer...</div>
    </div>

    <div id="map"></div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

    <script>
        const laMsBounds = L.latLngBounds([28.75, -94.25], [35.15, -88.00]);

        const map = L.map('map', {
            maxBounds: laMsBounds.pad(0.25),
            maxBoundsViscosity: 0.85,
            minZoom: 6,
            maxZoom: 11
        });

        map.fitBounds(laMsBounds);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }).addTo(map);

        const mapServerBase = 'https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer';
        const wmsUrl = 'https://mapservices.weather.noaa.gov/raster/services/precip/rfc_gridded_ffg/MapServer/WMSServer';

        // Use the parent 1-hour mosaic for display. Child layer 3 is query-only here.
        const displayLayer = '0';
        const queryLayer = 'all:3';

        const ffgPane = map.createPane('ffgPane');
        ffgPane.style.zIndex = 450;
        ffgPane.style.pointerEvents = 'none';

        let ffgOverlay = null;
        let refreshTimer = null;
        let requestId = 0;

        function setStatus(message) {
            document.getElementById('ffg-status').textContent = message;
        }

        function getProjectedBbox() {
            const crs = map.options.crs;
            const b = map.getBounds();
            const sw = crs.project(b.getSouthWest());
            const ne = crs.project(b.getNorthEast());
            return [sw.x, sw.y, ne.x, ne.y].join(',');
        }

        function getMapExtentString() {
            const b = map.getBounds();
            return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(',');
        }

        function getImageDisplayString() {
            const size = map.getSize();
            return `${size.x},${size.y},96`;
        }

        function buildWmsImageUrl() {
            const size = map.getSize();
            const params = new URLSearchParams({
                SERVICE: 'WMS',
                REQUEST: 'GetMap',
                VERSION: '1.3.0',
                LAYERS: displayLayer,
                STYLES: '',
                FORMAT: 'image/png',
                TRANSPARENT: 'true',
                CRS: 'EPSG:3857',
                BBOX: getProjectedBbox(),
                WIDTH: String(size.x),
                HEIGHT: String(size.y)
            });
            params.set('_ts', String(Date.now()));
            return `${wmsUrl}?${params.toString()}`;
        }

        function refreshFfgOverlay() {
            const thisRequest = ++requestId;
            const bounds = map.getBounds();
            const url = buildWmsImageUrl();

            setStatus('Loading FFG layer...');
            console.log('FFG WMS URL:', url);

            const img = new Image();
            img.onload = function() {
                if (thisRequest !== requestId) return;
                if (ffgOverlay) map.removeLayer(ffgOverlay);
                ffgOverlay = L.imageOverlay(url, bounds, {
                    opacity: 0.75,
                    pane: 'ffgPane',
                    interactive: false
                }).addTo(map);
                setStatus('FFG layer loaded. Click map to inspect value response.');
            };
            img.onerror = function() {
                if (thisRequest !== requestId) return;
                setStatus('FFG image failed to load; keeping previous view if available.');
                console.error('FFG WMS image failed:', url);
            };
            img.src = url;
        }

        function scheduleFfgRefresh() {
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(refreshFfgOverlay, 250);
        }

        function findReliableNumericValue(result) {
            const attrs = result.attributes || {};
            // Do NOT use Classify.Pixel Value. That is the display-class bucket,
            // which is why the old popup lied with 2.00 inches everywhere.
            const rawCandidates = [
                attrs['Raster.ServicePixelValue'],
                attrs['Raster.PixelValue'],
                attrs['Pixel Value'],
                attrs['Pixel value'],
                attrs['PixelValue'],
                result.value
            ];
            for (const candidate of rawCandidates) {
                const num = parseFloat(candidate);
                if (Number.isFinite(num) && num > 0 && num <= 20) return num;
            }
            return null;
        }

        function buildIdentifyUrl(lat, lng) {
            const params = new URLSearchParams({
                f: 'json',
                geometry: `${lng},${lat}`,
                geometryType: 'esriGeometryPoint',
                sr: '4326',
                layers: queryLayer,
                tolerance: '5',
                mapExtent: getMapExtentString(),
                imageDisplay: getImageDisplayString(),
                returnGeometry: 'false',
                returnUnformattedValues: 'true'
            });
            return `${mapServerBase}/identify?${params.toString()}`;
        }

        map.on('click', function(e) {
            const lat = e.latlng.lat;
            const lng = e.latlng.lng;

            const popup = L.popup()
                .setLatLng(e.latlng)
                .setContent(`<div class="popup-small"><i>Querying NOAA identify endpoint...</i></div>`)
                .openOn(map);

            fetch(buildIdentifyUrl(lat, lng))
                .then(response => response.json())
                .then(data => {
                    console.log('Full identify response:', data);

                    if (!data.results || data.results.length === 0) {
                        popup.setContent(`
                            <div class="popup-small">
                                <b>No identify result returned here.</b><br>
                                <span style="color:#888;">NOAA did not return a gridded value for this click.</span><br><br>
                                <b>Lat:</b> ${lat.toFixed(4)} | <b>Lng:</b> ${lng.toFixed(4)}
                            </div>
                        `);
                        return;
                    }

                    let ffg = null;
                    let chosenResult = null;
                    for (const result of data.results) {
                        const testValue = findReliableNumericValue(result);
                        if (testValue !== null) {
                            ffg = testValue;
                            chosenResult = result;
                            break;
                        }
                    }

                    console.log('Chosen identify result:', chosenResult);
                    console.log('Chosen raw FFG value:', ffg);

                    if (ffg === null) {
                        popup.setContent(`
                            <div class="popup-small">
                                <b>No reliable numeric FFG value returned.</b><br>
                                <span style="color:#888;">
                                    NOAA is drawing the FFG raster, but this identify response did not expose a raw rainfall threshold value.
                                    The old 2.00-inch value was a classified display bucket, not a trustworthy sampled FFG amount.
                                </span><br><br>
                                <b>Lat:</b> ${lat.toFixed(4)} | <b>Lng:</b> ${lng.toFixed(4)}
                            </div>
                        `);
                        return;
                    }

                    popup.setContent(`
                        <div class="popup-small">
                            <strong>1-Hr FFG:</strong>
                            <span style="color:#d9534f; font-weight:bold;">${ffg.toFixed(2)} inches</span><br>
                            <span style="color:#666; font-size:11px;">Raw value returned by NOAA identify endpoint.</span><br><br>
                            <hr style="border:0; border-top:1px solid #ddd; margin:5px 0;">
                            <b>Lat:</b> ${lat.toFixed(4)} | <b>Lng:</b> ${lng.toFixed(4)}
                        </div>
                    `);
                })
                .catch(error => {
                    console.error('Identify error:', error);
                    popup.setContent(`
                        <div class="popup-small">
                            <b>Error:</b> Could not query the NWS FFG identify endpoint.<br>
                            <span style="color:#888;">Check console with F12.</span>
                        </div>
                    `);
                });
        });

        map.whenReady(refreshFfgOverlay);
        map.on('moveend zoomend resize', scheduleFfgRefresh);
    </script>
</body>
</html>
"""

output_file = Path("index.html")
output_file.write_text(html, encoding="utf-8")

print(f"Created: {output_file.resolve()}")