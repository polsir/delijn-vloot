import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import st_folium

# --- CONFIGURATIE & BEVEILIGING ---
st.set_page_config(layout="wide", page_title="De Lijn Live Tracker", page_icon="🚌")

def check_password():
    if "auth" not in st.session_state:
        st.session_state.auth = False
    if st.session_state.auth:
        return True
    st.title("🔒 Beveiligde Toegang")
    pwd = st.text_input("Voer het wachtwoord in:", type="password")
    if st.button("Inloggen"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("❌ Verkeerd wachtwoord")
    return False

if not check_password():
    st.stop()

# --- DATA FUNCTIES ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

def get_belgian_time():
    tz = pytz.timezone('Europe/Brussels')
    return datetime.now(tz).strftime('%H:%M:%S')

def calculate_bearing(lat1, lon1, lat2, lon2):
    startLat, startLon = math.radians(lat1), math.radians(lon1)
    endLat, endLon = math.radians(lat2), math.radians(lon2)
    dLon = endLon - startLon
    y = math.sin(dLon) * math.cos(endLat)
    x = math.cos(startLat) * math.sin(endLat) - math.sin(startLat) * math.cos(endLat) * math.cos(dLon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

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

# --- STATE MANAGEMENT (Cruciaal voor Zoom/Positie) ---
if 'history' not in st.session_state:
    st.session_state.history = {}

# Initialiseer kaartpositie als deze nog niet bestaat
if "map_center" not in st.session_state:
    st.session_state.map_center = [51.05, 4.33]
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = 10

# --- UI ---
st.title("🚌 De Lijn Live Vloot Monitor")

refresh_rate = st.sidebar.slider("Verversingssnelheid (sec)", 10, 120, 20)
if st.sidebar.button("Uitloggen"):
    st.session_state.auth = False
    st.rerun()

# Bussen ophalen
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        curr_lat, curr_lon = loc['lat'], loc['lon']
        speed = loc.get('speed', 0)
        heading = None
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            if abs(curr_lat - prev['lat']) + abs(curr_lon - prev['lon']) > 0.00008:
                heading = calculate_bearing(prev['lat'], prev['lon'], curr_lat, curr_lon)
            else:
                heading = prev.get('heading')
        current_bussen.append({"id": b_id, "lat": curr_lat, "lon": curr_lon, "speed": speed, "heading": heading})
        st.session_state.history[b_id] = {"lat": curr_lat, "lon": curr_lon, "heading": heading}

# --- DE KAART ---
# Maak de kaart aan met de bewaarde positie en zoom
m = folium.Map(
    location=st.session_state.map_center, 
    zoom_start=st.session_state.map_zoom,
    control_scale=True
)

for b in current_bussen:
    rot = b['heading'] - 90 if b['heading'] is not None else 0
    icon_html = f'<div style="transform: rotate({rot}deg); color: #e67e22; font-size: 26px; text-shadow: 1px 1px 2px black;">{"➤" if b["heading"] is not None else "●"}</div>'
    
    full_html = f"""
    <div style="display: flex; flex-direction: column; align-items: center; width: 80px;">
        {icon_html}
        <div style="background: #f1c40f; border: 2px solid black; border-radius: 4px; padding: 1px 5px; font-weight: bold; font-size: 10px; color: black; white-space: nowrap; margin-top: -2px;">
            {b['id']} ({b['speed']}kmu)
        </div>
    </div>
    """
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=full_html, icon_size=(80, 80), icon_anchor=(40, 40))).add_to(m)

# Toon de kaart. returned_objects is essentieel om zoom/center terug te krijgen van de gebruiker.
output = st_folium(
    m, 
    width="100%", 
    height=650, 
    key="vloot_kaart",
    returned_objects=["zoom", "center"]
)

# BEWAAR DE POSITIE: Als de gebruiker schuift of zoomt, sla dit op voor de volgende refresh
if output:
    if output.get("center"):
        # We updaten de state alleen als het middelpunt echt anders is om onnodige loops te voorkomen
        new_center = [output["center"]["lat"], output["center"]["lng"]]
        st.session_state.map_center = new_center
    if output.get("zoom"):
        st.session_state.map_zoom = output["zoom"]

# Info balk
c1, c2 = st.columns(2)
with c1:
    st.info(f"🕒 Update (BE): {get_belgian_time()}")
with c2:
    st.success(f"🚌 Actieve bussen: {len(current_bussen)}")

# De automatische refresh
time.sleep(refresh_rate)
st.rerun()
