import sqlite3
import random
import string
import math
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Places Collector (Mock)", layout="wide")

DB_PATH = "places_mock.db"

def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS places (
        place_id TEXT PRIMARY KEY,
        name TEXT,
        address TEXT,
        lat REAL,
        lng REAL,
        types TEXT,
        rating REAL,
        user_ratings_total INTEGER,
        phone TEXT,
        website TEXT,
        fetched_at TEXT
    );
    """)
    con.commit()
    return con

def upsert_place(con, row: dict):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO places (
            place_id, name, address, lat, lng, types,
            rating, user_ratings_total, phone, website, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(place_id) DO UPDATE SET
            name=excluded.name,
            address=excluded.address,
            lat=excluded.lat,
            lng=excluded.lng,
            types=excluded.types,
            rating=excluded.rating,
            user_ratings_total=excluded.user_ratings_total,
            phone=excluded.phone,
            website=excluded.website,
            fetched_at=excluded.fetched_at;
    """, (
        row["place_id"], row["name"], row["address"], row["lat"], row["lng"],
        row["types"], row["rating"], row["user_ratings_total"],
        row["phone"], row["website"], row["fetched_at"]
    ))
    con.commit()

def load_all(con) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM places ORDER BY fetched_at DESC", con)

def clear_db(con):
    cur = con.cursor()
    cur.execute("DELETE FROM places;")
    con.commit()

def random_id(prefix="mock"):
    tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    return f"{prefix}_{tail}"

def jitter_latlng(center_lat, center_lng, radius_m):
    # very rough conversion: 1 deg lat ~ 111_000m; 1 deg lng scaled by cos(lat)
    r = radius_m * math.sqrt(random.random())  # uniform over circle area
    theta = random.random() * 2 * math.pi
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)
    dlat = dy / 111_000.0
    dlng = dx / (111_000.0 * max(0.2, math.cos(math.radians(center_lat))))
    return center_lat + dlat, center_lng + dlng

def mock_generate_places(location_label, center_lat, center_lng, radius_m, keyword, n):
    # simple fake industry labels
    type_pool = [
        "accounting", "restaurant", "electrician", "plumber", "real_estate_agency",
        "dentist", "lawyer", "hair_care", "gym", "store", "car_repair"
    ]
    street_pool = ["Hauptstraße", "Bahnhofstraße", "Herrengasse", "Annenstraße", "Keplerstraße", "Grieskai", "Idlhofgasse"]
    suffix_pool = ["GmbH", "OG", "KG", "e.U.", "AG"]

    rows = []
    for i in range(n):
        lat, lng = jitter_latlng(center_lat, center_lng, radius_m)
        t = random.sample(type_pool, k=random.randint(1, 3))
        rating = round(random.uniform(3.2, 4.9), 1)
        ratings_total = random.randint(5, 1200)

        name = f"{keyword.title()} {random.choice(['Plus','Pro','Center','Studio','Service','Partner'])} {random.choice(suffix_pool)}"
        address = f"{random.choice(street_pool)} {random.randint(1, 220)}, {location_label}"
        phone = f"+43 316 {random.randint(100000, 999999)}"
        website = f"https://{keyword.lower()}-{random.randint(10,999)}.example.com"

        rows.append({
            "place_id": random_id("mock"),
            "name": name,
            "address": address,
            "lat": lat,
            "lng": lng,
            "types": ",".join(t),
            "rating": rating,
            "user_ratings_total": ratings_total,
            "phone": phone,
            "website": website,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"
        })
    return rows

# ---------------- UI ----------------
st.title("Firmenliste UI (Simulation) – Streamlit")

con = ensure_db()

with st.sidebar:
    st.header("Simulation")
    location_label = st.text_input("Ort / PLZ (Label)", value="8020 Graz, Austria")

    # Approx Center for Graz; used only for map points (does NOT call Google)
    st.caption("Center-Koordinaten sind nur für die Mock-Karte.")
    center_lat = st.number_input("Center Lat", value=47.0707, format="%.6f")
    center_lng = st.number_input("Center Lng", value=15.4395, format="%.6f")

    keyword = st.text_input("Keyword (Branche)", value="firma")
    radius_m = st.slider("Radius (Meter)", 200, 5000, 2000, 100)
    n = st.slider("Anzahl Fake-Firmen", 5, 200, 50, 5)

    colA, colB = st.columns(2)
    with colA:
        gen_btn = st.button("Simulieren", type="primary")
    with colB:
        clear_btn = st.button("DB leeren")

    st.divider()
    st.write("DB-Datei:", DB_PATH)

if clear_btn:
    clear_db(con)
    st.success("DB geleert.")

if gen_btn:
    rows = mock_generate_places(location_label, center_lat, center_lng, radius_m, keyword, n)
    for r in rows:
        upsert_place(con, r)
    st.success(f"{len(rows)} Einträge simuliert und gespeichert.")

df = load_all(con)

col1, col2 = st.columns([1.3, 1])

with col1:
    st.subheader("Ergebnisse (Mock-DB)")
    st.caption(f"Einträge: {len(df)}")
    st.dataframe(df, use_container_width=True, height=520)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", data=csv, file_name="mock_places.csv", mime="text/csv")

with col2:
    st.subheader("Karte")
    if len(df) > 0 and df["lat"].notna().any() and df["lng"].notna().any():
        map_df = df.dropna(subset=["lat", "lng"])[["lat", "lng"]].rename(columns={"lat": "latitude", "lng": "longitude"})
        st.map(map_df, zoom=12)
    else:
        st.info("Keine Punkte vorhanden. Klicke links auf 'Simulieren'.")

st.divider()
st.subheader("Filter")
q = st.text_input("Suche in Name/Adresse/Types", value="")
if q.strip():
    ql = q.strip().lower()
    f = df[
        df["name"].fillna("").str.lower().str.contains(ql) |
        df["address"].fillna("").str.lower().str.contains(ql) |
        df["types"].fillna("").str.lower().str.contains(ql)
    ]
    st.dataframe(f, use_container_width=True, height=320)
