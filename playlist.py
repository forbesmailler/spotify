"""
Spotify Playlist Creator
========================
Creates Spotify playlists from kworb.net streaming data or JSON song lists.

Usage:
    python playlist.py <artist_name> <playlist_length>
    python playlist.py <year_or_decade_or_all_time> <playlist_length>
    python playlist.py <playlist.json>

Examples:
    python playlist.py "Aphex Twin" 20
    python playlist.py all_time 50
    python playlist.py 2016 30
    python playlist.py 1960 25
    python playlist.py my_playlist.json
"""

import json
import re
import sys

import requests
import spotipy
from bs4 import BeautifulSoup
from spotipy.oauth2 import SpotifyOAuth

KWORB_BASE = "https://kworb.net/spotify"
VALID_DECADES = {1960, 1970, 1980, 1990, 2000, 2005, 2010, 2015, 2020, 2025}
VALID_YEAR_RANGE = range(2016, 2027)
SCOPE = "playlist-modify-public playlist-modify-private"


# --- Spotify helpers ---


def get_spotify_client() -> spotipy.Spotify:
    """Authenticate via env vars SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET,
    SPOTIPY_REDIRECT_URI and return a Spotify client."""
    auth = SpotifyOAuth(scope=SCOPE)
    return spotipy.Spotify(auth_manager=auth)


def search_track(sp, query: str) -> dict | None:
    """Search Spotify for a track. Returns {name, artist, uri} or None."""
    results = sp.search(q=query, type="track", limit=1)
    items = results["tracks"]["items"]
    if not items:
        return None
    track = items[0]
    return {
        "name": track["name"],
        "artist": track["artists"][0]["name"],
        "uri": track["uri"],
    }


def create_playlist(sp, name: str, description: str = "", public: bool = True) -> dict:
    """Create a playlist for the current user."""
    user_id = sp.current_user()["id"]
    return sp.user_playlist_create(
        user_id, name, public=public, description=description
    )


def add_tracks_to_playlist(sp, playlist_id: str, track_uris: list[str]) -> None:
    """Add tracks to a playlist in batches of 100."""
    for i in range(0, len(track_uris), 100):
        sp.playlist_add_items(playlist_id, track_uris[i : i + 100])


def _authenticate(sp) -> None:
    """Print authentication info."""
    user = sp.current_user()
    print("Authenticating with Spotify...")
    print(f"   Logged in as: {user['display_name']} ({user['id']})\n")


# --- Kworb scraping ---


def fetch_page(url: str) -> BeautifulSoup:
    """Fetch HTML page and return parsed BeautifulSoup."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_artist_songs(soup: BeautifulSoup, limit: int) -> list[dict]:
    """Parse artist page table, extract song name + Spotify track URI + daily streams.

    Returns top `limit` entries sorted by daily streams descending.
    """
    table = soup.find("table", class_="sortable")
    if not table:
        raise ValueError("Could not find songs table on page")

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        link = cells[0].find("a")
        if not link:
            continue
        name = link.get_text(strip=True)
        href = link["href"]
        track_id = href.rstrip("/").split("/")[-1]
        uri = f"spotify:track:{track_id}"
        daily_text = cells[2].get_text(strip=True).replace(",", "")
        if not daily_text:
            continue
        rows.append({"name": name, "uri": uri, "daily": int(daily_text)})

    rows.sort(key=lambda r: r["daily"], reverse=True)
    return rows[:limit]


def parse_songs_chart(soup: BeautifulSoup, limit: int) -> list[dict]:
    """Parse songs chart page table, extract artist-title query + daily streams.

    Returns top `limit` entries sorted by daily streams descending.
    """
    table = soup.find("table", class_="sortable")
    if not table:
        raise ValueError("Could not find songs table on page")

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        query = cells[0].get_text(strip=True)
        daily_text = cells[2].get_text(strip=True).replace(",", "")
        if not daily_text:
            continue
        rows.append({"query": query, "daily": int(daily_text)})

    rows.sort(key=lambda r: r["daily"], reverse=True)
    return rows[:limit]


def get_artist_id(sp, artist_name: str) -> str:
    """Search Spotify for an artist and return their ID."""
    results = sp.search(q=f"artist:{artist_name}", type="artist", limit=1)
    artists = results["artists"]["items"]
    if not artists:
        raise ValueError(f"Artist '{artist_name}' not found on Spotify")
    artist = artists[0]
    print(f"   Found artist: {artist['name']} (ID: {artist['id']})")
    return artist["id"]


# --- URL builders ---


def build_kworb_artist_url(artist_id: str) -> str:
    return f"{KWORB_BASE}/artist/{artist_id}_songs.html"


def build_kworb_songs_url(period: str) -> str:
    if period == "all_time":
        return f"{KWORB_BASE}/songs.html"
    return f"{KWORB_BASE}/songs_{period}.html"


def is_period(arg: str) -> bool:
    """Check if argument is a valid time period (all_time, year, or decade)."""
    if arg == "all_time":
        return True
    if re.fullmatch(r"\d+", arg):
        num = int(arg)
        return num in VALID_DECADES or num in VALID_YEAR_RANGE
    return False


# --- Orchestrators ---


def create_artist_playlist(artist_name: str, limit: int) -> None:
    """Create a playlist of an artist's top daily streamed songs from kworb.net."""
    sp = get_spotify_client()
    _authenticate(sp)

    print(f"Searching for artist: {artist_name}")
    artist_id = get_artist_id(sp, artist_name)

    url = build_kworb_artist_url(artist_id)
    print(f"Fetching kworb.net data: {url}")
    soup = fetch_page(url)

    songs = parse_artist_songs(soup, limit)
    if not songs:
        print("No songs found on kworb.net for this artist.")
        return

    print(f"\nTop {len(songs)} songs by daily streams:")
    for i, s in enumerate(songs, 1):
        print(f"  {i:3d}. {s['name']} ({s['daily']:,}/day)")

    playlist_name = f"{artist_name} - Top Daily Streams"
    playlist = create_playlist(
        sp,
        playlist_name,
        f"Top {limit} daily streamed songs for {artist_name} from kworb.net",
    )
    track_uris = [s["uri"] for s in songs]
    add_tracks_to_playlist(sp, playlist["id"], track_uris)

    print(f"\nDone! '{playlist_name}' is ready with {len(songs)} tracks.")


def create_period_playlist(period: str, limit: int) -> None:
    """Create a playlist of top daily streamed songs for a time period."""
    sp = get_spotify_client()
    _authenticate(sp)

    url = build_kworb_songs_url(period)
    print(f"Fetching kworb.net data: {url}")
    soup = fetch_page(url)

    entries = parse_songs_chart(soup, limit)
    if not entries:
        print("No songs found on kworb.net for this period.")
        return

    print(f"\nTop {len(entries)} songs by daily streams:")
    for i, e in enumerate(entries, 1):
        print(f"  {i:3d}. {e['query']} ({e['daily']:,}/day)")

    print("\nSearching for tracks on Spotify...")
    track_uris = []
    for e in entries:
        if result := search_track(sp, e["query"]):
            track_uris.append(result["uri"])
            print(f"  Found: {result['name']} -- {result['artist']}")
        else:
            print(f"  Not found: {e['query']}")

    if not track_uris:
        print("\nNo tracks found on Spotify. Playlist not created.")
        return

    label = "All Time" if period == "all_time" else period
    playlist_name = f"Top Daily Streams - {label}"
    playlist = create_playlist(
        sp, playlist_name, f"Top {limit} daily streamed songs ({label}) from kworb.net"
    )
    add_tracks_to_playlist(sp, playlist["id"], track_uris)

    print(f"\nDone! '{playlist_name}' is ready with {len(track_uris)} tracks.")


def create_json_playlist(filepath: str) -> None:
    """Create a playlist from a JSON file.

    JSON format: {"name": str, "description": str, "songs": [str, ...], "public": bool}
    """
    with open(filepath) as f:
        data = json.load(f)

    sp = get_spotify_client()
    _authenticate(sp)

    print(f"Searching for {len(data['songs'])} tracks on Spotify...")
    track_uris = []
    for query in data["songs"]:
        if result := search_track(sp, query):
            track_uris.append(result["uri"])
            print(f"  Found: {result['name']} -- {result['artist']}")
        else:
            print(f"  Not found: {query}")

    if not track_uris:
        print("\nNo tracks found on Spotify. Playlist not created.")
        return

    playlist = create_playlist(
        sp,
        data["name"],
        data.get("description", ""),
        public=data.get("public", True),
    )
    add_tracks_to_playlist(sp, playlist["id"], track_uris)

    print(f"\nDone! '{data['name']}' is ready with {len(track_uris)} tracks.")


# --- CLI ---


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1].endswith(".json"):
        create_json_playlist(sys.argv[1])
        return

    if len(sys.argv) != 3:
        print("Usage: python playlist.py <artist_or_period> <length>")
        print("       python playlist.py <playlist.json>")
        print()
        print('  artist:  python playlist.py "Aphex Twin" 20')
        print("  year:    python playlist.py 2016 30")
        print("  decade:  python playlist.py 1960 25")
        print("  all:     python playlist.py all_time 50")
        print("  json:    python playlist.py my_playlist.json")
        sys.exit(1)

    arg = sys.argv[1]
    limit = int(sys.argv[2])

    if is_period(arg):
        create_period_playlist(arg, limit)
    else:
        create_artist_playlist(arg, limit)


if __name__ == "__main__":
    main()
