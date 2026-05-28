import folium
import webbrowser
import os

# 1. Setup the map centered over New Orleans / Baton Rouge
# [Latitude, Longitude]
wfo_lix_center = [30.2, -90.5]
m = folium.Map(location=wfo_lix_center, zoom_start=8, tiles="OpenStreetMap")

# 2. Pull the latest NWS 1-Hour Flash Flood Guidance Layer
# This acts like a digital blanket over the map
nws_wms_url = "https://mapservices.weather.noaa.gov/raster/services/precip/rfc_gridded_ffg/MapServer/WmsServer"

folium.raster_layers.WmsTileLayer(
    url=nws_wms_url,
    layers="0", # Layer '0' is the 1-Hour guidance data
    fmt="image/png",
    transparent=True,
    version="1.3.0",
    name="NWS 1-Hour Flash Flood Guidance",
    attr="National Weather Service",
    overlay=True,
    control=True,
    opacity=0.7
).add_to(m)

# 3. Add a tool that gives you the coordinates wherever your cursor clicks
m.add_child(folium.LatLngPopup())

# 4. Save it as a web page and automatically open it for you
output_file = "wfo_lix_flood_map.html"
m.save(output_file)

# Open the map automatically in your internet browser
webbrowser.open('file://' + os.path.realpath(output_file))
print("Map successfully created! It should now open in your internet browser.")
