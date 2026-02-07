# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Spotify Playlist Creator — a Python CLI tool that creates Spotify playlists from [kworb.net](https://kworb.net/spotify/) streaming data or JSON song lists, using [spotipy](https://spotipy.readthedocs.io/).

## Running

```bash
# By artist (top daily streams from kworb.net)
python playlist.py "Aphex Twin" 20

# By time period (year, decade, or all_time)
python playlist.py 2020 30
python playlist.py all_time 50

# From a JSON file
python playlist.py my_playlist.json
```

Requires env vars `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI` from a [Spotify Developer app](https://developer.spotify.com/dashboard).

## Dependencies

Managed via `environment.yaml` (mamba/conda). Key packages: `spotipy`, `beautifulsoup4`, `requests`.

## Architecture

Single-module design (`playlist.py`):

- **Spotify helpers**: `get_spotify_client`, `search_track`, `create_playlist`, `add_tracks_to_playlist`, `_authenticate`
- **Kworb scraping**: `fetch_page`, `parse_artist_songs`, `parse_songs_chart`, `get_artist_id`
- **URL builders**: `build_kworb_artist_url`, `build_kworb_songs_url`, `is_period`
- **Orchestrators**: `create_artist_playlist`, `create_period_playlist`, `create_json_playlist`
- **CLI**: `main()` — dispatches based on argument type

## Development

```bash
invoke format   # ruff format + check
invoke test     # pytest with coverage
invoke all      # both
```
