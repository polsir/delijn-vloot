import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import folium_static

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker", page_icon="🚌")

# Verbeterde styling voor maximale breedte zonder de boel te breken
st.markdown("""
    <style>
        .main .block-container { max-width: 95%; padding-top: 1rem; }
        iframe { width: 100% !important; height: 75vh !important; }
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

# --- DATA & ANALYSE ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

if 'counter' not in st.session_state:
    st.session_state.counter = {b_id: 0 for b_id in FLEET}
if 'in_zone_last' not in st.session_state:
    st.session_state.in_zone_last = {b_id: False for b_id in FLEET}

def is_in_polygon(lat, lon, polygon):
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

# --- ZONE DEFINITIE (Bornem Markt voorbeeld) ---
CHECK_ZONE = [
    [51.0965, 4.2240], [51.0990, 4.2240], [51.0990, 4.2290], [51.0965, 4.2290]
]

# --- VERWERKING ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        lat, lon = loc['lat'], loc['lon']
        in_zone = is_in_polygon(lat, lon, CHECK_ZONE)
        
        # Alleen tellen als de bus de zone BINNENRIJDT (niet als hij er al in stond)
        if in_zone and not st.session_state.in_zone_last[b_id]:
            st.session_state.counter[b_id] += 1
        
        st.session_state.in_zone_last[b_id] = in_zone
        current_bussen.append({"id": b_id, "lat": lat, "lon": lon, "speed": loc.get('speed', 0), "in_zone": in_zone})

# --- UI ---
st.title("🚌 De Lijn Live Vloot Monitor")

# Sidebar Statistieken
st.sidebar.title("📊 Passages in Zone")
for b_id, count in st.session_state.counter.items():
    st.sidebar.write(f"Bus {b_id}: **{count}**")
if st.sidebar.button("Reset Tellers"):
    st.session_state.counter = {b_id: 0 for b_id in FLEET}
    st.rerun()

# Kaart
m = folium.Map(location=[51.08, 4.25], zoom_start=12)

folium.Polygon(
    locations=CHECK_ZONE, color="red", weight=2, 
    fill=True, fill_color="red", fill_opacity=0.1, tooltip="Analyse Zone"
).add_to(m)

for b in current_bussen:
    color = "#2ecc71" if b["in_zone"] else "#e67e22"
    icon_html = f'''
        <div style="display: flex; flex-direction: column; align-items: center;">
            <div style="color: {color}; font-size: 24px; text-shadow: 1px 1px 2px black;">●</div>
            <div style="background: white; border: 1px solid black; padding: 1px 3px; border-radius: 3px; font-size: 10px; font-weight: bold; white-space: nowrap;">
                {b['id']} ({b['speed']}kmu)
            </div>
        </div>
    '''
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=icon_html, icon_size=(100, 40), icon_anchor=(50, 20))).add_to(m)

# Toon Kaart
folium_static(m)

# Statusbalken (Teruggezet!)
c1, c2 = st.columns(2)
tz = pytz.timezone('Europe/Brussels')
with c1:
    st.info(f"🕒 Laatste scan: {datetime.now(tz).strftime('%H:%M:%S')}")
with c2:
    st.success(f"🚌 Bussen online: {len(current_bussen)}")

# Auto-refresh
time.sleep(30)
st.rerun()
