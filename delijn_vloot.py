import streamlit as st
import pandas as pd  # <--- Hier zat de fout, nu hersteld
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw

# --- CONFIGURATIE & STYLING ---
st.set_page_config(layout="wide", page_title="De Lijn Tracker Pro", page_icon="🚌")

st.markdown("""
    <style>
        .main .block-container { padding: 1rem 2rem !important; }
        .folium-map { filter: grayscale(10%) brightness(95%); border-radius: 12px; }
        .update-badge {
            background-color: #2c3e50; color: white; padding: 5px 15px;
            border-radius: 20px; font-weight: bold; font-size: 14px;
            display: inline-block; margin-bottom: 10px;
        }
        .stat-card {
            background-color: white; border-radius: 8px; padding: 12px;
            border-top: 5px solid #3498db; box-shadow: 0 2px 5px rgba(0,0,0,0.08);
            text-align: center; border: 1px solid #eee;
        }
        .stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; margin-top: 15px; }
    </style>
""", unsafe_allow_html=True)

# --- 1. BEVEILIGING VIA SECRETS ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def check_password():
    if not st.session_state.authenticated:
        st.title("🔒 Beveiligd Portaal")
        
        # Haal het wachtwoord op uit de secrets
        # Zorg dat 'APP_PASSWORD' in je Streamlit Secrets of secrets.toml staat!
        try:
            target_password = st.secrets["APP_PASSWORD"]
        except:
            st.error("Wachtwoord niet gevonden in secrets. Voeg 'APP_PASSWORD' toe.")
            st.stop()
            
        password_input = st.text_input("Voer het wachtwoord in:", type="password")
        if st.button("Inloggen"):
            if password_input == target_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Onjuist wachtwoord. Probeer het opnieuw.")
        st.stop()

check_password()

# --- 2. INITIALISATIE ---
API_KEY = st.secrets["DELIJN_API_KEY"]

if 'fleet' not in st.session_state:
    st.session_state.fleet = ["302990", "107460", "331406", "645099"]

def init_bus_state(b_id):
    for key in ['counter', 'stop_times', 'last_zone_exit', 'last_travel_times']:
        if key not in st.session_state: st.session_state[key] = {}
        if b_id not in st.session_state[key]:
            st.session_state[key][b_id] = 0 if key == 'counter' else ("-" if key == 'last_travel_times' else None)

for b in st.session_state.fleet: init_bus_state(b)
if 'history' not in st.session_state: st.session_state.history = {}
if 'drawn_polygon' not in st.session_state: st.session_state.drawn_polygon = None
if 'map_center' not in st.session_state: st.session_state.map_center = [51.02, 4.48]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 10

# --- 3. API FUNCTIES ---
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

# --- 4. ZIJBALK ---
with st.sidebar:
    st.header("📋 Beheer")
    new_bus = st.text_input("Voeg voertuig toe:", placeholder="bvb. 107460")
    if st.button("➕ Toevoegen"):
        if new_bus and new_bus not in st.session_state.fleet:
            st.session_state.fleet.append(new_bus)
            init_bus_state(new_bus); st.rerun()
    
    for b_id in st.session_state.fleet:
        c1, c2 = st.columns([4, 1])
        c1.write(f"🚌 {b_id}")
        if c2.button("🗑️", key=f"del_{b_id}"):
            st.session_state.fleet.remove(b_id); st.rerun()
    
    st.divider()
    if st.button("🚪 Uitloggen"):
        st.session_state.authenticated = False
        st.rerun()

# --- 5. UI TABS ---
tab1, tab2 = st.tabs(["📺 LIVE MONITOR", "⚙️ INSTELLINGEN"])

def create_base_map():
    m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom, tiles='CartoDB positron')
    folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=m,traffic&x={x}&y={y}&z={z}', 
                     attr='Google Traffic', name='Verkeer', overlay=True, opacity=0.6).add_to(m)
    return m

# --- 6. HET FRAGMENT ---
@st.fragment(run_every=25)
def sync_monitor():
    current_bussen = []
    now_local = datetime.now(pytz.timezone('Europe/Brussels'))

    for b_id in st.session_state.fleet:
        loc = get_bus_data(b_id)
        if loc:
            lat, lon, speed = loc['lat'], loc['lon'], loc.get('speed', 0)
            
            if speed < 0.5:
                if st.session_state.stop_times[b_id] is None: st.session_state.stop_times[b_id] = now_local
                stoppage = now_local - st.session_state.stop_times[b_id]
                stop_str = f"{stoppage.seconds // 60}m {stoppage.seconds % 60}s"
            else:
                st.session_state.stop_times[b_id] = None
                stop_str = "Rijdt"

            in_z = is_in_polygon(lat, lon, st.session_state.drawn_polygon)
            was_in = st.session_state.history.get(b_id, {}).get('in_zone', False)
            
            if in_z and not was_in:
                st.session_state.counter[b_id] += 1
                if st.session_state.last_zone_exit[b_id]:
                    diff = now_local - st.session_state.last_zone_exit[b_id]
                    st.session_state.last_travel_times[b_id] = f"{diff.seconds // 60}m {diff.seconds % 60}s"
            
            if was_in and not in_z: st.session_state.last_zone_exit[b_id] = now_local
            since_zone = "-" if not st.session_state.last_zone_exit[b_id] else f"{(now_local - st.session_state.last_zone_exit[b_id]).seconds // 60}m"
            if in_z: since_zone = "In zone"

            head = st.session_state.history.get(b_id, {}).get('heading')
            if b_id in st.session_state.history:
                prev = st.session_state.history[b_id]
                if abs(lat - prev['lat']) + abs(lon - prev['lon']) > 0.00005:
                    head = math.degrees(math.atan2(math.sin(math.radians(lon - prev['lon'])) * math.cos(math.radians(lat)), math.cos(math.radians(prev['lat'])) * math.sin(math.radians(lat)) - math.sin(math.radians(prev['lat'])) * math.cos(math.radians(lat)) * math.cos(math.radians(lon - prev['lon'])))) % 360
            
            st.session_state.history[b_id] = {'lat': lat, 'lon': lon, 'heading': head, 'in_zone': in_z}
            current_bussen.append({"id": b_id, "lat": lat, "lon": lon, "speed": speed, "heading": head, "in_zone": in_z, "stop_duration": stop_str, "since_zone": since_zone})

    with tab1:
        st.markdown(f'<div class="update-badge">⏱️ Laatste update: {now_local.strftime("%H:%M:%S")}</div>', unsafe_allow_html=True)
        m1 = create_base_map()
        
        if st.session_state.drawn_polygon:
            folium.Polygon(locations=st.session_state.drawn_polygon, color="#e74c3c", weight=3, fill=True, fill_opacity=0.1).add_to(m1)
        
        for b in current_bussen:
            color = "#2ecc71" if b["in_zone"] else "#3498db"
            char = "➤" if b['speed'] >= 0.5 and b['heading'] is not None else "●"
            rot = f"transform: rotate({b['heading']-90}deg);" if char == "➤" else ""
            
            icon_html = f'''
                <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; width:100px; height:100px;">
                    <div style="{rot} color:{color}; font-size:32px; text-shadow:2px 2px 4px rgba(0,0,0,0.4); line-height:1;">{char}</div>
                    <div style="background:white; border:2px solid {color}; padding:2px 6px; border-radius:5px; font-size:12px; font-weight:bold; color:#333; margin-top:2px; box-shadow:0 2px 4px rgba(0,0,0,0.2);">{b["id"]}</div>
                </div>'''
            
            popup_html = f"<b>Voertuig {b['id']}</b><br><hr>🚀 {b['speed']} km/u<br>🛑 Stilstand: {b['stop_duration']}<br>📍 Buiten zone: {b['since_zone']}"
            folium.Marker([b['lat'], b['lon']], popup=folium.Popup(popup_html, max_width=200), icon=folium.DivIcon(html=icon_html, icon_size=(100,100), icon_anchor=(50,50))).add_to(m1)

        st_folium(m1, width=1600, height=700, key="live_map", returned_objects=[])
        
        st.markdown('<div class="stat-grid">', unsafe_allow_html=True)
        for b_id in st.session_state.fleet:
            in_z = st.session_state.history.get(b_id, {}).get('in_zone', False)
            st.markdown(f'<div class="stat-card" style="border-top-color:{"#2ecc71" if in_z else "#3498db"};"><b>{b_id}</b><br><span style="font-size:24px;">{st.session_state.counter[b_id]} ritten</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

sync_monitor()

with tab2:
    st.info("💡 Stel hier de standaard weergave en zone in.")
    m2 = create_base_map()
    Draw(draw_options={'polyline':False,'circle':False,'marker':False,'circlemarker':False}).add_to(m2)
    out_setup = st_folium(m2, width=1200, height=600, key="setup")
    
    if st.button("💾 Sla Positie & Zone op"):
        if out_setup:
            if out_setup.get("zoom"): st.session_state.map_zoom = out_setup["zoom"]
            if out_setup.get("center"): st.session_state.map_center = [out_setup["center"]["lat"], out_setup["center"]["lng"]]
            if out_setup.get("last_active_drawing"):
                st.session_state.drawn_polygon = [[p[1], p[0]] for p in out_setup['last_active_drawing']['geometry']['coordinates'][0]]
            st.success("Opgeslagen!"); st.rerun()
