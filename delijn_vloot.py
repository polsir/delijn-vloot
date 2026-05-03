import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import st_folium

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Live Tracker", page_icon="🚌")

# --- BEVEILIGING ---
def check_password():
    if "auth" not in st.session_state:
        st.session_state.auth = False
    if st.session_state.auth: return True
    st.title("🔒 Beveiligde Toegang")
    pwd = st.text_input("Wachtwoord:", type="password")
    if st.button("Inloggen"):
        if pwd == st.secrets["APP_PASSWORD"]:
            st.session_state.auth = True
            st.rerun()
        else: st.error("❌ Verkeerd")
    return False

if not check_password(): st.stop()

# --- DATA ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

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

# --- STATE MANAGEMENT ---
if 'history' not in st.session_state: st.session_state.history = {}

# BELANGRIJK: We zetten vaste startwaarden als er nog niets in het geheugen zit
if "map_center" not in st.session_state:
    st.session_state.map_center = [51.05, 4.33]
if "map_zoom" not in st.session_state:
    st.session_state.map_zoom = 10

# --- DATA VERWERKEN ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        curr_lat, curr_lon = loc['lat'], loc['lon']
        heading = None
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            if abs(curr_lat - prev['lat']) + abs(curr_lon - prev['lon']) > 0.00008:
                heading = math.degrees(math.atan2(math.sin(math.radians(curr_lon - prev['lon'])) * math.cos(math.radians(curr_lat)), math.cos(math.radians(prev['lat'])) * math.sin(math.radians(curr_lat)) - math.sin(math.radians(prev['lat'])) * math.cos(math.radians(curr_lat)) * math.cos(math.radians(curr_lon - prev['lon'])))) % 360
            else: heading = prev.get('heading')
        current_bussen.append({"id": b_id, "lat": curr_lat, "lon": curr_lon, "speed": loc.get('speed', 0), "heading": heading})
        st.session_state.history[b_id] = {"lat": curr_lat, "lon": curr_lon, "heading": heading}

# --- DE KAART ---
st.title("🚌 De Lijn Live Vloot Monitor")

# We maken de kaart exact op de plek waar de gebruiker gestopt is
m = folium.Map(
    location=st.session_state.map_center, 
    zoom_start=st.session_state.map_zoom,
    tiles="OpenStreetMap"
)

for b in current_bussen:
    rot = b['heading'] - 90 if b['heading'] is not None else 0
    icon_html = f'<div style="transform: rotate({rot}deg); color: #e67e22; font-size: 26px; text-shadow: 1px 1px 2px black;">{"➤" if b["heading"] is not None else "●"}</div>'
    full_html = f'<div style="display: flex; flex-direction: column; align-items: center; width: 80px;">{icon_html}<div style="background: #f1c40f; border: 2px solid black; border-radius: 4px; padding: 1px 5px; font-weight: bold; font-size: 10px; color: black; white-space: nowrap; margin-top: -2px;">{b["id"]} ({b["speed"]}kmu)</div></div>'
    folium.Marker([b['lat'], b['lon']], icon=folium.DivIcon(html=full_html, icon_size=(80, 80), icon_anchor=(40, 40))).add_to(m)

# De st_folium aanroep met beperkte terugkoppeling om lussen te voorkomen
output = st_folium(
    m,
    width=1400,
    height=600,
    key="vloot_kaart",
    returned_objects=["zoom", "center"]
)

# CRUCIAAL: Update de status alleen als de gebruiker de kaart echt heeft bewogen
if output:
    if output.get("zoom"):
        st.session_state.map_zoom = output["zoom"]
    if output.get("center"):
        # We vergelijken op 4 decimalen om afrondingsverschillen van de server te negeren
        new_lat = round(output["center"]["lat"], 4)
        new_lon = round(output["center"]["lng"], 4)
        if [new_lat, new_lon] != [round(st.session_state.map_center[0], 4), round(st.session_state.map_center[1], 4)]:
            st.session_state.map_center = [output["center"]["lat"], output["center"]["lng"]]

# Info & Refresh
tz = pytz.timezone('Europe/Brussels')
st.info(f"🕒 Update: {datetime.now(tz).strftime('%H:%M:%S')} | 🚌 Actief: {len(current_bussen)}")

# Sidebar voor handmatige controle
st.sidebar.write(f"Huidige Zoom: {st.session_state.map_zoom}")
if st.sidebar.button("Reset naar overzicht"):
    st.session_state.map_center = [51.05, 4.33]
    st.session_state.map_zoom = 10
    st.rerun()

# 30 seconden wachten tussen refreshes geeft meer rust
time.sleep(30)
st.rerun()
