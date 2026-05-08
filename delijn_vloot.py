import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime, timedelta
import pytz
import folium
from streamlit_folium import st_folium, folium_static
from folium.plugins import Draw

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker Pro", page_icon="🚌")

# Verbeterde CSS: Responsive grid voor kaarten en tabs
st.markdown("""
    <style>
        .block-container { padding: 1rem 2rem !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 10px; }
        .stTabs [data-baseweb="tab"] { 
            padding: 8px 16px; 
            background-color: #f0f2f6; 
            border-radius: 5px 5px 0 0;
            font-weight: bold;
        }
        .folium-map { border: 2px solid #3498db; border-radius: 10px; }
        .stat-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .stat-card {
            background-color: #ffffff;
            border-radius: 10px;
            padding: 15px;
            border-top: 4px solid #3498db;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
        }
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

# Dynamische vloot initialisatie
if 'fleet' not in st.session_state:
    st.session_state.fleet = ["302990", "302471", "331406", "645099"]

# Zorg dat alle keys bestaan voor elke bus in de vloot
def init_bus_state(b_id):
    if 'counter' not in st.session_state: st.session_state.counter = {}
    if 'stop_times' not in st.session_state: st.session_state.stop_times = {}
    if 'last_zone_exit' not in st.session_state: st.session_state.last_zone_exit = {}
    if 'last_travel_times' not in st.session_state: st.session_state.last_travel_times = {}
    
    if b_id not in st.session_state.counter: st.session_state.counter[b_id] = 0
    if b_id not in st.session_state.stop_times: st.session_state.stop_times[b_id] = None
    if b_id not in st.session_state.last_zone_exit: st.session_state.last_zone_exit[b_id] = None
    if b_id not in st.session_state.last_travel_times: st.session_state.last_travel_times[b_id] = "-"

for bus in st.session_state.fleet:
    init_bus_state(bus)

if 'history' not in st.session_state: st.session_state.history = {}
if 'drawn_polygon' not in st.session_state: st.session_state.drawn_polygon = None
if 'map_center' not in st.session_state: st.session_state.map_center = [51.0425, 4.3320]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 15

# --- HULPFUNCTIES ---
def get_bus_data(bus_id):
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}&t={int(time.time())}"
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": API_KEY, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data["data"][0] if data.get("data") else None
    except: return None

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

# --- SIDEBAR: BEHEER WATCHLIST ---
with st.sidebar:
    st.header("📋 Watchlist Beheer")
    
    # Bus toevoegen
    new_bus = st.text_input("Nieuw busnummer:", placeholder="bvb. 645092")
    if st.button("➕ Voeg toe aan lijst"):
        if new_bus and new_bus not in st.session_state.fleet:
            st.session_state.fleet.append(new_bus)
            init_bus_state(new_bus)
            st.success(f"Bus {new_bus} toegevoegd!")
            st.rerun()

    # Bus verwijderen
    st.subheader("Huidige Vloot")
    for b_id in st.session_state.fleet:
        cols = st.columns([3, 1])
        cols[0].write(f"Bus {b_id}")
        if cols[1].button("🗑️", key=f"del_{b_id}"):
            st.session_state.fleet.remove(b_id)
            st.rerun()

    st.divider()
    if st.button("🔄 Volledige Reset Stats"):
        for b_id in st.session_state.fleet:
            st.session_state.counter[b_id] = 0
            st.session_state.last_zone_exit[b_id] = None
            st.session_state.last_travel_times[b_id] = "-"
        st.rerun()

# --- DATA VERWERKING ---
current_bussen = []
now_utc = datetime.now(pytz.utc)

for b_id in st.session_state.fleet:
    loc = get_bus_data(b_id)
    if loc:
        curr_lat, curr_lon = loc['lat'], loc['lon']
        speed = loc.get('speed', 0)
        
        # 1. Stilstand
        if speed == 0:
            if st.session_state.stop_times[b_id] is None: st.session_state.stop_times[b_id] = now_utc
            diff = now_utc - st.session_state.stop_times[b_id]
            stop_str = f"{diff.seconds // 60}m {diff.seconds % 60}s"
        else:
            st.session_state.stop_times[b_id] = None
            stop_str = "Rijdt"

        # 2. Zone & Reistijd
        in_zone = is_in_polygon(curr_lat, curr_lon, st.session_state.drawn_polygon)
        was_in_zone = st.session_state.history.get(b_id, {}).get('in_zone', False)
        
        if in_zone and not was_in_zone:
            st.session_state.counter[b_id] += 1
            if st.session_state.last_zone_exit[b_id]:
                t_diff = now_utc - st.session_state.last_zone_exit[b_id]
                st.session_state.last_travel_times[b_id] = f"{t_diff.seconds // 60}m {t_diff.seconds % 60}s"
        
        if was_in_zone and not in_zone:
            st.session_state.last_zone_exit[b_id] = now_utc

        since_zone_str = "Nu in zone" if in_zone else ("-" if not st.session_state.last_zone_exit[b_id] else f"{(now_utc - st.session_state.last_zone_exit[b_id]).seconds // 60}m geleden")

        # 3. Heading / Richting
        heading = None
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            if abs(curr_lat - prev['lat']) + abs(curr_lon - prev['lon']) > 0.00005:
                heading = math.degrees(math.atan2(math.sin(math.radians(curr_lon - prev['lon'])) * math.cos(math.radians(curr_lat)), math.cos(math.radians(prev['lat'])) * math.sin(math.radians(curr_lat)) - math.sin(math.radians(prev['lat'])) * math.cos(math.radians(curr_lat)) * math.cos(math.radians(curr_lon - prev['lon'])))) % 360
            else: heading = prev.get('heading')
        
        st.session_state.history[b_id] = {'lat': curr_lat, 'lon': curr_lon, 'heading': heading, 'in_zone': in_zone}
        current_bussen.append({"id": b_id, "lat": curr_lat, "lon": curr_lon, "speed": speed, "heading": heading, "in_zone": in_zone, "stop_duration": stop_str, "since_zone": since_zone_str})

# --- UI TABS ---
tab1, tab2, tab3 = st.tabs(["📺 Live Monitor", "⚙️ Zone Instellen", "📊 Historiek"])

with tab1:
    m1 = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    if st.session_state.drawn_polygon:
        folium.Polygon(locations=st.session_state.drawn_polygon, color="red", weight=3, fill=True, fill_opacity=0.2).add_to(m1)

    for b in current_bussen:
        color = "#2ecc71" if b["in_zone"] else "#3498db"
        char = "➤" if b['heading'] is not None and b['speed'] > 0 else "●"
        rot = f"transform: rotate({b['heading']-90}deg);" if char == "➤" else ""
        
        label = f'<div style="background:white; border:1px solid {color}; padding:2px 5px; border-radius:4px; font-size:11px; font-weight:bold;">{b["id"]}</div>'
        icon_html = f'<div style="display:flex; flex-direction:column; align-items:center;"><div style="{rot} color:{color}; font-size:24px; text-shadow:1px 1px 2px black;">{char}</div>{label}</div>'
        
        pop = f"Bus {b['id']}<br>Snelheid: {b['speed']} km/u<br>Status: {b['stop_duration']}<br>Sinds zone: {b['since_zone']}"
        folium.Marker([b['lat'], b['lon']], popup=folium.Popup(pop, max_width=200), icon=folium.DivIcon(html=icon_html, icon_size=(150,70), icon_anchor=(75,35))).add_to(m1)

    st_folium(m1, width=1600, height=600, key="live_map")
    
    # DASHBOARD ONDERAAN (Responsive grid)
    st.markdown("### 📊 Vloot Status")
    st.markdown('<div class="stat-grid">', unsafe_allow_html=True)
    for b_id in st.session_state.fleet:
        in_z = st.session_state.history.get(b_id, {}).get('in_zone', False)
        status_c = "#2ecc71" if in_z else "#3498db"
        st.markdown(f"""
            <div class="stat-card" style="border-top-color:{status_c};">
                <b style="font-size:18px;">Bus {b_id}</b><br>
                <span style="font-size:24px; color:#2c3e50;">{st.session_state.counter[b_id]} ritten</span><br>
                <small>Laatste: {st.session_state.last_travel_times[b_id]}</small>
            </div>
        """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.subheader("Teken een zone op de kaart")
    m2 = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    Draw(draw_options={'polyline':False,'circle':False,'marker':False,'circlemarker':False}).add_to(m2)
    out = st_folium(m2, width=1200, height=600, key="setup")
    if out:
        if out.get("last_active_drawing"):
            st.session_state.drawn_polygon = [[p[1], p[0]] for p in out['last_active_drawing']['geometry']['coordinates'][0]]
            st.success("Zone succesvol opgeslagen!")
            st.rerun()

with tab3:
    st.subheader("Data Logboek")
    if current_bussen:
        df = pd.DataFrame(current_bussen)
        st.table(df[['id', 'speed', 'stop_duration', 'since_zone']])
    else:
        st.write("Wachten op data...")

# AUTO-REFRESH
time.sleep(25)
st.rerun()
