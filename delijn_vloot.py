import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import folium
from streamlit_folium import st_folium

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Live Tracker", page_icon="🚌")

# Veilig ophalen van de API-key uit Streamlit Secrets
try:
    API_KEY = st.secrets["DELIJN_API_KEY"]
except Exception:
    st.error("⚠️ API Key 'DELIJN_API_KEY' niet gevonden in Streamlit Secrets!")
    st.stop()

FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Berekent de rijrichting tussen twee punten."""
    startLat, startLon = math.radians(lat1), math.radians(lon1)
    endLat, endLon = math.radians(lat2), math.radians(lon2)
    dLon = endLon - startLon
    y = math.sin(dLon) * math.cos(endLat)
    x = math.cos(startLat) * math.sin(endLat) - math.sin(startLat) * math.cos(endLat) * math.cos(dLon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def get_bus_data(bus_id):
    """Haalt de meest recente locatie op van de De Lijn API."""
    url = f"https://api.delijn.be/location-tracking/v1/locations?vehicleId={bus_id}"
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "Ocp-Apim-Subscription-Key": API_KEY, 
        "User-Agent": "Mozilla/5.0"
    })
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as r:
            data = json.loads(r.read().decode())
            return data["data"][0] if data.get("data") else None
    except Exception:
        return None

# --- STATE MANAGEMENT ---
if 'history' not in st.session_state:
    st.session_state.history = {}

# --- UI ---
st.title("🚌 De Lijn Live Vloot Monitor")

# Sidebar
refresh_rate = st.sidebar.slider("Verversingssnelheid (sec)", 10, 60, 15)
if st.sidebar.button("Nu vernieuwen"):
    st.rerun()

# Data ophalen en verwerken
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        curr_lat, curr_lon = loc['lat'], loc['lon']
        speed = loc.get('speed', 0)
        heading = None
        
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            dist = abs(curr_lat - prev['lat']) + abs(curr_lon - prev['lon'])
            if dist > 0.00008:
                heading = calculate_bearing(prev['lat'], prev['lon'], curr_lat, curr_lon)
            else:
                heading = prev.get('heading')
        
        current_bussen.append({
            "id": b_id, "lat": curr_lat, "lon": curr_lon, 
            "speed": speed, "heading": heading
        })
        st.session_state.history[b_id] = {"lat": curr_lat, "lon": curr_lon, "heading": heading}

# Kaart maken
m = folium.Map(location=[51.05, 4.33], zoom_start=10)

for b in current_bussen:
    label = f"Bus {b['id']} ({b['speed']} km/u)"
    
    # Icoon bepalen (Pijl of Bol)
    if b['heading'] is not None:
        rot = b['heading'] - 90
        icon_html = f'<div style="transform: rotate({rot}deg); color: #e67e22; font-size: 26px; text-shadow: 1px 1px 2px black;">➤</div>'
    else:
        icon_html = '<div style="color: #7f8c8d; font-size: 20px; text-shadow: 1px 1px 2px black;">●</div>'

    # HTML voor de marker (Pijl + Label)
    full_html = f"""
    <div style="display: flex; flex-direction: column; align-items: center; width: 80px;">
        {icon_html}
        <div style="background: #f1c40f; border: 2px solid black; border-radius: 4px; 
                    padding: 1px 5px; font-weight: bold; font-size: 10px; color: black;
                    white-space: nowrap; margin-top: -2px; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
            {b['id']} ({b['speed']}kmu)
        </div>
    </div>
    """

    folium.Marker(
        [b['lat'], b['lon']],
        popup=label,
        tooltip=label,
        icon=folium.DivIcon(
            html=full_html,
            icon_size=(80, 80),
            icon_anchor=(40, 40)
        )
    ).add_to(m)

# Kaart tonen
st_folium(m, width="100%", height=700, key="vloot_kaart")

# Footer info
c1, c2 = st.columns(2)
with c1:
    st.info(f"🕒 Update: {datetime.now().strftime('%H:%M:%S')}")
with c2:
    st.success(f"🚌 Actief: {len(current_bussen)} bussen")

# Auto-refresh
time.sleep(refresh_rate)
st.rerun()
