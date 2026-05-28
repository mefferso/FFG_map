from pathlib import Path

html = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LMRFC Flash Flood Guidance</title>

    <link rel="stylesheet" href="https://js.arcgis.com/4.30/esri/themes/dark/main.css" />

    <style>
        html, body, #viewDiv {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background: #111;
            overflow: hidden;
        }

        #info-banner {
            position: absolute;
            top: 12px;
            left: 58px;
            z-index: 10;
            background: rgba(255, 255, 255, 0.96);
            color: #222;
            padding: 10px 14px;
            border-radius: 7px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
            font-family: Arial, sans-serif;
            max-width: 390px;
        }

        #info-banner h3 {
            margin: 0 0 4px 0;
            font-size: 15px;
            line-height: 1.2;
        }

        #info-banner p,
        #ffg-status {
            margin: 0;
            font-size: 11px;
            color: #555;
            line-height: 1.3;
        }

        #ffg-status {
            margin-top: 5px;
            font-weight: 600;
        }

        .popup-small {
            font-family: Arial, sans-serif;
            font-size: 13px;
            line-height: 1.35;
        }

        .ffg-value {
            color: #d9534f;
            font-weight: bold;
        }
    </style>
</head>

<body>
    <div id="info-banner">
        <h3>LMRFC Local 1-Hr Flash Flood Guidance</h3>
        <p>Focused on Louisiana, Mississippi, and nearby hydrologic context.</p>
        <div id="ffg-status">Loading FFG layer...</div>
    </div>

    <div id="viewDiv"></div>

    <script src="https://js.arcgis.com/4.30/"></script>

    <script>
        require([
            "esri/Map",
            "esri/views/MapView",
            "esri/layers/MapImageLayer",
            "esri/geometry/Extent",
            "esri/rest/identify",
            "esri/rest/support/IdentifyParameters",
            "esri/widgets/LayerList",
            "esri/widgets/Legend",
            "esri/widgets/Home"
        ], function(Map, MapView, MapImageLayer, Extent, identify, IdentifyParameters, LayerList, Legend, Home) {
            // No dedicated public LMRFC-only FFG MapServer was found. This uses the
            // national RFC mosaic service but keeps display, navigation, and identify
            // operations constrained to the local LMRFC/LA/MS operating area.
            const mapServerUrl = "https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer";

            const lmrfcLocalExtent = new Extent({
                xmin: -94.15,
                ymin: 28.70,
                xmax: -87.80,
                ymax: 35.20,
                spatialReference: { wkid: 4326 }
            });

            const lmrfcPanLimit = new Extent({
                xmin: -94.65,
                ymin: 28.25,
                xmax: -87.35,
                ymax: 35.65,
                spatialReference: { wkid: 4326 }
            });

            const ffgLayer = new MapImageLayer({
                url: mapServerUrl,
                title: "1-Hr Flash Flood Guidance",
                opacity: 0.82,
                imageFormat: "png32",
                refreshInterval: 60,
                sublayers: [
                    {
                        id: 0,
                        title: "1-Hr FFG",
                        visible: true
                    }
                ]
            });

            const map = new Map({
                basemap: "dark-gray-vector",
                layers: [ffgLayer]
            });

            const view = new MapView({
                container: "viewDiv",
                map,
                extent: lmrfcLocalExtent,
                constraints: {
                    geometry: lmrfcPanLimit,
                    minZoom: 6,
                    maxZoom: 12,
                    rotationEnabled: false
                },
                popup: {
                    dockEnabled: false,
                    collapseEnabled: false
                }
            });

            function setStatus(message) {
                document.getElementById("ffg-status").textContent = message;
            }

            ffgLayer.when(function() {
                setStatus("FFG display layer loaded from NOAA national mosaic, constrained locally.");
                console.log("FFG MapImageLayer loaded:", ffgLayer);
            }).catch(function(error) {
                setStatus("FFG layer failed to load. Check console.");
                console.error("FFG layer load error:", error);
            });

            view.when(function() {
                view.goTo(lmrfcLocalExtent, { animate: false }).catch(function(error) {
                    console.warn("Initial extent goTo warning:", error);
                });

                view.ui.add(new Home({ view: view }), "top-left");

                const layerList = new LayerList({ view: view });
                view.ui.add(layerList, "top-right");

                const legend = new Legend({
                    view: view,
                    layerInfos: [{ layer: ffgLayer, title: "1-Hr FFG" }]
                });
                view.ui.add(legend, "bottom-right");
            });

            function parseMaybeNumber(value) {
                if (value === undefined || value === null) return null;
                const text = String(value).trim();
                if (text.length === 0 || text.toLowerCase() === "nodata") return null;
                const num = parseFloat(text);
                if (!Number.isFinite(num)) return null;
                if (num <= 0 || num > 20) return null;
                return num;
            }

            function getRawFfgValue(result) {
                const attrs = result.attributes || {};
                const rawFieldNames = [
                    "Raster.ServicePixelValue",
                    "Raster.PixelValue",
                    "ServicePixelValue",
                    "Pixel Value",
                    "Pixel value",
                    "PixelValue",
                    "value"
                ];

                for (const name of rawFieldNames) {
                    const num = parseMaybeNumber(attrs[name]);
                    if (num !== null) return num;
                }

                const directValue = parseMaybeNumber(result.value);
                if (directValue !== null) return directValue;

                return null;
            }

            function getDisplayClass(result) {
                const attrs = result.attributes || {};
                return attrs["Classify.Pixel Value"] ?? attrs["Classify.PixelValue"] ?? null;
            }

            function showNoLocalDataPopup(mapPoint, lat, lon, displayClass = null) {
                view.popup.open({
                    title: "No current local FFG data",
                    location: mapPoint,
                    content: `
                        <div class="popup-small">
                            <b>No current local FFG data available for this sector.</b><br>
                            <span style="color:#666; font-size:11px;">
                                The layer may be temporarily missing, unissued, masked, or the identify response may not expose a raw pixel value here.
                                ${displayClass !== null ? `<br>Display class returned: ${displayClass}` : ""}
                            </span><br><br>
                            <b>Lat:</b> ${lat.toFixed(4)} | <b>Lng:</b> ${lon.toFixed(4)}
                        </div>
                    `
                });
            }

            view.on("click", async function(event) {
                const lat = event.mapPoint.latitude;
                const lon = event.mapPoint.longitude;

                view.popup.open({
                    title: "Sampling 1-Hr FFG",
                    location: event.mapPoint,
                    content: `<div class="popup-small"><i>Querying NOAA identify endpoint...</i></div>`
                });

                const params = new IdentifyParameters({
                    tolerance: 6,
                    returnGeometry: false,
                    layerOption: "all",
                    layerIds: [0],
                    geometry: event.mapPoint,
                    mapExtent: view.extent,
                    width: view.width,
                    height: view.height
                });

                try {
                    const response = await identify.identify(mapServerUrl, params);
                    console.log("Full ArcGIS identify response:", response);

                    const results = response.results || [];
                    if (results.length === 0) {
                        showNoLocalDataPopup(event.mapPoint, lat, lon);
                        return;
                    }

                    let rawFfg = null;
                    let displayClass = null;
                    let chosenResult = null;

                    for (const result of results) {
                        const testValue = getRawFfgValue(result);
                        if (displayClass === null) displayClass = getDisplayClass(result);

                        if (testValue !== null) {
                            rawFfg = testValue;
                            chosenResult = result;
                            break;
                        }
                    }

                    console.log("Chosen identify result:", chosenResult);
                    console.log("Raw FFG value:", rawFfg);
                    console.log("Display class value:", displayClass);

                    if (rawFfg === null) {
                        showNoLocalDataPopup(event.mapPoint, lat, lon, displayClass);
                        return;
                    }

                    view.popup.open({
                        title: "1-Hr Flash Flood Guidance",
                        location: event.mapPoint,
                        content: `
                            <div class="popup-small">
                                <strong>1-Hr FFG:</strong>
                                <span class="ffg-value">${rawFfg.toFixed(2)} inches</span><br>
                                <span style="color:#666; font-size:11px;">Raw value returned by NOAA identify layer 0.</span><br><br>
                                <b>Lat:</b> ${lat.toFixed(4)} | <b>Lng:</b> ${lon.toFixed(4)}
                            </div>
                        `
                    });
                } catch (error) {
                    console.error("Identify error:", error);
                    showNoLocalDataPopup(event.mapPoint, lat, lon);
                }
            });
        });
    </script>
</body>
</html>'''

output_file = Path("index.html")
output_file.write_text(html, encoding="utf-8")

print(f"Created: {output_file.resolve()}")