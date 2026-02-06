# -*- coding: utf-8 -*-
import sqlite3
import random
import string
import math
from datetime import datetime
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Places Collector (Mock, Clickable Map)", layout="wide")

DB_PATH = "places_mock.db"

CAPITALS_AT = {
    # 9 Landeshauptstädte Österreichs (ungefähre Center-Koordinaten)
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
# DB
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
        fetched_at TEXT
    );
    """)
    con.commit()
    return con

def clear_db(con):
    cur = con.cursor()
    cur.execute("DELETE FROM places;")
    con.commit()

def upsert_place(con, row: dict):
    cur = con.cursor()
    cur.execute("""
        INSERT INTO places (
            place_id, name, industry, address, lat, lng, types,
            rating, user_ratings_total, phone, website, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            fetched_at=excluded.fetched_at;
    """, (
        row["place_id"], row["name"], row["industry"], row["address"], row["lat"], row["lng"],
        row["types"], row["rating"], row["user_ratings_total"],
        row["phone"], row["website"], row["fetched_at"]
    ))
    con.commit()

def load_all(con) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM places ORDER BY fetched_at DESC", con)

# ----------------------------
# Mock generation
# ----------------------------
def random_id(prefix="mock"):
    tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    return f"{prefix}_{tail}"

def jitter_latlng(center_lat, center_lng, radius_m):
    # rough conversion: 1 deg lat ~ 111_000m; 1 deg lng scaled by cos(lat)
    r = radius_m * math.sqrt(random.random())
    theta = random.random() * 2 * math.pi
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)
    dlat = dy / 111_000.0
    dlng = dx / (111_000.0 * max(0.2, math.cos(math.radians(center_lat))))
    return center_lat + dlat, center_lng + dlng

def mock_generate_places(location_label, center_lat, center_lng, radius_m, industries, n):
    type_pool = [
        "accounting", "restaurant", "electrician", "plumber", "real_estate_agency",
        "dentist", "lawyer", "hair_care", "gym", "store", "car_repair"
    ]
    street_pool = ["Hauptstraße", "Bahnhofstraße", "Herrengasse", "Annenstraße", "Keplerstraße", "Grieskai", "Idlhofgasse"]
    suffix_pool = ["GmbH", "OG", "KG", "e.U.", "AG"]

    rows = []
    for _ in range(n):
        industry = random.choice(industries) if industries else "Firma"
        lat, lng = jitter_latlng(center_lat, center_lng, radius_m)
        t = random.sample(type_pool, k=random.randint(1, 3))
        rating = round(random.uniform(3.2, 4.9), 1)
        ratings_total = random.randint(5, 1200)

        name = f"{industry} {random.choice(['Plus','Pro','Center','Studio','Service','Partner'])} {random.choice(suffix_pool)}"
        address = f"{random.choice(street_pool)} {random.randint(1, 220)}, {location_label}"
        phone = f"+43 316 {random.randint(100000, 999999)}"
        website = f"https://{industry.lower().replace(' ', '-')}-{random.randint(10,999)}.example.com"

        rows.append({
            "place_id": random_id("mock"),
            "name": name,
            "industry": industry,
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

def find_clicked_place(df: pd.DataFrame, lat: float, lng: float):
    # match by rounded coords (Marker coords are the same we created)
    if df.empty:
        return None
    lat_r = round(lat, 6)
    lng_r = round(lng, 6)
    tmp = df.copy()
    tmp["lat_r"] = tmp["lat"].round(6)
    tmp["lng_r"] = tmp["lng"].round(6)
    hit = tmp[(tmp["lat_r"] == lat_r) & (tmp["lng_r"] == lng_r)]
    if len(hit) == 0:
        return None
    return hit.iloc[0].drop(["lat_r", "lng_r"])

# ----------------------------
# UI
# ----------------------------
st.title("Firmenfinder")

con = ensure_db()

with st.sidebar:
    st.header("Ort")
    st.caption("Hier sind alle 9 Landeshauptstädte Österreichs:")
    capital = st.selectbox("Landeshauptstadt", list(CAPITALS_AT.keys()), index=list(CAPITALS_AT.keys()).index("Graz"))
    center_lat, center_lng = CAPITALS_AT[capital]
    location_label = f"{capital}, Austria"

    st.divider()
    st.header("Branchen")
    industries = st.multiselect("Branchen auswählen", DEFAULT_INDUSTRIES, default=["Steuerberater", "Immobilienmakler", "Elektriker"])

    st.divider()
    st.header("Simulation")
    radius_m = st.slider("Radius (Meter)", 200, 5000, 2000, 100)
    n = st.slider("Anzahl Fake-Firmen", 5, 300, 80, 5)

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
    rows = mock_generate_places(location_label, center_lat, center_lng, radius_m, industries, n)
    for r in rows:
        upsert_place(con, r)
    st.success(f"{len(rows)} Einträge simuliert und gespeichert.")

df = load_all(con)

left, right = st.columns([1.15, 0.85])

with left:
    st.subheader("Ergebnisse (DB)")
    st.caption(f"Einträge: {len(df)}")
    st.dataframe(df, use_container_width=True, height=520)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", data=csv, file_name="mock_places.csv", mime="text/csv")

with right:
    st.subheader("Karte (klickbare Marker)")
    st.caption("Klicke einen Marker → Details werden darunter angezeigt.")

    if df.empty or df["lat"].isna().all() or df["lng"].isna().all():
        st.info("Noch keine Daten. Links auf „Simulieren“ klicken.")
    else:
        m = folium.Map(location=[center_lat, center_lng], zoom_start=12, control_scale=True)

        # Marker
        for _, r in df.dropna(subset=["lat", "lng"]).iterrows():
            tooltip = f"{r['name']} | ⭐ {r['rating']} ({r['user_ratings_total']})"
            popup_html = f"""
            <div style="font-size: 14px;">
              <b>{r['name']}</b><br/>
              Branche: {r['industry']}<br/>
              {r['address']}<br/>
              ⭐ {r['rating']} ({r['user_ratings_total']})<br/>
              <small>Click marker → Details rechts</small>
            </div>
            """
            folium.Marker(
                location=[float(r["lat"]), float(r["lng"])],
                tooltip=tooltip,
                popup=folium.Popup(popup_html, max_width=350),
            ).add_to(m)

        map_state = st_folium(m, width=None, height=520)

        clicked = map_state.get("last_object_clicked")
        st.divider()

        if clicked:
            row = find_clicked_place(df, clicked["lat"], clicked["lng"])
            if row is None:
                st.warning("Klick erkannt, aber kein exakter Datensatz gefunden (Koordinaten-Match).")
            else:
                st.markdown("### Details")
                st.write(f"**Name:** {row['name']}")
                st.write(f"**Branche:** {row['industry']}")
                st.write(f"**Adresse:** {row['address']}")
                st.write(f"**Rating:** {row['rating']}  | **Reviews:** {row['user_ratings_total']}")
                st.write(f"**Telefon:** {row['phone']}")
                st.write(f"**Website:** {row['website']}")
                st.write(f"**Types:** {row['types']}")
                st.write(f"**Fetched:** {row['fetched_at']}")
        else:
            st.info("Noch kein Marker geklickt.")

st.divider()
st.subheader("Filter")
q = st.text_input("Suche in Name/Adresse/Branche/Types", value="")
if q.strip():
    ql = q.strip().lower()
    f = df[
        df["name"].fillna("").str.lower().str.contains(ql) |
        df["address"].fillna("").str.lower().str.contains(ql) |
        df["industry"].fillna("").str.lower().str.contains(ql) |
        df["types"].fillna("").str.lower().str.contains(ql)
    ]
    st.dataframe(f, use_container_width=True, height=320)
