import streamlit as st
import pandas as pd
import json, ssl, urllib.request, math, time
from datetime import datetime
import pytz
import folium
from streamlit_folium import folium_static

# --- SCHERMVULLENDE CONFIGURATIE ---
st.set_page_config(layout="wide", page_title="De Lijn Analyse", page_icon="🚌")

# CSS om alle Streamlit marges te verwijderen voor een écht full-screen effect
st.markdown("""
    <style>
        .block-container { padding-top: 0rem; padding-bottom: 0rem; padding-left: 0rem; padding-right: 0rem; }
        iframe { width: 100%; height: 85vh !important; }
        header { visibility: hidden; }
        footer { visibility: hidden; }
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
        else: st.error("❌ Verkeerd")
    st.stop()

# --- DATA & ANALYSE ---
API_KEY = st.secrets["DELIJN_API_KEY"]
FLEET = ["302990", "302471", "331406", "645099", "645098", "645092"]

# Sla 'passages' op in het geheugen van de sessie
if 'counter' not in st.session_state:
    st.session_state.counter = {b_id: 0 for b_id in FLEET}

def is_in_polygon(lat, lon, polygon):
    """Controleert of een bus binnen een polygoon is (Ray Casting algoritme)."""
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if lon > min(p1y, p2y):
            if lon <= max(p1y, p2y):
                if lat <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or lat <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside

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

# --- COORDINATEN VOOR DE TEST-POLYGOON (Bijv. Markt van Bornem) ---
# Je kunt dit later aanpasbaar maken via de sidebar
CHECK_ZONE = [
    [51.0970, 4.2250],
    [51.0985, 4.2250],
    [51.0985, 4.2280],
    [51.0970, 4.2280]
]

# --- VERWERKING ---
current_bussen = []
for b_id in FLEET:
    loc = get_bus_data(b_id)
    if loc:
        lat, lon = loc['lat'], loc['lon']
        
        # Check of bus in de zone rijdt
        in_zone = is_in_polygon(lat, lon, CHECK_ZONE)
        if in_zone:
            st.session_state.counter[b_id] += 1
            
        current_bussen.append({
            "id": b_id, "lat": lat, "lon": lon, 
            "speed": loc.get('speed', 0), "in_zone": in_zone
        })

# --- KAART ---
m = folium.Map(location=[51.05, 4.33], zoom_start=10, tiles="OpenStreetMap")

# Teken de Polygoon op de kaart
folium.Polygon(
    locations=CHECK_ZONE,
    color="red",
    fill=True,
    fill_color="red",
    fill_opacity=0.2,
    tooltip="Controle Zone"
).add_to(m)

for b in current_bussen:
    color = "green" if b["in_zone"] else "orange"
    icon_html = f'<div style="color: {color}; font-size: 24px; text-shadow: 1px 1px 2px black;">●</div>'
    label_html = f'<div style="background: white; border: 1px solid black; padding: 2px; font-size: 9px;">{b["id"]}<br>{st.session_state.counter[b["id"]]}x</div>'
    
    folium.Marker(
        [b['lat'], b['lon']], 
        icon=folium.DivIcon(html=f'<div>{icon_html}{label_html}</div>', icon_anchor=(15,15))
    ).add_to(m)

# Toon kaart schermvullend
folium_static(m)

# Sidebar info met statistieken
st.sidebar.title("📊 Statistieken")
for b_id, count in st.session_state.counter.items():
    st.sidebar.write(f"Bus {b_id}: {count} passages")

if st.sidebar.button("Reset Teller"):
    st.session_state.counter = {b_id: 0 for b_id in FLEET}
    st.rerun()

time.sleep(30)
st.rerun()
