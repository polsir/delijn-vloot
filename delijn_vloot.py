import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import folium_static

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Analyse", page_icon="🚌")

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

# --- DATA & ANALYSE FUNCTIES ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

if 'counter' not in st.session_state:
    st.session_state.counter = {b_id: 0 for b_id in FLEET}
if 'in_zone_last' not in st.session_state:
    st.session_state.in_zone_last = {b_id: False for b_id in FLEET}

def is_in_box(lat, lon, n, s, e, w):
    """Controleert of de bus binnen de ingestelde vierkante zone valt."""
    return s <= lat <= n and w <= lon <= e

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

# --- SIDEBAR: ZONE INSTELLEN ---
st.sidebar.title("🎯 Zone Instellen")
st.sidebar.info("Pas de coördinaten aan om de controlebox te verplaatsen.")

# Standaardwaarden staan nu rond Bornem Markt
lat_n = st.sidebar.number_input("Noord (Lat)", value=51.0990, format="%.4f")
lat_s = st.sidebar.number_input("Zuid (Lat)", value=51.0965, format="%.4f")
lon_e = st.sidebar.number_input("Oost (Lon)", value=4.2290, format="%.4f")
lon_w = st.sidebar.number_input("West (Lon)", value=4.2240, format="%.4f")

CHECK_ZONE_BOX = [[lat_s, lon_w], [lat_n, lon_w], [lat_n, lon_e], [lat_s, lon_e]]

st.sidebar.divider()
st.sidebar.title("📊 Passages")
for b_id, count in st.session_state.counter.items():
    st.sidebar.write(f"Bus {b_id}: **{count}**")

if st.sidebar.button("Reset Tellers"):
    st.session_state.counter = {b_id: 0 for b_id in FLEET}
    st.rerun()

# --- VERWERKING ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        lat, lon = loc['lat'], loc['lon']
        in_zone = is_in_box(lat, lon, lat_n, lat_s, lon_e, lon_w)
        
        # Detecteer 'Entry event' (als hij van buiten naar binnen komt)
        if in_zone and not st.session_state.in_zone_last[b_id]:
            st.session_state.counter[b_id] += 1
        
        st.session_state.in_zone_last[b_id] = in_zone
        current_bussen.append({"id": b_id, "lat": lat, "lon": lon, "speed": loc.get('speed', 0), "in_zone": in_zone})

# --- UI HOOFDSCHERM ---
st.title("🚌 De Lijn Live Vloot Monitor")

# Kaart (we gebruiken weer folium_static voor stabiliteit)
m = folium.Map(location=[(lat_n+lat_s)/2, (lon_e+lon_w)/2], zoom_start=14)

# Teken de handmatige box
folium.Polygon(
    locations=CHECK_ZONE_BOX, color="red", weight=3, 
    fill=True, fill_color="red", fill_opacity=0.15, tooltip="Jouw Analyse Zone"
).add_to(m)

for b in current_bussen:
    color = "#2ecc71" if b["in_zone"] else "#e67e22"
    icon_html = f'''
        <div style="display: flex; flex-direction: column; align-items: center;">
            <div style="color: {color}; font-size: 24px; text-shadow: 1px 1px 2px black;">●</div>
            <div style="background: white; border: 1px solid black; padding: 1px 3px; border-radius: 3px; font-size: 10px; font-weight: bold; color: black;">
                {b['id']} ({b['speed']}kmu)
            </div>
        </div>
    '''
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=icon_html, icon_size=(100, 40), icon_anchor=(50, 20))).add_to(m)

folium_static(m)

# Statusbalken
c1, c2 = st.columns(2)
tz = pytz.timezone('Europe/Brussels')
with c1:
    st.info(f"🕒 Laatste scan: {datetime.now(tz).strftime('%H:%M:%S')}")
with c2:
    st.success(f"🚌 Bussen online: {len(current_bussen)}")

# Auto-refresh
time.sleep(30)
st.rerun()
