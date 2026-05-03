import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import st_folium, folium_static
from folium.plugins import Draw

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker Pro", page_icon="🚌")

# CSS voor een schone, schermvullende weergave
st.markdown("""
    <style>
        .block-container { padding: 0rem 1rem !important; max-width: 100% !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 24px; }
        .stTabs [data-baseweb="tab"] { height: 50px; font-weight: bold; }
        .folium-map { margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; }
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
    st.stop()

# --- INITIALISATIE STATE ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

if 'counter' not in st.session_state: st.session_state.counter = {b_id: 0 for b_id in FLEET}
if 'history' not in st.session_state: st.session_state.history = {}
if 'drawn_polygon' not in st.session_state: st.session_state.drawn_polygon = None
if 'map_center' not in st.session_state: st.session_state.map_center = [51.0425, 4.3320]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 15

# --- HELPER FUNCTIES ---
def is_in_polygon(lat, lon, polygon):
    if not polygon: return False
    n = len(polygon); inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if lon > min(p1y, p2y) and lon <= max(p1y, p2y) and lat <= max(p1x, p2x):
            if p1y != p2y: xints = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            if p1x == p2x or lat <= xints: inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def get_bus_data(bus_id):
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}&t={int(time.time())}"
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": API_KEY, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data["data"][0] if data.get("data") else None
    except: return None

# --- DATA VERWERKING ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        curr_lat, curr_lon = loc['lat'], loc['lon']
        speed = loc.get('speed', 0)
        heading = None
        
        # Heading logica op basis van beweging
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            dist = abs(curr_lat - prev['lat']) + abs(curr_lon - prev['lon'])
            if dist > 0.00005: 
                heading = math.degrees(math.atan2(math.sin(math.radians(curr_lon - prev['lon'])) * math.cos(math.radians(curr_lat)), math.cos(math.radians(prev['lat'])) * math.sin(math.radians(curr_lat)) - math.sin(math.radians(prev['lat'])) * math.cos(math.radians(curr_lat)) * math.cos(math.radians(curr_lon - prev['lon'])))) % 360
            else: heading = prev.get('heading')
        
        in_zone = is_in_polygon(curr_lat, curr_lon, st.session_state.drawn_polygon)
        if in_zone and not st.session_state.history.get(b_id, {}).get('in_zone', False):
            st.session_state.counter[b_id] += 1
        
        st.session_state.history[b_id] = {'lat': curr_lat, 'lon': curr_lon, 'heading': heading, 'in_zone': in_zone}
        current_bussen.append({"id": b_id, "lat": curr_lat, "lon": curr_lon, "speed": speed, "heading": heading, "in_zone": in_zone})

# --- UI INDELING ---
tab1, tab2 = st.tabs(["📺 Live Monitor", "⚙️ Zone & Zoom Instellen"])

with st.sidebar:
    st.title("📊 Passages")
    for b_id, count in st.session_state.counter.items():
        st.write(f"Bus {b_id}: **{count}**")
    if st.button("Reset Tellers"):
        st.session_state.counter = {b_id: 0 for b_id in FLEET}; st.rerun()
    st.divider()
    st.write(f"Huidige Zoom: **{st.session_state.map_zoom}**")

# --- TAB 1: DE STABIELE MONITOR (Gebruikt folium_static) ---
with tab1:
    m1 = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom, control_scale=True)
    
    if st.session_state.drawn_polygon:
        folium.Polygon(locations=st.session_state.drawn_polygon, color="red", weight=3, fill=True, fill_opacity=0.2).add_to(m1)

    for b in current_bussen:
        color = "#2ecc71" if b["in_zone"] else "#3498db"
        if b['heading'] is not None and b['speed'] > 0:
            icon_html = f'<div style="transform: rotate({b["heading"]-90}deg); color: {color}; font-size: 26px; text-shadow: 1px 1px 2px black;">➤</div>'
        else:
            icon_html = f'<div style="color: {color}; font-size: 22px; text-shadow: 1px 1px 2px black;">●</div>'
        
        label_html = f'''
            <div style="background: rgba(255,255,255,0.95); border: 1.5px solid {color}; padding: 3px 8px; border-radius: 5px; 
                        font-size: 12px; font-weight: bold; color: black; white-space: nowrap; box-shadow: 2px 2px 5px rgba(0,0,0,0.2);">
                {b["id"]} ({b["speed"]} km/u)
            </div>
        '''
        folium.Marker(
            [b['lat'], b['lon']], 
            icon=folium.DivIcon(
                html=f'<div style="display:flex; flex-direction:column; align-items:center;">{icon_html}{label_html}</div>', 
                icon_size=(150,70), icon_anchor=(75,35)
            )
        ).add_to(m1)

    folium_static(m1, width=1350, height=800)
    tz = pytz.timezone('Europe/Brussels')
    st.info(f"🕒 Update: {datetime.now(tz).strftime('%H:%M:%S')} | 🚌 Actief: {len(current_bussen)}")

# --- TAB 2: SETUP (Gebruikt st_folium voor interactiviteit) ---
with tab2:
    st.subheader("Stel hier je voorkeuren in")
    st.write("1. Zoom en verschuif de kaart naar wens. 2. Teken een zone. 3. Ga terug naar de Monitor.")
    
    m2 = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    Draw(export=False, draw_options={'polyline':False,'circle':False,'marker':False,'circlemarker':False,'polygon':True,'rectangle':True}).add_to(m2)
    
    # Deze component vangt alle wijzigingen op
    out = st_folium(m2, width=1300, height=600, key="setup_map")
    
    if out:
        # Update zoom/center als de gebruiker de kaart beweegt in deze tab
        if out.get("zoom") and out["zoom"] != st.session_state.map_zoom:
            st.session_state.map_zoom = out["zoom"]
        if out.get("center"):
            st.session_state.map_center = [out["center"]["lat"], out["center"]["lng"]]
        
        # Update polygon als er getekend wordt
        if out.get("last_active_drawing"):
            new_poly = out['last_active_drawing']['geometry']['coordinates'][0]
            st.session_state.drawn_polygon = [[p[1], p[0]] for p in new_poly]
            st.success("Configuratie opgeslagen!")

# Automatische verversing (om de 25 seconden)
time.sleep(25)
st.rerun()
