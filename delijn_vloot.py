import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import folium_static

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker Pro", page_icon="🚌")

# CSS: Optimale benutting van schermruimte en zichtbaarheid van kaart-elementen
st.markdown("""
    <style>
        .block-container { padding: 0.5rem 1rem 0rem 1rem !important; max-width: 100% !important; }
        .stSlider { padding-bottom: 0px; }
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

def geocode_city(city_name):
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={city_name.replace(' ', '+')}&format=json&limit=1"
        headers = {"User-Agent": "DeLijnTrackerApp"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read().decode())
            if data: return [float(data[0]['lat']), float(data[0]['lon'])]
    except: return None
    return None

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

# --- SIDEBAR: BESTURING ---
with st.sidebar:
    st.title("🗺️ Kaart & Zone")
    search_city = st.text_input("1. Locatie zoeken:", placeholder="Breendonk, Dorp")
    if st.button("Kaart verplaatsen"):
        coord = geocode_city(search_city)
        if coord:
            st.session_state.center_coord = coord
            st.rerun()

    st.session_state.map_zoom = st.slider("2. Kaart Zoom", 7, 18, st.session_state.map_zoom)

    st.divider()
    st.write("📐 **Zone Fine-tuning**")
    base_m = st.slider("Basis grootte (m)", 10, 500, 150)
    
    # Directere feedback voor de sliders (stappen van 0.0001 graden ~ 11 meter)
    off_n = st.slider("Noord ↑", -0.0050, 0.0050, 0.0000, format="%.4f")
    off_s = st.slider("Zuid ↓", -0.0050, 0.0050, 0.0000, format="%.4f")
    off_e = st.slider("Oost →", -0.0050, 0.0050, 0.0000, format="%.4f")
    off_w = st.slider("West ←", -0.0050, 0.0050, 0.0000, format="%.4f")

    # Bereken finale coördinaten
    deg_base = base_m / 111000
    lat_n = st.session_state.center_coord[0] + deg_base + off_n
    lat_s = st.session_state.center_coord[0] - deg_base + off_s
    lon_e = st.session_state.center_coord[1] + (deg_base * 1.5) + off_e
    lon_w = st.session_state.center_coord[1] - (deg_base * 1.5) + off_w
    
    CHECK_ZONE_BOX = [[lat_s, lon_w], [lat_n, lon_w], [lat_n, lon_e], [lat_s, lon_e]]

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
        in_zone = lat_s <= lat <= lat_n and lon_w <= lon <= lon_e
        
        if in_zone and not st.session_state.in_zone_last[b_id]:
            st.session_state.counter[b_id] += 1
        
        st.session_state.in_zone_last[b_id] = in_zone
        current_bussen.append({"id": b_id, "lat": lat, "lon": lon, "speed": loc.get('speed', 0), "in_zone": in_zone})

# --- HOOFDSCHERM ---
st.subheader("🚌 De Lijn Live Vloot Monitor")

m = folium.Map(
    location=st.session_state.center_coord, 
    zoom_start=st.session_state.map_zoom, 
    control_scale=True
)

folium.Polygon(
    locations=CHECK_ZONE_BOX, color="#e74c3c", weight=3, 
    fill=True, fill_color="#e74c3c", fill_opacity=0.2, tooltip="Meetzone"
).add_to(m)

for b in current_bussen:
    color = "#2ecc71" if b["in_zone"] else "#3498db"
    icon_html = f'''
        <div style="display: flex; flex-direction: column; align-items: center; width: 100px;">
            <div style="color: {color}; font-size: 26px; text-shadow: 1px 1px 3px black;">●</div>
            <div style="background: rgba(255,255,255,0.95); border: 1px solid #333; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; color: black; white-space: nowrap;">
                {b['id']} ({b['speed']} km/u)
            </div>
        </div>
    '''
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=icon_html, icon_size=(100, 50), icon_anchor=(50, 25))).add_to(m)

# breedte=1350 is meestal de sweet spot voor 'full width' op desktop zonder dat de knoppen wegvallen
folium_static(m, width=1350, height=800)

c1, c2 = st.columns(2)
tz = pytz.timezone('Europe/Brussels')
with c1: st.info(f"🕒 Update: {datetime.now(tz).strftime('%H:%M:%S')}")
with c2: st.success(f"🚌 Bussen online: {len(current_bussen)}")

time.sleep(30)
st.rerun()
