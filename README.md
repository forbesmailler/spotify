# Spotify Playlist Creator

Create Spotify playlists from [kworb.net](https://kworb.net/spotify/) streaming data or JSON song lists.

## Setup

1. Create a [Spotify Developer app](https://developer.spotify.com/dashboard) with redirect URI `http://localhost:8888/callback`

2. Set environment variables:

```bash
export SPOTIPY_CLIENT_ID="your_client_id"
export SPOTIPY_CLIENT_SECRET="your_client_secret"
export SPOTIPY_REDIRECT_URI="http://localhost:8888/callback"
```

3. Install dependencies:

```bash
mamba env create -f environment.yaml
mamba activate spotify
```

## Usage

### Artist mode

Create a playlist of an artist's top daily streamed songs (from kworb.net):

```bash
python playlist.py "Aphex Twin" 20
```

### Period mode

Create a playlist of top daily streamed songs for a year, decade, or all time:

```bash
python playlist.py 2020 30
python playlist.py 1960 25
python playlist.py all_time 50
```

### JSON mode

Create a playlist from a JSON file:

```bash
python playlist.py my_playlist.json
```

JSON format:

```json
{
  "name": "My Playlist",
  "description": "Optional description",
  "songs": ["Artist - Song", "Another Artist - Another Song"],
  "public": true
}
```

## Development

```bash
invoke format   # ruff format + check
invoke test     # pytest with coverage
invoke all      # both
```
