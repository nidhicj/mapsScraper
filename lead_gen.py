#!/usr/bin/env python3
"""
Leads scraper for Google Maps Places (official googlemaps client)

Features
- Loads API key from .env (GOOGLE_MAPS_API_KEY), config.ini, or environment var
- Text Search with pagination (handles next_page_token properly)
- Place Details with cost-controlled fields
- Robust error handling (timeouts, API errors, no results)
- CSV + JSON output with dynamic, human-readable filenames
- Simple CLI: python leads_scraper.py --query "Generator Dealer" --location "Atlanta, GA" --radius 5000

Install:
    pip install googlemaps python-dotenv

Notes:
- Ensure your Google Cloud project has Places API enabled.
- Billing must be enabled for Places API usage.
"""

import argparse
import configparser
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import googlemaps
from googlemaps import exceptions as gme

# -------------------------------
# 1) Configuration and Setup
# -------------------------------

def load_api_key() -> Optional[str]:
    """
    Load API key from (in order of precedence):
    1. .env file variable GOOGLE_MAPS_API_KEY (if python-dotenv is installed)
    2. config.ini [google] api_key = ...
    3. Environment variable GOOGLE_MAPS_API_KEY
    Returns the key or None if not found.
    """
    # Try .env (optional)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()  # loads variables from .env into environment
    except Exception:
        # dotenv is optional; if missing, we just skip
        pass

    # 1 & 3: environment
    key = os.getenv("GOOGLE_MAPS_API_KEY")
    if key:
        return key.strip()

    # 2: config.ini
    config = configparser.ConfigParser()
    if os.path.exists("config.ini"):
        try:
            config.read("config.ini")
            if "google" in config and "api_key" in config["google"]:
                return config["google"]["api_key"].strip()
        except Exception:
            # If config.ini exists but unreadable, fall through to None
            pass

    return None


def init_client(api_key: str) -> googlemaps.Client:
    """
    Initialize and return a googlemaps.Client instance.
    Raises ValueError if api_key is empty.
    """
    if not api_key:
        raise ValueError("Empty API key provided to init_client().")
    # You can tweak timeout or retry logic here if needed.
    return googlemaps.Client(key=api_key, timeout=10)


# -------------------------------
# 2) Core Logic and Search
# -------------------------------

def geocode_location(gmaps: googlemaps.Client, location: str) -> Optional[Dict[str, float]]:
    """
    Geocode a free-form location string to lat/lng.
    Returns dict with {'lat': float, 'lng': float} or None on failure/no results.
    """
    try:
        results = gmaps.geocode(location)
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        return {"lat": float(loc["lat"]), "lng": float(loc["lng"])}
    except (gme.Timeout, gme.TransportError) as e:
        print(f"[warn] Geocoding timeout/transport error: {e}", file=sys.stderr)
        return None
    except gme.ApiError as e:
        print(f"[warn] Geocoding API error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[warn] Geocoding unexpected error: {e}", file=sys.stderr)
        return None


def text_search_all_pages(
    gmaps: googlemaps.Client,
    query: str,
    location_latlng: Dict[str, float],
    radius: int = 5000,
    max_pages: int = 10,
    page_wait_seconds: float = 2.0
) -> List[Dict]:
    """
    Perform a Text Search for the query near the given lat/lng with a radius.
    Handles pagination (20 results per page) by following next_page_token until exhausted.
    The Places API typically requires a short wait (~2s) before the next_page_token becomes valid.
    Returns a list of raw result dicts (each having at least 'place_id').
    """
    all_results: List[Dict] = []
    next_page_token: Optional[str] = None
    page = 0

    while True:
        page += 1
        try:
            if next_page_token:
                # Next page: must wait a bit before using token per API docs.
                time.sleep(page_wait_seconds)
                resp = gmaps.places(query=query, page_token=next_page_token)
            else:
                resp = gmaps.places(
                    query=query,
                    location=(location_latlng["lat"], location_latlng["lng"]),
                    radius=radius
                )

            results = resp.get("results", [])
            if not results:
                # No results on this page; stop.
                break

            all_results.extend(results)

            next_page_token = resp.get("next_page_token")
            if not next_page_token:
                break  # no more pages

            if page >= max_pages:
                print(f"[info] Reached max_pages={max_pages}; stopping pagination.")
                break

        except gme.Timeout:
            print("[warn] Text Search timeout; continuing with what we have...", file=sys.stderr)
            break
        except gme.ApiError as e:
            print(f"[error] Text Search API error: {e}", file=sys.stderr)
            break
        except gme.TransportError as e:
            print(f"[error] Network/transport error during Text Search: {e}", file=sys.stderr)
            break
        except Exception as e:
            print(f"[error] Unexpected error during Text Search: {e}", file=sys.stderr)
            break

    return all_results


def get_leads_by_query(api_key: str, query: str, location: str, radius: int = 5000) -> List[Dict]:
    """
    Main orchestration function for your spec.

    1) Initialize client
    2) Geocode 'location' to lat/lng
    3) Text Search with pagination to collect place_ids
    4) For each place_id, fetch cost-controlled Place Details

    Returns a list of sanitized dicts with desired fields.
    """
    gmaps_client = init_client(api_key)

    print(f"[info] Geocoding location: {location}")
    latlng = geocode_location(gmaps_client, location)
    if not latlng:
        print("[error] Could not geocode the location; aborting.", file=sys.stderr)
        return []

    print(f"[info] Starting Text Search for '{query}' within {radius}m of {location}...")
    search_results = text_search_all_pages(
        gmaps=gmaps_client, query=query, location_latlng=latlng, radius=radius
    )
    if not search_results:
        print("[info] No search results found.")
        return []

    place_ids = [r.get("place_id") for r in search_results if r.get("place_id")]
    unique_place_ids = list(dict.fromkeys(place_ids))  # preserve order, remove dupes
    print(f"[info] Found {len(unique_place_ids)} unique places. Fetching details...")

    # Fields matter for cost control:
    fields = [
        'rating', 'geometry/viewport/northeast', 'geometry/location/lat', 'serves_wine', 'website', 'formatted_address', 'adr_address', 'reservable', 'formatted_phone_number', 'geometry/location/lng', 'address_component', 'editorial_summary', 'geometry', 'business_status', 'reviews', 'utc_offset', 'geometry/viewport/southwest', 'serves_lunch', 'secondary_opening_hours', 'review', 'geometry/viewport/northeast/lng', 'geometry/viewport/northeast/lat', 'type', 'wheelchair_accessible_entrance', 'price_level', 'delivery', 'takeout', 'serves_breakfast', 'serves_beer', 'opening_hours', 'serves_vegetarian_food', 'dine_in', 'place_id', 'photo', 'international_phone_number', 'current_opening_hours', 'curbside_pickup', 'geometry/viewport/southwest/lng', 'user_ratings_total', 'vicinity', 'icon', 'url', 'geometry/location', 'name', 'geometry/viewport/southwest/lat', 'serves_brunch', 'geometry/viewport', 'plus_code', 'serves_dinner', 'permanently_closed'
    ]

    leads: List[Dict] = []

    for idx, pid in enumerate(unique_place_ids, start=1):
        # Light progress indicator
        print(f"  - [{idx}/{len(unique_place_ids)}] {pid}", end="\r", flush=True)

        try:
            detail_resp = gmaps_client.place(place_id=pid, fields=fields)
            result = (detail_resp or {}).get("result")
            if not result:
                continue

            # Sanitize fields
            lead = {
                "place_id": pid,
                "name": safe_get_str(result, "name"),
                "formatted_address": safe_get_str(result, "formatted_address"),
                "formatted_phone_number": safe_get_str(result, "formatted_phone_number"),
                "website": safe_get_str(result, "website"),
                "url": safe_get_str(result, "url"),  # Google Maps place URL
                "types": "|".join(result.get("types", []) or []),
                "business_status": safe_get_str(result, "business_status"),
            }
            leads.append(lead)

        except gme.Timeout:
            print(f"\n[warn] Details timeout for place_id={pid}; skipping.", file=sys.stderr)
        except gme.ApiError as e:
            print(f"\n[warn] Details API error for place_id={pid}: {e}; skipping.", file=sys.stderr)
        except gme.TransportError as e:
            print(f"\n[warn] Network/transport error for place_id={pid}: {e}; skipping.", file=sys.stderr)
        except Exception as e:
            print(f"\n[warn] Unexpected error for place_id={pid}: {e}; skipping.", file=sys.stderr)

        # Gentle pacing to avoid hammering the API (adjust if needed)
        time.sleep(0.05)

    print("\n[info] Done fetching details.")
    return leads


# -------------------------------
# 3) Data Extraction Helpers
# -------------------------------

def safe_get_str(d: Dict, key: str) -> str:
    """
    Return a string value for d[key] or empty string if missing/non-string.
    Prevents KeyErrors and ensures CSV-safe values.
    """
    v = d.get(key, "")
    if v is None:
        return ""
    return str(v)


# -------------------------------
# 4) Data Output and Persistence
# -------------------------------

def sanitize_filename_fragment(text: str) -> str:
    """
    Turn arbitrary query/location text into a safe filename fragment:
    - Replace whitespace with underscore
    - Keep alphanumerics and underscore
    - Trim consecutive underscores
    """
    text = re.sub(r"\s+", "_", text.strip())
    text = re.sub(r"[^A-Za-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "search"


def build_output_basename(query: str, location: str) -> str:
    """
    Build a nice basename like 'Generator_Dealer_Atlanta_GA_2025-09-14_1512'
    """
    q = sanitize_filename_fragment(query)
    loc = sanitize_filename_fragment(location)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return f"{q}_{loc}_{ts}"


def write_csv(path: str, rows: List[Dict]) -> None:
    """
    Write leads to CSV with a stable column order.
    """
    fieldnames = [
        "place_id",
        "name",
        "formatted_address",
        "formatted_phone_number",
        "website",
        "url",
        "types",
        "business_status",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_json(path: str, rows: List[Dict]) -> None:
    """
    Write leads to JSON (UTF-8) for easy integration.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


# -------------------------------
# 5) CLI and Main
# -------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape business leads from Google Maps using Places API (official client)."
    )
    p.add_argument("--query", required=True, help='Search term, e.g., "Generator Dealer"')
    p.add_argument("--location", required=True, help='Location, e.g., "Atlanta, GA"')
    p.add_argument("--radius", type=int, default=5000, help="Search radius in meters (default: 5000)")
    p.add_argument("--json-only", action="store_true", help="Write only JSON (skip CSV)")
    p.add_argument("--csv-only", action="store_true", help="Write only CSV (skip JSON)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Load API key
    api_key = load_api_key()
    if not api_key:
        print(
            "[fatal] No API key found. Provide GOOGLE_MAPS_API_KEY via a .env file, config.ini, or environment.\n"
            "Examples:\n"
            "  1) .env file (requires python-dotenv):\n"
            "       GOOGLE_MAPS_API_KEY=YOUR_KEY_HERE\n"
            "  2) config.ini file:\n"
            "       [google]\n"
            "       api_key = YOUR_KEY_HERE\n"
            "  3) Environment variable:\n"
            "       export GOOGLE_MAPS_API_KEY=YOUR_KEY_HERE\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print("[info] API key loaded successfully.")
    print(f"[info] Query: '{args.query}' | Location: '{args.location}' | Radius: {args.radius}m")

    leads = get_leads_by_query(api_key, args.query, args.location, args.radius)
    if not leads:
        print("[info] No leads to write. Exiting.")
        return

    base = build_output_basename(args.query, args.location)
    wrote_any = False

    if not args.json_only:
        csv_path = f"{base}.csv"
        write_csv(csv_path, leads)
        print(f"[info] CSV written: {csv_path}")
        wrote_any = True

    if not args.csv_only:
        json_path = f"{base}.json"
        write_json(json_path, leads)
        print(f"[info] JSON written: {json_path}")
        wrote_any = True

    if not wrote_any:
        # If both flags are set (unlikely), default to CSV.
        csv_path = f"{base}.csv"
        write_csv(csv_path, leads)
        print(f"[info] No output format selected; wrote CSV by default: {csv_path}")

    print(f"[done] Collected {len(leads)} leads.")


if __name__ == "__main__":
    main()
