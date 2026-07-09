import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time, re, os
from datetime import datetime, timedelta
import pytz
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw
from extra_streamlit_components import CookieManager
import concurrent.futures

# --- 1. CONFIGURATIE & OPSLAG ---
st.set_page_config(layout="wide", page_title="Bus Tracker Pro", page_icon="🚌")
cookie_manager = CookieManager()
CONFIG_FILE = "delijn_config.json"

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

# Configuratie Inladen & Opslaan Functies (Antwoord op Slaapstand Probleem)
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: return json.load(f)
        except: pass
    return None

def save_config():
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "fleet": st.session_state.fleet,
            "map_center": st.session_state.map_center,
            "map_zoom": st.session_state.map_zoom,
            "drawn_polygon": st.session_state.drawn_polygon
        }, f)

# --- 2. AUTHENTICATIE ---
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

# --- 3. INITIALISATIE MET PERSISTENCE ---
API_KEY = st.secrets["DELIJN_API_KEY"]
saved_cfg = load_config()

if 'fleet' not in st.session_state: 
    st.session_state.fleet = saved_cfg.get("fleet", ["221324", "221325", "304806", "304802", "304801", "502605"]) if saved_cfg else ["221324", "221325", "304806", "304802", "304801", "502605"]
if 'map_center' not in st.session_state: 
    st.session_state.map_center = saved_cfg.get("map_center", [51.0760, 4.2780]) if saved_cfg else [51.0760, 4.2780]
if 'map_zoom' not in st.session_state: 
    st.session_state.map_zoom = saved_cfg.get("map_zoom", 14) if saved_cfg else 14
if 'drawn_polygon' not in st.session_state:
    st.session_state.drawn_polygon = saved_cfg.get("drawn_polygon") if saved_cfg else None

def init_bus_state(b_id):
    # Nieuwe variabelen: last_trip_duration & zone_entry_time toegevoegd
    for key in ['counter', 'stop_times', 'last_zone_exit', 'last_trip_duration', 'zone_entry_time']:
        if key not in st.session_state: st.session_state[key] = {}
        if b_id not in st.session_state[key]:
            st.session_state[key][b_id] = 0 if key == 'counter' else None

for b in st.session_state.fleet: init_bus_state(b)
if 'history' not in st.session_state: st.session_state.history = {}

def get_bus_data(bus_id):
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}&t={int(time.time())}"
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"Ocp-Apim-Subscription-Key": API_KEY})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=3) as r:
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
            for b_id in re.split(r'[;, ]+', new_ids):
                clean = b_id.strip()
                if clean and clean not in st.session_state.fleet:
                    st.session_state.fleet.append(clean); init_bus_state(clean)
            save_config()
            st.rerun()
    st.divider()
    
    if st.button("🗑️ Wis hele vloot"):
        st.session_state.fleet = []
        save_config()
        st.rerun()
        
    for b_id in st.session_state.fleet:
        c1, c2 = st.columns([4, 1])
        c1.write(f"🚌 {b_id}")
        if c2.button("🗑️", key=f"del_{b_id}"): 
            st.session_state.fleet.remove(b_id)
            save_config()
            st.rerun()
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

        bus_data_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            future_to_bus = {executor.submit(get_bus_data, b_id): b_id for b_id in st.session_state.fleet}
            for future in concurrent.futures.as_completed(future_to_bus):
                b_id = future_to_bus[future]
                try: bus_data_results[b_id] = future.result()
                except: bus_data_results[b_id] = None

        for b_id in st.session_state.fleet:
            loc = bus_data_results.get(b_id)
            if loc:
                lat, lon = loc['lat'], loc['lon']
                speed = float(loc.get('speed') or 0) 
                in_z = is_in_polygon(lat, lon, st.session_state.drawn_polygon)
                was_in = st.session_state.history.get(b_id, {}).get('in_zone', False)
                
                # --- NIEUW: Rittijd (Heen en terug) Logica ---
                if in_z and not was_in: 
                    st.session_state.counter[b_id] += 1
                    # Bus komt binnen: meet hoe lang hij weg was
                    if st.session_state.last_zone_exit[b_id]:
                        duration = now - st.session_state.last_zone_exit[b_id]
                        st.session_state.last_trip_duration[b_id] = f"{duration.seconds // 60}m {duration.seconds % 60}s"
                    st.session_state.zone_entry_time[b_id] = now
                    
                if was_in and not in_z: 
                    # Bus vertrekt uit zone
                    st.session_state.last_zone_exit[b_id] = now
                    st.session_state.zone_entry_time[b_id] = None
                
                # Stilstand check
                if speed < 0.5:
                    if st.session_state.stop_times[b_id] is None: st.session_state.stop_times[b_id] = now
                    stop_d = now - st.session_state.stop_times[b_id]
                    stop_str = f"{stop_d.seconds // 60}m {stop_d.seconds % 60}s"
                else:
                    st.session_state.stop_times[b_id] = None
                    stop_str = "Rijdt"

                # Heading check
                heading = 0
                if b_id in st.session_state.history:
                    prev = st.session_state.history[b_id]
                    if abs(lat - prev['lat']) + abs(lon - prev['lon']) > 0.00001:
                        heading = math.degrees(math.atan2(lon - prev['lon'], lat - prev['lat'])) % 360
                st.session_state.history[b_id] = {'lat': lat, 'lon': lon, 'in_zone': in_z, 'heading': heading}

                # Status tekst voor popup
                if in_z:
                    if st.session_state.zone_entry_time[b_id]:
                        t_in = (now - st.session_state.zone_entry_time[b_id]).seconds // 60
                        status_z = f"Binnen zone (sinds {t_in}m)"
                    else: status_z = "Binnen zone"
                else:
                    if st.session_state.last_zone_exit[b_id]:
                        t_out = (now - st.session_state.last_zone_exit[b_id]).seconds // 60
                        status_z = f"Buiten zone (al {t_out}m)"
                    else: status_z = "Buiten zone"
                
                last_trip = st.session_state.last_trip_duration.get(b_id) or "-"

                # --- MARKER ---
                color = "#2ecc71" if in_z else "#3498db"
                char = "➤" if speed >= 0.5 else "●"
                rotation = f"transform: rotate({heading-90}deg);" if char == "➤" else ""
                
                icon_html = f'''
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; width: 60px; height: 60px;">
                    <div style="background: white; border: 2px solid {color}; border-radius: 4px; padding: 2px 6px; font-family: sans-serif; font-size: 11px; font-weight: bold; color: black; box-shadow: 0 2px 4px rgba(0,0,0,0.3); margin-bottom: 2px; white-space: nowrap;">{b_id}</div>
                    <div style="{rotation} color: {color}; font-size: 28px; line-height: 1; text-shadow: 1px 1px 2px rgba(0,0,0,0.3);">{char}</div>
                </div>
                '''
                
                popup_html = f"<b>Bus {b_id}</b><br><hr>Snelheid: {speed} km/u<br>Stil: {stop_str}<br>Locatie: {status_z}<br>Laatste rit: {last_trip}<br>Ritten voltooid: {st.session_state.counter[b_id]}"
                folium.Marker([lat, lon], popup=folium.Popup(popup_html, max_width=200), icon=folium.DivIcon(html=icon_html, icon_size=(60, 60), icon_anchor=(30, 45))).add_to(m)

        with map_box.container():
            st.markdown(f'<div class="update-badge">⏱️ Laatste update: {now.strftime("%H:%M:%S")}</div>', unsafe_allow_html=True)
            st_folium(m, width="100%", height=600, key="map_v1614", returned_objects=[])

        with stats_box.container():
            cols = st.columns(min(len(st.session_state.fleet), 6)) if st.session_state.fleet else st.columns(1)
            for i, b_id in enumerate(st.session_state.fleet):
                trip_t = st.session_state.last_trip_duration.get(b_id)
                delta_str = f"Rit: {trip_t}" if trip_t else "Bezig..."
                with cols[i % 6]: st.metric(label=f"Bus {b_id}", value=f"{st.session_state.counter[b_id]}x", delta=delta_str, delta_color="off")

    update_view()

with tab2:
    st.header("⚙️ Configuratie")
    m2 = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    Draw(draw_options={'polyline':False,'circle':False,'marker':False,'circlemarker':False}).add_to(m2)
    out = st_folium(m2, width="100%", height=500, key="cfg_v1614")
    if st.button("💾 Opslaan"):
        if out:
            if out.get("last_active_drawing"):
                st.session_state.drawn_polygon = [[p[1], p[0]] for p in out['last_active_drawing']['geometry']['coordinates'][0]]
            st.session_state.map_center = [out["center"]["lat"], out["center"]["lng"]]
            st.session_state.map_zoom = out["zoom"]
            save_config()
            st.success("Configuratie beveiligd opgeslagen!"); st.rerun()
