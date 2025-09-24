
#!/usr/bin/env python3
"""
Polished Streamlit UI for a Google Maps Lead Scraper (product-grade shell).

It expects a module exposing:
    - load_api_key() -> Optional[str]
    - get_leads_by_query(api_key: str, query: str, location: str, radius: int = 5000) -> List[Dict]

Import resolution:
    1) Try `lead_gen` (rename your module to this if possible).
    2) Fallback to `mapsScraper` (your existing filename).

Run locally:
    pip install -r requirements.txt
    streamlit run app_streamlit.py

Deploy notes:
    - Put GOOGLE_API_KEY in environment or st.secrets
    - Serve behind a subdomain/app gateway (Cloud Run/Render/Railway/etc.)
"""

from typing import List, Dict
import os, re, time
import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

# ---------------------------------
# Resolve scraper backend
# ---------------------------------
load_api_key = None
get_leads_by_query = None
err_import = None
try:
    from lead_gen import load_api_key, get_leads_by_query  # preferred canonical name
except Exception as e1:
    try:
        from mapsScraper import load_api_key, get_leads_by_query  # fallback to user's existing module name
    except Exception as e2:
        err_import = f"Failed to import backend. Attempted 'lead_gen' ({e1}) and 'mapsScraper' ({e2})."

# ---------------------------------
# Page config and minimal chrome
# ---------------------------------
st.set_page_config(
    page_title="Google Maps Lead Scraper",
    page_icon="assets/scraper-icon.jpg",
    layout="wide",
)

# Minimal OG/meta for when embedded
html("""
<meta property='og:title' content='Google Maps Lead Scraper'>
<meta property='og:description' content='Find and export local business leads in seconds.'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
""", height=0)

# Hide default Streamlit chrome for cleaner look
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding-top: 1rem;}
    </style>
    """, unsafe_allow_html=True
)

# ---------------------------------
# Header
# ---------------------------------
col_logo, col_title, col_cta = st.columns([1, 4, 1])
with col_logo:
    try:
        st.image("assets/googlemaps.jpeg", use_container_width=True)
    except Exception:
        st.write("")  # optional
with col_title:
    st.markdown("### Google Maps Lead Scraper")
    st.caption("Fast, export-ready lead lists with addresses, phones, and websites—no code required.")
with col_cta:
    st.link_button("Privacy", "https://example.com/privacy", use_container_width=True)

# ---------------------------------
# Sidebar controls
# ---------------------------------
with st.sidebar:
    st.header("Search Settings")
    query = st.text_input("Search Query", placeholder="e.g., Generator Dealer")
    location = st.text_input("Location", placeholder="e.g., Atlanta, GA")
    radius = st.number_input("Search Radius (meters)", min_value=100, value=5000, step=100)
    start = st.button("Find Leads", use_container_width=True)

status = st.empty()
results = st.container()

# ---------------------------------
# Helpers
# ---------------------------------
def to_dataframe(leads: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(leads or [])
    desired_order = [
        "name",
        "formatted_address",
        "formatted_phone_number",
        "website",
        "url",
        "place_id",
        "types",
        "business_status",
    ]
    cols = [c for c in desired_order if c in df.columns]
    return df[cols] if cols else df

def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

def sanitize_fragment(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "search"

# Simple per-session rate limit
if "_last_call" not in st.session_state:
    st.session_state._last_call = 0.0

def guard(min_interval_sec: float = 3.0):
    now = time.time()
    if now - st.session_state._last_call < min_interval_sec:
        st.warning("You're clicking too fast—please wait a few seconds.")
        st.stop()
    st.session_state._last_call = now

# ---------------------------------
# Main flow
# ---------------------------------
if err_import:
    st.error(err_import)
    st.stop()

if start:
    guard(3.0)
    api_key = None
    try:
        api_key = load_api_key() if load_api_key else None
    except Exception as e:
        st.warning(f"Could not load API key: {e}")
    if not api_key:
        st.warning("API key missing. Provide it via environment or st.secrets.")
    elif not query or not location:
        st.warning("Please provide both a Search Query and a Location.")
    else:
        with st.spinner("Searching…"):
            try:
                status.info(f"Searching **{query}** around **{location}** within **{radius} m**")
                leads = get_leads_by_query(api_key=api_key, query=query, location=location, radius=int(radius))
                df = to_dataframe(leads)
                if df.empty:
                    st.error("No results. Try a broader query, larger radius, or nearby city.")
                else:
                    st.toast(f"Found {len(df)} leads.", icon="✅")
                    with results:
                        st.dataframe(df, use_container_width=True, height=520)
                        st.download_button(
                            "Download CSV",
                            data=csv_bytes(df),
                            file_name=f"{sanitize_fragment(query)}_{sanitize_fragment(location)}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
            except Exception as e:
                st.error(f"Unexpected error: {e}")
else:
    with results:
        st.info("Set your search on the left, then click **Find Leads** to fetch results.")
