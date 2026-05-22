import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time, re
from datetime import datetime, timedelta
import pytz
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from extra_streamlit_components import CookieManager

# --- 1. CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="Bus Tracker Pro", page_icon="🚌")
cookie_manager = CookieManager()

st.markdown("""
    <style>
        .main .block-container { padding: 1rem 2rem !important; }
        @media (max-width: 768px) { .main .block-container { padding: 0.5rem !important; } }
        .folium-map { border-radius: 12px; border: 1px solid #ddd; }
        .update-badge {
            background-color: #2c3e50; color: white; padding: 6px 16px;
            border-radius: 20px; font-weight: bold; font-size: 14px;
            display: inline-block; margin-bottom: 12px;
        }
        #MainMenu {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# --- 2. AUTHENTICATIE (Instant Bridge) ---
def check_auth():
    if st.session_state.get('authenticated'): return True
    auth_cookie = cookie_manager.get("auth_token")
    target_pw = st.secrets["APP_PASSWORD"]
    
    if auth_cookie == target_pw:
        st.session_state.authenticated = True
        return True
    
    st.title("🔒 Login")
    pw_input = st.text_input("Wachtwoord:", type="password")
    if st.button("Inloggen"):
        if pw_input == target_pw:
            cookie_manager.set("auth_token", target_pw, expires_at=datetime.now() + timedelta(days=30))
            st.session_state.authenticated = True
            st.rerun()
        else: st.error("Onjuist.")
    st.stop()

check_auth()

# --- 3. INITIALISATIE ---
API_KEY = st.secrets["DELIJN_API_KEY"]

# Standaard vloot aangepast voor het nieuwe project
if 'fleet' not in st.session_state: 
    st.session_state.fleet = ["441521", "401282", "442204", "616045", "642050", "441518", "442068", "610087", "610088", "616038", "616042", "616044", "441814", "611066"]

def init_bus_state(b_id):
    for key in ['counter', 'stop_times', 'last_zone_exit']:
        if key not in st.session_state: st.session_state[key] = {}
        if b_id not in st.session_state[key]:
            st.session_state[key][b_id] = 0 if key == 'counter' else None

for b in st.session_state.fleet: init_bus_state(b)
if 'history' not in st.session_state: st.session_state.history = {}
if 'drawn_polygon' not in st.session_state: st.session_state.drawn_polygon = None

# Startlocatie aangepast naar Houthalen-Helchteren
if 'map_center' not in st.session_state: st.session_state.map_center = [51.0315, 5.3741]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 13

def get_bus_data(bus_id):
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}&t={int(time.time())}"
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": API_KEY})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            data = json.loads(r.read().decode()); return data["data"][0] if data.get("data") else None
    except: return None

def is_in_polygon(lat, lon, poly):
    if not poly: return False
    n = len(poly); inside = False; p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if lon > min(p1y, p2y) and lon <= max(p1y, p2y) and lat <= max(p1x, p2x):
            if p1y != p2y: xints = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            if p1x == p2x or lat <= xints: inside = not inside
        p1x, p1y = p2x, p2y
    return inside

# --- 4. ZIJBALK ---
with st.sidebar:
    st.header("📋 Vloot")
    new_ids = st.text_input("Voeg toe (bvb 205310; 207310)")
    if st.button("➕ Toevoegen"):
        if new_ids:
            for b_id in re.split(r'[;,]+', new_ids):
                clean = b_id.strip()
                if clean and clean not in st.session_state.fleet:
                    st.session_state.fleet.append(clean); init_bus_state(clean)
            st.rerun()
    st.divider()
    for b_id in st.session_state.fleet:
        c1, c2 = st.columns([4, 1])
        c1.write(f"🚌 {b_id}")
        if c2.button("🗑️", key=f"del_{b_id}"): st.session_state.fleet.remove(b_id); st.rerun()
    st.divider()
    if st.button("🚪 Uitloggen"):
        cookie_manager.delete("auth_token")
        st.session_state.authenticated = False
        st.rerun()

# --- 5. TABS ---
tab1, tab2 = st.tabs(["📺 LIVE MONITOR", "⚙️ CONFIG"])

with tab1:
    map_box = st.empty()
    stats_box = st.empty()

    @st.fragment(run_every=25)
    def update_view():
        now = datetime.now(pytz.timezone('Europe/Brussels'))
        m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom, tiles='CartoDB positron')
        folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=m,traffic&x={x}&y={y}&z={z}', 
                         attr='Google', name='Verkeer', overlay=True, opacity=0.5).add_to(m)
        
        if st.session_state.drawn_polygon:
            folium.Polygon(locations=st.session_state.drawn_polygon, color="red", weight=2, fill=True, fill_opacity=0.1).add_to(m)

        for b_id in st.session_state.fleet:
            loc = get_bus_data(b_id)
            if loc:
                lat = loc['lat']
                lon = loc['lon']
                speed = float(loc.get('speed') or 0) 
                
                in_z = is_in_polygon(lat, lon, st.session_state.drawn_polygon)
                was_in = st.session_state.history.get(b_id, {}).get('in_zone', False)
                
                # Ritten & Stilstand Logica
                if in_z and not was_in: st.session_state.counter[b_id] += 1
                if was_in and not in_z: st.session_state.last_zone_exit[b_id] = now
                
                if speed < 0.5:
                    if st.session_state.stop_times[b_id] is None: st.session_state.stop_times[b_id] = now
                    stoppage = now - st.session_state.stop_times[b_id]
                    stop_str = f"{stoppage.seconds // 60}m {stoppage.seconds % 60}s"
                else:
                    st.session_state.stop_times[b_id] = None
                    stop_str = "Rijdt"

                # Heading berekening voor pijltje
                heading = 0
                if b_id in st.session_state.history:
                    prev = st.session_state.history[b_id]
                    if abs(lat - prev['lat']) + abs(lon - prev['lon']) > 0.00001:
                        heading = math.degrees(math.atan2(lon - prev['lon'], lat - prev['lat'])) % 360

                st.session_state.history[b_id] = {'lat': lat, 'lon': lon, 'in_zone': in_z, 'heading': heading}
                since_z = "-" if not st.session_state.last_zone_exit[b_id] else f"{(now - st.session_state.last_zone_exit[b_id]).seconds // 60}m"
                if in_z: since_z = "In zone"

                # --- MARKER STYLING ---
                color = "#2ecc71" if in_z else "#3498db"
                char = "➤" if speed >= 0.5 else "●"
                rotation = f"transform: rotate({heading-90}deg);" if char == "➤" else ""
                
                icon_html = f'''
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; width: 60px; height: 60px;">
                    <div style="background: white; border: 2px solid {color}; border-radius: 4px; padding: 2px 6px; 
                                font-family: sans-serif; font-size: 11px; font-weight: bold; color: black; 
                                box-shadow: 0 2px 4px rgba(0,0,0,0.3); margin-bottom: 2px; white-space: nowrap;">
                        {b_id}
                    </div>
                    <div style="{rotation} color: {color}; font-size: 28px; line-height: 1; text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">
                        {char}
                    </div>
                </div>
                '''
                
                popup_html = f"<b>Bus {b_id}</b><br><hr>Snelheid: {speed} km/u<br>Stil: {stop_str}<br>Zone: {since_z}<br>Ritten: {st.session_state.counter[b_id]}"
                
                folium.Marker(
                    [lat, lon], 
                    popup=folium.Popup(popup_html, max_width=200),
                    icon=folium.DivIcon(html=icon_html, icon_size=(60, 60), icon_anchor=(30, 45))
                ).add_to(m)

        with map_box.container():
            st.markdown(f'<div class="update-badge">⏱️ Laatste update: {now.strftime("%H:%M:%S")}</div>', unsafe_allow_html=True)
            st_folium(m, width="100%", height=600, key="map_v1611", returned_objects=[])

        with stats_box.container():
            cols = st.columns(min(len(st.session_state.fleet), 6))
            for i, b_id in enumerate(st.session_state.fleet):
                with cols[i % 6]: st.metric(label=f"Bus {b_id}", value=f"{st.session_state.counter[b_id]}x")

    update_view()

with tab2:
    st.header("⚙️ Configuratie")
    m2 = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    Draw(draw_options={'polyline':False,'circle':False,'marker':False,'circlemarker':False}).add_to(m2)
    out = st_folium(m2, width="100%", height=500, key="cfg_v1611")
    if st.button("💾 Opslaan"):
        if out:
            if out.get("last_active_drawing"):
                st.session_state.drawn_polygon = [[p[1], p[0]] for p in out['last_active_drawing']['geometry']['coordinates'][0]]
            st.session_state.map_center = [out["center"]["lat"], out["center"]["lng"]]
            st.session_state.map_zoom = out["zoom"]
            st.success("Opgeslagen!"); st.rerun()
