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
import streamlit.components.v1 as components

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
# DB (mit Auto-Migration)
# ----------------------------
def ensure_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Basistabelle (alt)
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

    # Migration: Spalten nachrüsten
    cur.execute("PRAGMA table_info(places);")
    cols = {row[1] for row in cur.fetchall()}

    if "industry" not in cols:
        cur.execute("ALTER TABLE places ADD COLUMN industry TEXT;")
    if "has_website" not in cols:
        cur.execute("ALTER TABLE places ADD COLUMN has_website INTEGER;")

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
            rating, user_ratings_total, phone, website, has_website, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    """, (
        row["place_id"], row["name"], row.get("industry"), row["address"],
        row["lat"], row["lng"], row["types"],
        row["rating"], row["user_ratings_total"],
        row["phone"], row["website"], row["has_website"], row["fetched_at"]
    ))
    con.commit()

def load_all(con) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM places ORDER BY fetched_at DESC", con)
    # falls alte Datensätze has_website NULL haben: nachberechnen
    if "has_website" in df.columns:
        df["has_website"] = df["has_website"].fillna(df["website"].notna().astype(int)).astype(int)
    else:
        df["has_website"] = df["website"].notna().astype(int)
    if "industry" not in df.columns:
        df["industry"] = None
    return df

# ----------------------------
# Mock generation
# ----------------------------
def random_id(prefix="mock"):
    tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    return f"{prefix}_{tail}"

def jitter_latlng(center_lat, center_lng, radius_m):
    r = radius_m * math.sqrt(random.random())
    theta = random.random() * 2 * math.pi
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)
    dlat = dy / 111_000.0
    dlng = dx / (111_000.0 * max(0.2, math.cos(math.radians(center_lat))))
    return center_lat + dlat, center_lng + dlng

def mock_generate_places(location_label, center_lat, center_lng, radius_m, industries, n, pct_with_website: int):
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

        has_site = (random.randint(1, 100) <= pct_with_website)
        website = None
        if has_site:
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
            "has_website": 1 if has_site else 0,
            "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z"
        })
    return rows

def find_clicked_place(df: pd.DataFrame, lat: float, lng: float):
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
# State
# ----------------------------
if "selected_place_id" not in st.session_state:
    st.session_state.selected_place_id = None

# ----------------------------
# UI
# ----------------------------
st.title("Firmenliste UI (Simulation) – klickbare Karte + Website-Flag + Preview")

con = ensure_db()

with st.sidebar:
    st.header("Ort")
    st.caption("Alle 9 Landeshauptstädte Österreichs:")
    capital = st.selectbox("Landeshauptstadt", list(CAPITALS_AT.keys()), index=list(CAPITALS_AT.keys()).index("Graz"))
    center_lat, center_lng = CAPITALS_AT[capital]
    location_label = f"{capital}, Austria"

    st.divider()
    st.header("Branchen")
    industries = st.multiselect(
        "Branchen auswählen",
        DEFAULT_INDUSTRIES,
        default=["Steuerberater", "Immobilienmakler", "Elektriker"]
    )

    st.divider()
    st.header("Simulation")
    radius_m = st.slider("Radius (Meter)", 200, 5000, 2000, 100)
    n = st.slider("Anzahl Fake-Firmen", 5, 300, 80, 5)
    pct_with_website = st.slider("Anteil mit Website (%)", 0, 100, 70, 5)

    colA, colB = st.columns(2)
    with colA:
        gen_btn = st.button("Simulieren", type="primary")
    with colB:
        clear_btn = st.button("DB leeren")

    st.divider()
    st.header("Filter")
    website_filter = st.radio(
        "Website Filter",
        ["Alle", "Nur mit Website", "Nur ohne Website"],
        index=0
    )

    st.divider()
    st.write("DB-Datei:", DB_PATH)

if clear_btn:
    clear_db(con)
    st.session_state.selected_place_id = None
    st.success("DB geleert.")

if gen_btn:
    rows = mock_generate_places(location_label, center_lat, center_lng, radius_m, industries, n, pct_with_website)
    for r in rows:
        upsert_place(con, r)
    st.success(f"{len(rows)} Einträge simuliert und gespeichert.")

df = load_all(con)

# Apply website filter
df_view = df.copy()
if website_filter == "Nur mit Website":
    df_view = df_view[df_view["has_website"] == 1]
elif website_filter == "Nur ohne Website":
    df_view = df_view[df_view["has_website"] == 0]

# Search filter (global)
st.divider()
q = st.text_input("Suche in Name/Adresse/Branche/Types", value="")
if q.strip():
    ql = q.strip().lower()
    df_view = df_view[
        df_view["name"].fillna("").str.lower().str.contains(ql) |
        df_view["address"].fillna("").str.lower().str.contains(ql) |
        df_view["industry"].fillna("").str.lower().str.contains(ql) |
        df_view["types"].fillna("").str.lower().str.contains(ql)
    ]

left, right = st.columns([1.2, 0.8])

# ----------------------------
# LEFT: table + website preview (unten links)
# ----------------------------
with left:
    st.subheader("Ergebnisse (DB)")
    st.caption(f"Einträge (nach Filter): {len(df_view)} / Gesamt: {len(df)}")

    show_cols = [
        "name", "industry", "address", "rating", "user_ratings_total", "has_website", "website", "phone", "fetched_at"
    ]
    show_cols = [c for c in show_cols if c in df_view.columns]
    st.dataframe(df_view[show_cols], use_container_width=True, height=420)

    csv = df_view.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", data=csv, file_name="places_filtered.csv", mime="text/csv")

    st.divider()
    st.subheader("Website Preview (links unten)")

    selected = None
    if st.session_state.selected_place_id:
        hit = df[df["place_id"] == st.session_state.selected_place_id]
        if len(hit) > 0:
            selected = hit.iloc[0]

    if selected is None:
        st.info("Klicke rechts auf einen Marker, um Details + Preview zu sehen.")
    else:
        if selected.get("has_website", 0) == 1 and isinstance(selected.get("website"), str) and selected["website"]:
            st.write(f"**Ausgewählt:** {selected['name']}")
            st.write(f"**Website:** {selected['website']}")
            # Iframe preview (kann von vielen Sites geblockt sein)
            components.iframe(selected["website"], height=360, scrolling=True)
            st.caption("Falls die Vorschau leer bleibt: die Website blockiert iFrame-Einbettung (CSP/X-Frame-Options).")
        else:
            st.write(f"**Ausgewählt:** {selected['name']}")
            st.warning("Diese Firma hat keine Website (oder keine Website-Daten).")

# ----------------------------
# RIGHT: clickable map + details
# ----------------------------
with right:
    st.subheader("Karte (klickbare Marker)")
    st.caption("Grün = hat Website | Rot = keine Website. Marker klicken → Details werden hier angezeigt + Preview links unten.")

    if df_view.empty or df_view["lat"].isna().all() or df_view["lng"].isna().all():
        st.info("Keine Daten nach Filter. Links simulieren oder Filter anpassen.")
    else:
        m = folium.Map(location=[center_lat, center_lng], zoom_start=12, control_scale=True)

        for _, r in df_view.dropna(subset=["lat", "lng"]).iterrows():
            has_site = int(r.get("has_website", 0)) == 1
            color = "green" if has_site else "red"

            tooltip = f"{r['name']} | {'🌐' if has_site else '—'} | ⭐ {r['rating']} ({r['user_ratings_total']})"
            popup_html = f"""
            <div style="font-size: 14px;">
              <b>{r['name']}</b><br/>
              Branche: {r.get('industry','')}<br/>
              {r['address']}<br/>
              Website: {"ja" if has_site else "nein"}<br/>
              ⭐ {r['rating']} ({r['user_ratings_total']})
            </div>
            """

            folium.Marker(
                location=[float(r["lat"]), float(r["lng"])],
                tooltip=tooltip,
                popup=folium.Popup(popup_html, max_width=350),
                icon=folium.Icon(color=color),
            ).add_to(m)

        map_state = st_folium(m, width=None, height=520)

        clicked = map_state.get("last_object_clicked")
        st.divider()

        if clicked:
            row = find_clicked_place(df_view, clicked["lat"], clicked["lng"])
            if row is None:
                st.warning("Klick erkannt, aber kein exakter Datensatz gefunden (Koordinaten-Match).")
            else:
                st.session_state.selected_place_id = row["place_id"]

                st.markdown("### Details")
                st.write(f"**Name:** {row['name']}")
                st.write(f"**Branche:** {row.get('industry')}")
                st.write(f"**Adresse:** {row['address']}")
                st.write(f"**Rating:** {row['rating']}  | **Reviews:** {row['user_ratings_total']}")
                st.write(f"**Website vorhanden:** {'Ja' if int(row.get('has_website',0))==1 else 'Nein'}")
                if row.get("website"):
                    st.markdown(f"**Website:** [{row['website']}]({row['website']})")
                else:
                    st.write("**Website:** —")
                st.write(f"**Telefon:** {row.get('phone')}")
                st.write(f"**Types:** {row.get('types')}")
                st.write(f"**Fetched:** {row.get('fetched_at')}")
        else:
            st.info("Noch kein Marker geklickt.")
