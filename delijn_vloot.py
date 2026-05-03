import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import folium_static
from folium.plugins import Draw

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker Pro", page_icon="🚌")

st.markdown("""
    <style>
        .block-container { padding: 0.5rem 1rem 0rem 1rem !important; max-width: 100% !important; }
        .folium-map { border-radius: 8px; border: 1px solid #ccc; margin: auto; }
    </style>
""", unsafe_allow_html=True)

# --- BEVEILIGING ---
if "auth" not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("🔒 Beveiligde Toegang")
    pwd = st.text_input("Wachtwoord:", type="password")
    if st.button("Inloggen"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.auth = True
            st.rerun()
        else: st.error("❌ Verkeerd")
    st.stop()

# --- DATA FUNCTIES ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

if 'counter' not in st.session_state: st.session_state.counter = {b_id: 0 for b_id in FLEET}
if 'in_zone_last' not in st.session_state: st.session_state.in_zone_last = {b_id: False for b_id in FLEET}
if 'center_coord' not in st.session_state: st.session_state.center_coord = [51.05, 4.33]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 15
if 'drawn_polygon' not in st.session_state: st.session_state.drawn_polygon = None

def is_in_polygon(lat, lon, polygon):
    """Ray Casting algoritme om te checken of punt in polygoon ligt."""
    if not polygon: return False
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if lon > min(p1y, p2y):
            if lon <= max(p1y, p2y):
                if lat <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or lat <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def get_bus_data(bus_id):
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}&t={int(time.time())}"
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": API_KEY, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data["data"][0] if data.get("data") else None
    except: return None

# --- SIDEBAR ---
with st.sidebar:
    st.title("🗺️ Kaart Instellingen")
    search_city = st.text_input("Locatie zoeken:", placeholder="Breendonk")
    if st.button("Ga naar locatie"):
        # Geocode functie hier herhalen indien nodig of hardcode Breendonk
        st.session_state.center_coord = [51.0425, 4.3320] # Voorbeeld Breendonk
        st.rerun()

    st.session_state.map_zoom = st.slider("Zoomniveau", 7, 18, st.session_state.map_zoom)
    
    st.divider()
    st.title("📊 Passages")
    for b_id, count in st.session_state.counter.items():
        st.write(f"Bus {b_id}: **{count}**")
    
    if st.button("Reset Tellers"):
        st.session_state.counter = {b_id: 0 for b_id in FLEET}
        st.rerun()

# --- VERWERKING ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        lat, lon = loc['lat'], loc['lon']
        heading = loc.get('heading', 0)
        
        in_zone = False
        if st.session_state.drawn_polygon:
            in_zone = is_in_polygon(lat, lon, st.session_state.drawn_polygon)
        
        if in_zone and not st.session_state.in_zone_last[b_id]:
            st.session_state.counter[b_id] += 1
        
        st.session_state.in_zone_last[b_id] = in_zone
        current_bussen.append({
            "id": b_id, "lat": lat, "lon": lon, 
            "speed": loc.get('speed', 0), "heading": heading, "in_zone": in_zone
        })

# --- HOOFDSCHERM ---
st.subheader("🚌 De Lijn Live Monitor - Teken je zone op de kaart")

m = folium.Map(location=st.session_state.center_coord, zoom_start=st.session_state.map_zoom)

# Tekentool toevoegen
draw = Draw(
    draw_options={'polyline': False, 'rectangle': True, 'polygon': True, 'circle': False, 'marker': False, 'circlemarker': False},
    edit_options={'edit': False}
)
draw.add_to(m)

# Als er al een zone getekend was, tonen we deze opnieuw
if st.session_state.drawn_polygon:
    folium.Polygon(locations=st.session_state.drawn_polygon, color="red", weight=2, fill=True, fill_opacity=0.2).add_to(m)

for b in current_bussen:
    color = "#2ecc71" if b["in_zone"] else "#3498db"
    # Pijltje toevoegen met heading
    icon_html = f'''
        <div style="display: flex; flex-direction: column; align-items: center; width: 100px;">
            <div style="transform: rotate({b['heading']}deg); color: {color}; font-size: 28px; text-shadow: 1px 1px 3px black;">⬆</div>
            <div style="background: rgba(255,255,255,0.95); border: 1px solid #333; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; color: black; white-space: nowrap; margin-top: -5px;">
                {b['id']} ({b['speed']} km/u)
            </div>
        </div>
    '''
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=icon_html, icon_size=(100, 60), icon_anchor=(50, 30))).add_to(m)

# De kaart weergeven en data opvangen
output = folium_static(m, width=1350, height=800)

# LOGICA: Pak de getekende vorm op
# Let op: Streamlit-folium geeft getekende vormen terug in de return waarde
# We checken of er een nieuwe 'draw' actie is geweest
if output and 'last_active_drawing' in output and output['last_active_drawing']:
    new_poly = output['last_active_drawing']['geometry']['coordinates'][0]
    # GeoJSON gebruikt [lon, lat], wij hebben [lat, lon] nodig
    formatted_poly = [[p[1], p[0]] for p in new_poly]
    if st.session_state.drawn_polygon != formatted_poly:
        st.session_state.drawn_polygon = formatted_poly
        st.rerun()

c1, c2 = st.columns(2)
tz = pytz.timezone('Europe/Brussels')
with c1: st.info(f"🕒 Update: {datetime.now(tz).strftime('%H:%M:%S')}")
with c2: st.success(f"🚌 Bussen online: {len(current_bussen)}")

time.sleep(30)
st.rerun()
