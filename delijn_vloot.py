import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import folium_static

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker", page_icon="🚌")

# CSS voor maximale benutting van het scherm (Horizontaal & Verticaal)
st.markdown("""
    <style>
        .block-container { padding: 1rem 1% 0rem 1% !important; max-width: 100% !important; }
        footer {visibility: hidden;}
        .stSlider { padding-bottom: 0px; }
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

# --- SIDEBAR: ZONE & FINE-TUNING ---
with st.sidebar:
    st.title("🎯 Zone Setup")
    search_city = st.text_input("1. Zoek locatie:", placeholder="Gemeente of straat")
    if st.button("Verplaats kaart"):
        coord = geocode_city(search_city)
        if coord:
            st.session_state.center_coord = coord
            st.rerun()

    st.divider()
    st.write("2. Grootte & Fine-tuning")
    base_size = st.slider("Basis grootte (m)", 20, 1000, 200) / 111000
    
    # Fine-tuning sliders voor elke windrichting
    off_n = st.slider("Noord offset", -0.0050, 0.0050, 0.0000, format="%.4f")
    off_s = st.slider("Zuid offset", -0.0050, 0.0050, 0.0000, format="%.4f")
    off_e = st.slider("Oost offset", -0.0050, 0.0050, 0.0000, format="%.4f")
    off_w = st.slider("West offset", -0.0050, 0.0050, 0.0000, format="%.4f")

    # Bereken finale coördinaten
    lat_n = st.session_state.center_coord[0] + base_size + off_n
    lat_s = st.session_state.center_coord[0] - base_size + off_s
    lon_e = st.session_state.center_coord[1] + (base_size * 1.5) + off_e
    lon_w = st.session_state.center_coord[1] - (base_size * 1.5) + off_w
    
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
# Kaart op volledige breedte (100%)
m = folium.Map(location=st.session_state.center_coord, zoom_start=16, control_scale=True)

folium.Polygon(
    locations=CHECK_ZONE_BOX, color="#e74c3c", weight=3, 
    fill=True, fill_color="#e74c3c", fill_opacity=0.2
).add_to(m)

for b in current_bussen:
    color = "#2ecc71" if b["in_zone"] else "#3498db"
    icon_html = f'''
        <div style="display: flex; flex-direction: column; align-items: center; width: 100px;">
            <div style="color: {color}; font-size: 26px; text-shadow: 1px 1px 3px black;">●</div>
            <div style="background: rgba(255,255,255,0.9); border: 1px solid #333; padding: 1px 4px; border-radius: 4px; font-size: 11px; font-weight: bold; color: black;">
                {b['id']} ({b['speed']}k)
            </div>
        </div>
    '''
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=icon_html, icon_size=(100, 50), icon_anchor=(50, 25))).add_to(m)

# Breedte op 1400 (of meer) om horizontaal te vullen
folium_static(m, width=1400, height=850)

# Statusbalken
c1, c2 = st.columns(2)
tz = pytz.timezone('Europe/Brussels')
with c1: st.info(f"🕒 Laatste scan: {datetime.now(tz).strftime('%H:%M:%S')}")
with c2: st.success(f"🚌 Bussen online: {len(current_bussen)}")

time.sleep(30)
st.rerun()
