import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import folium
from streamlit_folium import st_folium

# --- CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Live Tracker", page_icon="🚌")

# Haal de API-key veilig op uit Streamlit Secrets
try:
    API_KEY = st.secrets["DELIJN_API_KEY"]
except KeyError:
    st.error("⚠️ API Key niet gevonden! Voeg 'DELIJN_API_KEY' toe aan de Streamlit Secrets.")
    st.stop()

FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Berekent de hoek tussen twee punten (richting)."""
    startLat, startLon = math.radians(lat1), math.radians(lon1)
    endLat, endLon = math.radians(lat2), math.radians(lon2)
    dLon = endLon - startLon
    y = math.sin(dLon) * math.cos(endLat)
    x = math.cos(startLat) * math.sin(endLat) - math.sin(startLat) * math.cos(endLat) * math.cos(dLon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def get_bus_data(bus_id):
    """Haalt data op van De Lijn API."""
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
    except Exception as e:
        return None

# --- SESSION STATE ---
# Streamlit herlaadt de hele pagina bij elke refresh.
# We gebruiken st.session_state om de vorige locaties te onthouden voor richting-berekening.
if 'history' not in st.session_state:
    st.session_state.history = {}

# --- UI HEADER ---
st.title("🚌 De Lijn Live Vloot Monitor")

# Sidebar instellingen
st.sidebar.header("Dashboard Instellingen")
refresh_rate = st.sidebar.slider("Verversingssnelheid (seconden)", 10, 60, 15)
if st.sidebar.button("Forceer Refresh"):
    st.rerun()

# --- DATA VERWERKING ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        curr_lat, curr_lon = loc['lat'], loc['lon']
        speed = loc.get('speed', 0)
        heading = None
        
        # Bereken richting t.o.v. vorige meting uit de sessie-geheugen
        if b_id in st.session_state.history:
            prev = st.session_state.history[b_id]
            # Check of de bus meer dan ~8 meter bewogen is om trilling te voorkomen
            dist = abs(curr_lat - prev['lat']) + abs(curr_lon - prev['lon'])
            if dist > 0.00008:
                heading = calculate_bearing(prev['lat'], prev['lon'], curr_lat, curr_lon)
            else:
                heading = prev.get('heading') # Stilstand: behoud laatst bekende hoek
        
        bus_info = {
            "id": b_id, "lat": curr_lat, "lon": curr_lon,
            "speed": speed, "heading": heading
        }
        current_bussen.append(bus_info)
        # Update geschiedenis voor de volgende run
        st.session_state.history[b_id] = {"lat": curr_lat, "lon": curr_lon, "heading": heading}

# --- KAART ---
# Startpositie (gemiddelde van Vlaanderen/Antwerpen/Gent)
m = folium.Map(location=[51.05, 4.33], zoom_start=11, tiles="OpenStreetMap")

for b in current_bussen:
    label = f"Bus {b['id']} | Snelheid: {b['speed']} km/u"
    
    # HTML Icon opbouw
    if b['heading'] is not None:
        rot = b['heading'] - 90  # Correctie voor pijl-oriëntatie
        icon_html = f'<div style="transform: rotate({rot}deg); color: #e67e22; font-size: 26px; text-shadow: 1px 1px 2px black;">➤</div>'
    else:
        # Geen richting bekend: toon bolletje
        icon_html = '<div style="color: #7f8c8d; font-size: 20px; text-shadow: 1px 1px 2px black;">●</div>'

    # Voeg label met ID en snelheid toe onder het icoon
    full_html = f"""
    <div style="display:flex; flex-direction:column; align-items:center;">
        {icon_html}
        <div style="background:#f1c40f; border:2px solid black; border-radius:4px; 
                    padding:1px 5px; font-weight:bold; font-size:11px; white-space:nowrap; 
                    margin-top:-2px; box-shadow: 2px 2px 5px rgba(0,0,0,0.3);">
            {b['id']} ({b['speed']}kmu)
        </div>
    </div>
    """

    folium.Marker(
        [b['lat'], b['lon']],
        popup=label,
        tooltip=label,
        icon=folium.DivIcon(html=full_html, iconSize=[60, 60], iconAnchor=[30, 30])
    ).add_to(m)

# Toon de kaart in de Streamlit app
st_folium(m, width="100%", height=700, key="vloot_kaart")

# Status onderaan
col1, col2 = st.columns(2)
with col1:
    st.info(f"🕒 Laatste update: {datetime.now().strftime('%H:%M:%S')}")
with col2:
    st.success(f"🚌 Bussen online: {len(current_bussen)}")

# --- AUTO REFRESH LOGICA ---
time.sleep(refresh_rate)
st.rerun()

