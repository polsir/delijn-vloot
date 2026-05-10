import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time, os
from datetime import datetime, timedelta
import pytz
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker Pro", page_icon="🚌")

# CSS voor de knoppen en layout
st.markdown("""
    <style>
        .main .block-container { padding: 1rem 2rem !important; }
        button[data-baseweb="tab"] {
            font-size: 16px !important; font-weight: bold !important;
            color: #31333F !important; background-color: #f0f2f6 !important;
            border-radius: 8px 8px 0px 0px !important; padding: 10px 20px !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #3498db !important; color: white !important;
        }
        .stat-grid {
            display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px; margin-top: 15px;
        }
        .stat-card {
            background-color: white; border-radius: 8px; padding: 12px;
            border-top: 4px solid #3498db; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            text-align: center; border: 1px solid #eee;
        }
    </style>
""", unsafe_allow_html=True)

# --- INITIALISATIE ---
API_KEY = st.secrets["DELIJN_API_KEY"]

if 'fleet' not in st.session_state:
    st.session_state.fleet = ["302990", "302471", "331406", "645099"]

def init_bus_state(b_id):
    for key in ['counter', 'stop_times', 'last_zone_exit', 'last_travel_times']:
        if key not in st.session_state: st.session_state[key] = {}
        if b_id not in st.session_state[key]:
            st.session_state[key][b_id] = 0 if key == 'counter' else ("-" if key == 'last_travel_times' else None)

for b in st.session_state.fleet: init_bus_state(b)

if 'history' not in st.session_state: st.session_state.history = {}
if 'drawn_polygon' not in st.session_state: st.session_state.drawn_polygon = None
# Standaard view iets verder uitgezoomd (zoom 11)
if 'map_center' not in st.session_state: st.session_state.map_center = [51.0425, 4.3320]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 11

# --- API & LOGICA ---
def get_bus_data(bus_id):
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}&t={int(time.time())}"
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": API_KEY, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data["data"][0] if data.get("data") else None
    except: return None

def is_in_polygon(lat, lon, poly):
    if not poly: return False
    n = len(poly); inside = False
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if lon > min(p1y, p2y) and lon <= max(p1y, p2y) and lat <= max(p1x, p2x):
            if p1y != p2y: xints = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            if p1x == p2x or lat <= xints: inside = not inside
        p1x, p1y = p2x, p2y
    return inside

# --- SIDEBAR ---
with st.sidebar:
    st.header("📋 Watchlist")
    new_bus = st.text_input("Nieuwe bus:", placeholder="bvb. 645092")
    if st.button("➕ Toevoegen"):
        if new_bus and new_bus not in st.session_state.fleet:
            st.session_state.fleet.append(new_bus)
            init_bus_state(new_bus)
            st.rerun()
    for b_id in st.session_state.fleet:
        c1, c2 = st.columns([4, 1])
        c1.write(f"🚌 {b_id}")
        if c2.button("🗑️", key=f"del_{b_id}"):
            st.session_state.fleet.remove(b_id)
            st.rerun()

# --- DATA VERWERKING ---
current_bussen = []
now_utc = datetime.now(pytz.utc)

for b_id in st.session_state.fleet:
    loc = get_bus_data(b_id)
    if loc:
        lat, lon, speed = loc['lat'], loc['lon'], loc.get('speed', 0)
        
        # Stilstand check
        if speed == 0:
            if st.session_state.stop_times[b_id] is None: st.session_state.stop_times[b_id] = now_utc
            stoppage = now_utc - st.session_state.stop_times[b_id]
            stop_str = f"{stoppage.seconds // 60}m {stoppage.seconds % 60}s"
        else:
            st.session_state.stop_times[b_id] = None
            stop_str = "Rijdt"

        in_z = is_in_polygon(lat, lon, st.session_state.drawn_polygon)
        was_in = st.session_state.history.get(b_id, {}).get('in_zone', False)
        
        if in_z and not was_in:
            st.session_state.counter[b_id] += 1
            if st.session_state.last_zone_exit[b_id]:
                diff = now_utc - st.session_state.last_zone_exit[b_id]
                st.session_state.last_travel_times[b_id] = f"{diff.seconds // 60}m {diff.seconds % 60}s"
        if was_in and not in_z: 
            st.session_state.last_zone_exit[b_id] = now_utc

        since_zone = "-" if not st.session_state.last_zone_exit[b_id] else f"{(now_utc - st.session_state.last_zone_exit[b_id]).seconds // 60}m"
        if in_z: since_zone = "In zone"

        head = st.session_state.history.get(b_id, {}).get('heading')
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            if abs(lat - prev['lat']) + abs(lon - prev['lon']) > 0.00005:
                head = math.degrees(math.atan2(math.sin(math.radians(lon - prev['lon'])) * math.cos(math.radians(lat)), math.cos(math.radians(prev['lat'])) * math.sin(math.radians(lat)) - math.sin(math.radians(prev['lat'])) * math.cos(math.radians(lat)) * math.cos(math.radians(lon - prev['lon'])))) % 360
        
        st.session_state.history[b_id] = {'lat': lat, 'lon': lon, 'heading': head, 'in_zone': in_z}
        current_bussen.append({
            "id": b_id, "lat": lat, "lon": lon, "speed": speed, 
            "heading": head, "in_zone": in_z, "stop_duration": stop_str, "since_zone": since_zone
        })

# --- UI TABS ---
tab1, tab2, tab3 = st.tabs(["📺 LIVE MONITOR", "⚙️ ZONE INSTELLEN", "📊 HISTORIEK"])

def create_map(is_setup=False):
    # Grijze basiskaart
    m = folium.Map(
        location=st.session_state.map_center, 
        zoom_start=st.session_state.map_zoom,
        tiles='CartoDB positron'
    )
    # Real-time Verkeer laag
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=m,traffic&x={x}&y={y}&z={z}',
        attr='Google Traffic',
        name='Verkeersdrukte',
        overlay=True,
        control=True
    ).add_to(m)
    return m

with tab1:
    m1 = create_map()
    if st.session_state.drawn_polygon:
        folium.Polygon(locations=st.session_state.drawn_polygon, color="red", weight=2, fill=True, fill_opacity=0.1).add_to(m1)
    
    for b in current_bussen:
        color = "#2ecc71" if b["in_zone"] else "#3498db"
        char = "➤" if b['heading'] is not None and b['speed'] > 0 else "●"
        rot = f"transform: rotate({b['heading']-90}deg);" if char == "➤" else ""
        
        # Anchor optimalisatie om 'zweven' te voorkomen
        icon_html = f'''
            <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; width:100px; height:100px;">
                <div style="{rot} color:{color}; font-size:28px; text-shadow:1px 1px 3px rgba(0,0,0,0.5); line-height:1;">{char}</div>
                <div style="background:white; border:2px solid {color}; padding:1px 5px; border-radius:4px; font-size:11px; font-weight:bold; white-space:nowrap; margin-top:2px;">
                    {b["id"]} ({b["speed"]} km/u)
                </div>
            </div>'''
        
        popup_content = f"""
            <div style="font-family: sans-serif; font-size: 13px;">
                <b>Bus {b['id']}</b><hr style="margin:5px 0;">
                🚀 <b>Snelheid:</b> {b['speed']} km/u<br>
                🛑 <b>Stilstand:</b> {b['stop_duration']}<br>
                📍 <b>Weg uit zone:</b> {b['since_zone']}
            </div>
        """
        
        folium.Marker(
            [b['lat'], b['lon']], 
            popup=folium.Popup(popup_content, max_width=200),
            icon=folium.DivIcon(
                html=icon_html, 
                icon_size=(100,100), 
                icon_anchor=(50,50) # Exact in het midden van het icoon-vlak
            )
        ).add_to(m1)

    # De monitor geeft nu ook zoom en center terug om te onthouden
    out_map = st_folium(m1, width=1600, height=650, key="live_map", returned_objects=["zoom", "center"])
    
    if out_map:
        if out_map.get("zoom"): st.session_state.map_zoom = out_map["zoom"]
        if out_map.get("center"): st.session_state.map_center = [out_map["center"]["lat"], out_map["center"]["lng"]]
    
    st.markdown('<div class="stat-grid">', unsafe_allow_html=True)
    for b_id in st.session_state.fleet:
        in_z = st.session_state.history.get(b_id, {}).get('in_zone', False)
        st.markdown(f'<div class="stat-card" style="border-top-color:{"#2ecc71" if in_z else "#3498db"};"><b>Bus {b_id}</b><br><span style="font-size:22px;">{st.session_state.counter[b_id]} ritten</span><br><small>Reistijd: {st.session_state.last_travel_times[b_id]}</small></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.info("Bepaal hier de meet-zone en de standaard kaartweergave.")
    m2 = create_map()
    Draw(draw_options={'polyline':False,'circle':False,'marker':False,'circlemarker':False}).add_to(m2)
    
    out_setup = st_folium(m2, width=1200, height=600, key="setup")
    if out_setup:
        if out_setup.get("zoom"): st.session_state.map_zoom = out_setup["zoom"]
        if out_setup.get("center"): st.session_state.map_center = [out_setup["center"]["lat"], out_setup["center"]["lng"]]
        if out_setup.get("last_active_drawing"):
            st.session_state.drawn_polygon = [[p[1], p[0]] for p in out_setup['last_active_drawing']['geometry']['coordinates'][0]]
            st.success("Configuratie opgeslagen!"); st.rerun()

with tab3:
    st.dataframe(pd.DataFrame(current_bussen)[['id', 'speed', 'stop_duration', 'since_zone']], use_container_width=True)

time.sleep(25)
st.rerun()
