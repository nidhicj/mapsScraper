#!/usr/bin/env python3
"""
Streamlit UI for Google Maps Lead Scraper

Assumptions:
- Core scraping lives in `lead_scraper.py` in the same folder.
- `lead_scraper.py` exposes:
    - load_api_key() -> Optional[str]
    - get_leads_by_query(api_key: str, query: str, location: str, radius: int = 5000) -> List[Dict]
- API key handling (env/.env/config.ini) is done inside lead_scraper.py

Run:
    streamlit run app_streamlit.py
"""

from typing import List, Dict
import pandas as pd
import streamlit as st

# Import from your scraper module (same folder)
# Make sure your file is named exactly 'lead_scraper.py'
from lead_gen import load_api_key, get_leads_by_query

# -------------------------------
# Page Config & Title
# -------------------------------
st.set_page_config(page_title="Google Maps Lead Scraper", layout="wide")
st.title("Google Maps Lead Scraper")

# -------------------------------
# Sidebar Inputs
# -------------------------------
with st.sidebar:
    st.header("Search Settings")
    query = st.text_input("Search Query", placeholder="e.g., Generator Dealer")
    location = st.text_input("Location", placeholder="e.g., Atlanta, GA")
    radius = st.number_input("Search Radius (meters)", min_value=1, value=5000, step=100)
    start_btn = st.button("Start Scraping", use_container_width=True)

# Placeholder areas in main content for feedback & data
status_box = st.empty()
results_container = st.container()

# -------------------------------
# Helpers
# -------------------------------
def to_dataframe(leads: List[Dict]) -> pd.DataFrame:
    """
    Convert list of lead dicts into a tidy DataFrame for display & download.
    Expects keys from Place Details: name, formatted_address, formatted_phone_number, website, url
    """
    df = pd.DataFrame(leads or [])
    # Ensure the UI shows these columns in a friendly order if present
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
    # Keep only columns that exist, in the desired order
    cols = [c for c in desired_order if c in df.columns]
    if cols:
        df = df[cols]
    return df


def csv_bytes(df: pd.DataFrame) -> bytes:
    """Return CSV bytes for download_button."""
    return df.to_csv(index=False).encode("utf-8-sig")


def sanitize_fragment(text: str) -> str:
    """Simple filename fragment sanitizer for query/location."""
    import re
    text = (text or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "search"


# -------------------------------
# Main Action
# -------------------------------
if start_btn:
    # Validate inputs (including API key pulled from the scraper module)
    api_key = load_api_key()
    if not api_key:
        st.warning("API key is not configured. Configure it in your `lead_scraper.py` setup (.env/config.ini/env var).")
    elif not query or not location:
        st.warning("Please provide both a Search Query and a Location.")
    else:
        with st.spinner("Scraping in progress... This may take a moment."):
            try:
                status_box.info(f"Searching for **{query}** around **{location}** (radius {radius} m)…")
                leads = get_leads_by_query(api_key=api_key, query=query, location=location, radius=int(radius))

                if not leads:
                    st.error("No results found or an error occurred. Try a broader query, larger radius, or another location.")
                else:
                    df = to_dataframe(leads)
                    with results_container:
                        st.success(f"Found {len(df)} leads.")
                        st.dataframe(df, use_container_width=True)

                        # Download button (CSV)
                        base_q = sanitize_fragment(query)
                        base_loc = sanitize_fragment(location)
                        filename = f"{base_q}_{base_loc}.csv"
                        st.download_button(
                            label="Download as CSV",
                            data=csv_bytes(df),
                            file_name=filename,
                            mime="text/csv",
                            use_container_width=True,
                        )

            except Exception as e:
                # Friendly top-level error; the scraper module has its own internal error handling too.
                st.error(f"Unexpected error: {e}")
