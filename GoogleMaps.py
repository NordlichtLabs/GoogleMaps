# -*- coding: utf-8 -*-
import sqlite3
import random
import string
import math
from datetime import datetime
import urllib.parse as up

import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium
import streamlit.components.v1 as components

st.set_page_config(page_title="Places Collector Demo", layout="wide")

DB_PATH = "places_mock.db"

# ----------------------------
# 9 Landeshauptstädte AT
# ----------------------------
CAPITALS_AT = {
    "Wien": (48.2082, 16.3738),
    "St. Pölten": (48.2036, 15.6243),
    "Linz": (48.3069, 14.2858),
    "Salzburg": (47.8095, 13.0550),
    "Innsbruck": (47.2692, 11.4041),
    "Bregenz": (47.5031, 9.7471),
    "Graz": (47.0707, 15.4395),
    "Klagenfurt": (46.6247, 14.3053),
    "Eisenstadt": (47.8456, 16.5232),
}

DEFAULT_INDUSTRIES = [
    "Steuerberater",
    "Immobilienmakler",
    "Elektriker",
    "Installateur",
    "Zahnarzt",
    "Rechtsanwalt",
    "Friseur",
    "Fitnessstudio",
    "Auto Werkstatt",
    "Restaurant",
]

# ----------------------------
# DB + Migration
# ----------------------------
def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS places (
        place_id TEXT PRIMARY KEY,
        name TEXT,
        industry TEXT,
        address TEXT,
        lat REAL,
        lng REAL,
        types TEXT,
        rating REAL,
        user_ratings_total INTEGER,
        phone TEXT,
        website TEXT,
        has_website INTEGER,
        fetched_at TEXT
    );
    """)

    con.commit()
    return con


def clear_db(con):
    con.execute("DELETE FROM places;")
    con.commit()


def upsert_place(con, row):
    con.execute("""
        INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(place_id) DO UPDATE SET
            name=excluded.name,
            industry=excluded.industry,
            address=excluded.address,
            lat=excluded.lat,
            lng=excluded.lng,
            types=excluded.types,
            rating=excluded.rating,
            user_ratings_total=excluded.user_ratings_total,
            phone=excluded.phone,
            website=excluded.website,
            has_website=excluded.has_website,
            fetched_at=excluded.fetched_at;
    """, tuple(row.values()))
    con.commit()


def load_all(con):
    return pd.read_sql_query("SELECT * FROM places", con)

# ----------------------------
# Mock Generator
# ----------------------------
def random_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=20))


def jitter(lat, lng, radius):
    r = radius * math.sqrt(random.random())
    theta = random.random() * 2 * math.pi
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)
    return lat + dy/111000, lng + dx/111000


def mock_places(city, lat, lng, industries, n, pct_site):
    rows = []

    for _ in range(n):
        industry = random.choice(industries)
        plat, plng = jitter(lat, lng, 2000)

        has_site = random.randint(1,100) <= pct_site
        website = None
        if has_site:
            website = f"https://{industry.lower()}-{random.randint(10,999)}.example.com"

        rows.append({
            "place_id": random_id(),
            "name": f"{industry} Service GmbH",
            "industry": industry,
            "address": f"Hauptstraße {random.randint(1,200)}, {city}",
            "lat": plat,
            "lng": plng,
            "types": industry,
            "rating": round(random.uniform(3.5,4.9),1),
            "user_ratings_total": random.randint(5,500),
            "phone": "+43 123 456789",
            "website": website,
            "has_website": 1 if website else 0,
            "fetched_at": datetime.utcnow().isoformat()
        })

    return rows

# ----------------------------
# Website Preview Renderer
# ----------------------------
def render_preview(url):
    st.markdown(f"**Website:** [{url}]({url})")

    # iframe Versuch
    components.iframe(url, height=360, scrolling=True)

    # Fallback Screenshot
    thumb = "https://image.thum.io/get/width/1000/" + up.quote(url, safe="")
    st.caption("Fallback Screenshot:")
    st.image(thumb, use_container_width=True)

# ----------------------------
# App State
# ----------------------------
if "selected" not in st.session_state:
    st.session_state.selected = None

con = ensure_db()

# ----------------------------
# Sidebar
# ----------------------------
with st.sidebar:
    city = st.selectbox("Landeshauptstadt", list(CAPITALS_AT.keys()))
    lat, lng = CAPITALS_AT[city]

    industries = st.multiselect(
        "Branchen",
        DEFAULT_INDUSTRIES,
        default=["Steuerberater","Elektriker"]
    )

    n = st.slider("Firmen", 10, 200, 60)
    pct = st.slider("Mit Website %", 0, 100, 70)

    if st.button("Simulieren"):
        rows = mock_places(city, lat, lng, industries, n, pct)
        for r in rows:
            upsert_place(con, r)

    if st.button("DB leeren"):
        clear_db(con)

# ----------------------------
# Data
# ----------------------------
df = load_all(con)

left, right = st.columns([1.2,0.8])

# ----------------------------
# Tabelle + Preview
# ----------------------------
with left:
    st.dataframe(df, use_container_width=True, height=420)

    st.subheader("Website Preview")

    if st.session_state.selected is not None:
        row = df[df.place_id == st.session_state.selected].iloc[0]

        if row.has_website:
            render_preview(row.website)
        else:
            st.warning("Keine Website vorhanden")

# ----------------------------
# Karte
# ----------------------------
with right:
    m = folium.Map(location=[lat,lng], zoom_start=12)

    for _,r in df.iterrows():
        color = "green" if r.has_website else "red"

        folium.Marker(
            [r.lat, r.lng],
            tooltip=r.name,
            icon=folium.Icon(color=color)
        ).add_to(m)

    state = st_folium(m, height=520)

    if state.get("last_object_clicked"):
        clicked = state["last_object_clicked"]
        match = df[
            (df.lat.round(6)==round(clicked["lat"],6)) &
            (df.lng.round(6)==round(clicked["lng"],6))
        ]

        if len(match):
            st.session_state.selected = match.iloc[0].place_id
            st.rerun()
