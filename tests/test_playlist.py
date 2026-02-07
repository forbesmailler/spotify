import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from spotify.playlist import (
    _authenticate,
    add_tracks_to_playlist,
    build_kworb_artist_url,
    build_kworb_songs_url,
    create_artist_playlist,
    create_json_playlist,
    create_period_playlist,
    create_playlist,
    fetch_page,
    get_artist_id,
    get_spotify_client,
    is_period,
    main,
    parse_artist_songs,
    parse_songs_chart,
    search_track,
)


# --- HTML fixtures ---


def _artist_html(rows: list[tuple[str, str, str]]) -> BeautifulSoup:
    """Build a minimal kworb artist page.

    Each row is (song_name, track_id, daily_streams).
    """
    trs = ""
    for name, track_id, daily in rows:
        link = f'<a href="/spotify/track/{track_id}/">{name}</a>' if track_id else name
        trs += f"<tr><td>{link}</td><td>1,000,000</td><td>{daily}</td></tr>\n"
    return BeautifulSoup(
        f'<table class="sortable"><tbody>{trs}</tbody></table>', "html.parser"
    )


def _chart_html(rows: list[tuple[str, str]]) -> BeautifulSoup:
    """Build a minimal kworb songs chart page.

    Each row is (query, daily_streams).
    """
    trs = ""
    for query, daily in rows:
        trs += f"<tr><td>{query}</td><td>1,000,000</td><td>{daily}</td></tr>\n"
    return BeautifulSoup(
        f'<table class="sortable"><tbody>{trs}</tbody></table>', "html.parser"
    )


# --- Pure function tests ---


class TestIsPeriod:
    def test_all_time(self):
        assert is_period("all_time") is True

    def test_valid_year(self):
        assert is_period("2020") is True
        assert is_period("2016") is True
        assert is_period("2026") is True

    def test_valid_decade(self):
        assert is_period("1960") is True
        assert is_period("2000") is True
        assert is_period("2010") is True

    def test_invalid_string(self):
        assert is_period("hello") is False
        assert is_period("Aphex Twin") is False
        assert is_period("") is False

    def test_out_of_range_number(self):
        assert is_period("1950") is False
        assert is_period("2030") is False
        assert is_period("2014") is False


class TestBuildKworbArtistUrl:
    def test_format(self):
        url = build_kworb_artist_url("abc123")
        assert url == "https://kworb.net/spotify/artist/abc123_songs.html"


class TestBuildKworbSongsUrl:
    def test_all_time(self):
        url = build_kworb_songs_url("all_time")
        assert url == "https://kworb.net/spotify/songs.html"

    def test_year(self):
        url = build_kworb_songs_url("2020")
        assert url == "https://kworb.net/spotify/songs_2020.html"

    def test_decade(self):
        url = build_kworb_songs_url("1960")
        assert url == "https://kworb.net/spotify/songs_1960.html"


# --- HTML parsing tests ---


class TestParseArtistSongs:
    def test_normal(self):
        soup = _artist_html(
            [
                ("Song A", "aaa", "500"),
                ("Song B", "bbb", "1,000"),
                ("Song C", "ccc", "200"),
            ]
        )
        result = parse_artist_songs(soup, 10)
        assert len(result) == 3
        assert result[0] == {
            "name": "Song B",
            "uri": "spotify:track:bbb",
            "daily": 1000,
        }
        assert result[1] == {"name": "Song A", "uri": "spotify:track:aaa", "daily": 500}
        assert result[2] == {"name": "Song C", "uri": "spotify:track:ccc", "daily": 200}

    def test_limit(self):
        soup = _artist_html(
            [
                ("Song A", "aaa", "500"),
                ("Song B", "bbb", "1,000"),
                ("Song C", "ccc", "200"),
            ]
        )
        result = parse_artist_songs(soup, 2)
        assert len(result) == 2

    def test_sort_order(self):
        soup = _artist_html(
            [
                ("Low", "low", "10"),
                ("High", "high", "9,999"),
            ]
        )
        result = parse_artist_songs(soup, 10)
        assert result[0]["name"] == "High"
        assert result[1]["name"] == "Low"

    def test_missing_link_skipped(self):
        soup = _artist_html(
            [
                ("No Link", "", "500"),
                ("Has Link", "abc", "300"),
            ]
        )
        result = parse_artist_songs(soup, 10)
        assert len(result) == 1
        assert result[0]["name"] == "Has Link"

    def test_missing_daily_skipped(self):
        soup = _artist_html(
            [
                ("Song A", "aaa", ""),
                ("Song B", "bbb", "300"),
            ]
        )
        result = parse_artist_songs(soup, 10)
        assert len(result) == 1
        assert result[0]["name"] == "Song B"

    def test_no_table_raises(self):
        soup = BeautifulSoup("<html><body>No table here</body></html>", "html.parser")
        with pytest.raises(ValueError, match="Could not find songs table"):
            parse_artist_songs(soup, 10)


class TestParseSongsChart:
    def test_normal(self):
        soup = _chart_html(
            [
                ("Artist - Song A", "500"),
                ("Artist - Song B", "1,000"),
            ]
        )
        result = parse_songs_chart(soup, 10)
        assert len(result) == 2
        assert result[0] == {"query": "Artist - Song B", "daily": 1000}
        assert result[1] == {"query": "Artist - Song A", "daily": 500}

    def test_limit(self):
        soup = _chart_html(
            [
                ("A", "300"),
                ("B", "200"),
                ("C", "100"),
            ]
        )
        result = parse_songs_chart(soup, 2)
        assert len(result) == 2

    def test_sort_order(self):
        soup = _chart_html([("Low", "1"), ("High", "999")])
        result = parse_songs_chart(soup, 10)
        assert result[0]["query"] == "High"

    def test_missing_daily_skipped(self):
        soup = _chart_html([("Song", ""), ("Other", "100")])
        result = parse_songs_chart(soup, 10)
        assert len(result) == 1
        assert result[0]["query"] == "Other"

    def test_no_table_raises(self):
        soup = BeautifulSoup("<html><body>Empty</body></html>", "html.parser")
        with pytest.raises(ValueError, match="Could not find songs table"):
            parse_songs_chart(soup, 10)


# --- Spotify API tests (MagicMock) ---


class TestSearchTrack:
    def test_found(self):
        sp = MagicMock()
        sp.search.return_value = {
            "tracks": {
                "items": [
                    {
                        "name": "Windowlicker",
                        "artists": [{"name": "Aphex Twin"}],
                        "uri": "spotify:track:xyz",
                    }
                ]
            }
        }
        result = search_track(sp, "Aphex Twin Windowlicker")
        assert result == {
            "name": "Windowlicker",
            "artist": "Aphex Twin",
            "uri": "spotify:track:xyz",
        }
        sp.search.assert_called_once_with(
            q="Aphex Twin Windowlicker", type="track", limit=1
        )

    def test_not_found(self):
        sp = MagicMock()
        sp.search.return_value = {"tracks": {"items": []}}
        assert search_track(sp, "nonexistent") is None


class TestGetArtistId:
    def test_found(self):
        sp = MagicMock()
        sp.search.return_value = {
            "artists": {"items": [{"name": "Aphex Twin", "id": "abc123"}]}
        }
        result = get_artist_id(sp, "Aphex Twin")
        assert result == "abc123"

    def test_not_found_raises(self):
        sp = MagicMock()
        sp.search.return_value = {"artists": {"items": []}}
        with pytest.raises(ValueError, match="not found on Spotify"):
            get_artist_id(sp, "Nobody")


class TestCreatePlaylist:
    def test_returns_playlist(self):
        sp = MagicMock()
        sp.current_user.return_value = {"id": "user1"}
        sp.user_playlist_create.return_value = {"id": "pl1", "name": "Test"}
        result = create_playlist(sp, "Test", "desc", public=False)
        assert result == {"id": "pl1", "name": "Test"}
        sp.user_playlist_create.assert_called_once_with(
            "user1", "Test", public=False, description="desc"
        )


class TestAddTracksToPlaylist:
    def test_single_batch(self):
        sp = MagicMock()
        uris = [f"spotify:track:{i}" for i in range(50)]
        add_tracks_to_playlist(sp, "pl1", uris)
        sp.playlist_add_items.assert_called_once_with("pl1", uris)

    def test_multi_batch(self):
        sp = MagicMock()
        uris = [f"spotify:track:{i}" for i in range(250)]
        add_tracks_to_playlist(sp, "pl1", uris)
        assert sp.playlist_add_items.call_count == 3
        sp.playlist_add_items.assert_any_call("pl1", uris[:100])
        sp.playlist_add_items.assert_any_call("pl1", uris[100:200])
        sp.playlist_add_items.assert_any_call("pl1", uris[200:250])


class TestAuthenticate:
    def test_prints_user_info(self, capsys):
        sp = MagicMock()
        sp.current_user.return_value = {"display_name": "Test User", "id": "user1"}
        _authenticate(sp)
        output = capsys.readouterr().out
        assert "Test User" in output
        assert "user1" in output


# --- Integration-level tests ---


class TestFetchPage:
    @patch("spotify.playlist.requests.get")
    def test_returns_soup(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Hello</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = fetch_page("https://example.com")
        assert isinstance(result, BeautifulSoup)
        assert result.find("p").text == "Hello"
        mock_get.assert_called_once_with("https://example.com", timeout=30)


class TestMain:
    @patch("spotify.playlist.create_artist_playlist")
    def test_artist_mode(self, mock_create):
        with patch.object(sys, "argv", ["playlist.py", "Aphex Twin", "20"]):
            main()
        mock_create.assert_called_once_with("Aphex Twin", 20)

    @patch("spotify.playlist.create_period_playlist")
    def test_period_mode(self, mock_create):
        with patch.object(sys, "argv", ["playlist.py", "2020", "30"]):
            main()
        mock_create.assert_called_once_with("2020", 30)

    @patch("spotify.playlist.create_period_playlist")
    def test_all_time_mode(self, mock_create):
        with patch.object(sys, "argv", ["playlist.py", "all_time", "50"]):
            main()
        mock_create.assert_called_once_with("all_time", 50)

    @patch("spotify.playlist.create_json_playlist")
    def test_json_mode(self, mock_create):
        with patch.object(sys, "argv", ["playlist.py", "my_playlist.json"]):
            main()
        mock_create.assert_called_once_with("my_playlist.json")

    def test_usage_error(self):
        with patch.object(sys, "argv", ["playlist.py"]):
            with pytest.raises(SystemExit, match="1"):
                main()

    def test_usage_error_too_many_args(self):
        with patch.object(sys, "argv", ["playlist.py", "a", "b", "c"]):
            with pytest.raises(SystemExit, match="1"):
                main()


class TestCreateJsonPlaylist:
    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.search_track")
    @patch("spotify.playlist.create_playlist")
    @patch("spotify.playlist.add_tracks_to_playlist")
    def test_creates_playlist(
        self, mock_add, mock_create_pl, mock_search, mock_auth, mock_client, tmp_path
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_search.side_effect = [
            {"name": "Song A", "artist": "Artist A", "uri": "spotify:track:aaa"},
            None,
            {"name": "Song C", "artist": "Artist C", "uri": "spotify:track:ccc"},
        ]
        mock_create_pl.return_value = {"id": "pl1"}

        data = {
            "name": "My Playlist",
            "description": "Test",
            "songs": ["Song A", "Song B", "Song C"],
            "public": False,
        }
        filepath = tmp_path / "test.json"
        filepath.write_text(json.dumps(data))

        create_json_playlist(str(filepath))

        mock_auth.assert_called_once_with(sp)
        mock_create_pl.assert_called_once_with(sp, "My Playlist", "Test", public=False)
        mock_add.assert_called_once_with(
            sp, "pl1", ["spotify:track:aaa", "spotify:track:ccc"]
        )

    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.search_track")
    def test_no_tracks_found(
        self, mock_search, mock_auth, mock_client, tmp_path, capsys
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_search.return_value = None

        data = {"name": "Empty", "songs": ["nothing"]}
        filepath = tmp_path / "test.json"
        filepath.write_text(json.dumps(data))

        create_json_playlist(str(filepath))

        output = capsys.readouterr().out
        assert "No tracks found" in output


class TestGetSpotifyClient:
    @patch("spotify.playlist.SpotifyOAuth")
    @patch("spotify.playlist.spotipy.Spotify")
    def test_returns_client(self, mock_spotify, mock_oauth):
        mock_auth = MagicMock()
        mock_oauth.return_value = mock_auth
        mock_client = MagicMock()
        mock_spotify.return_value = mock_client
        result = get_spotify_client()
        assert result is mock_client
        mock_oauth.assert_called_once_with(
            scope="playlist-modify-public playlist-modify-private"
        )
        mock_spotify.assert_called_once_with(auth_manager=mock_auth)


class TestCreateArtistPlaylist:
    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.get_artist_id")
    @patch("spotify.playlist.fetch_page")
    @patch("spotify.playlist.parse_artist_songs")
    @patch("spotify.playlist.create_playlist")
    @patch("spotify.playlist.add_tracks_to_playlist")
    def test_full_flow(
        self,
        mock_add,
        mock_create_pl,
        mock_parse,
        mock_fetch,
        mock_aid,
        mock_auth,
        mock_client,
        capsys,
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_aid.return_value = "artist123"
        mock_fetch.return_value = MagicMock()
        mock_parse.return_value = [
            {"name": "Track A", "uri": "spotify:track:aaa", "daily": 500},
        ]
        mock_create_pl.return_value = {"id": "pl1"}

        create_artist_playlist("Aphex Twin", 10)

        mock_auth.assert_called_once_with(sp)
        mock_aid.assert_called_once_with(sp, "Aphex Twin")
        mock_create_pl.assert_called_once()
        mock_add.assert_called_once_with(sp, "pl1", ["spotify:track:aaa"])
        assert "Done!" in capsys.readouterr().out

    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.get_artist_id")
    @patch("spotify.playlist.fetch_page")
    @patch("spotify.playlist.parse_artist_songs")
    def test_no_songs(
        self, mock_parse, mock_fetch, mock_aid, mock_auth, mock_client, capsys
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_aid.return_value = "artist123"
        mock_fetch.return_value = MagicMock()
        mock_parse.return_value = []

        create_artist_playlist("Nobody", 10)

        assert "No songs found" in capsys.readouterr().out


class TestCreatePeriodPlaylist:
    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.fetch_page")
    @patch("spotify.playlist.parse_songs_chart")
    @patch("spotify.playlist.search_track")
    @patch("spotify.playlist.create_playlist")
    @patch("spotify.playlist.add_tracks_to_playlist")
    def test_full_flow(
        self,
        mock_add,
        mock_create_pl,
        mock_search,
        mock_parse,
        mock_fetch,
        mock_auth,
        mock_client,
        capsys,
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_fetch.return_value = MagicMock()
        mock_parse.return_value = [
            {"query": "Artist - Song", "daily": 1000},
        ]
        mock_search.return_value = {
            "name": "Song",
            "artist": "Artist",
            "uri": "spotify:track:aaa",
        }
        mock_create_pl.return_value = {"id": "pl1"}

        create_period_playlist("2020", 10)

        mock_auth.assert_called_once_with(sp)
        mock_create_pl.assert_called_once()
        mock_add.assert_called_once_with(sp, "pl1", ["spotify:track:aaa"])
        assert "Done!" in capsys.readouterr().out

    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.fetch_page")
    @patch("spotify.playlist.parse_songs_chart")
    def test_no_entries(self, mock_parse, mock_fetch, mock_auth, mock_client, capsys):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_fetch.return_value = MagicMock()
        mock_parse.return_value = []

        create_period_playlist("2020", 10)

        assert "No songs found" in capsys.readouterr().out

    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.fetch_page")
    @patch("spotify.playlist.parse_songs_chart")
    @patch("spotify.playlist.search_track")
    def test_no_tracks_found(
        self,
        mock_search,
        mock_parse,
        mock_fetch,
        mock_auth,
        mock_client,
        capsys,
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_fetch.return_value = MagicMock()
        mock_parse.return_value = [{"query": "Unknown", "daily": 100}]
        mock_search.return_value = None

        create_period_playlist("2020", 10)

        assert "No tracks found" in capsys.readouterr().out

    @patch("spotify.playlist.get_spotify_client")
    @patch("spotify.playlist._authenticate")
    @patch("spotify.playlist.fetch_page")
    @patch("spotify.playlist.parse_songs_chart")
    @patch("spotify.playlist.search_track")
    @patch("spotify.playlist.create_playlist")
    @patch("spotify.playlist.add_tracks_to_playlist")
    def test_all_time_label(
        self,
        mock_add,
        mock_create_pl,
        mock_search,
        mock_parse,
        mock_fetch,
        mock_auth,
        mock_client,
    ):
        sp = MagicMock()
        mock_client.return_value = sp
        mock_fetch.return_value = MagicMock()
        mock_parse.return_value = [{"query": "Song", "daily": 100}]
        mock_search.return_value = {
            "name": "Song",
            "artist": "A",
            "uri": "spotify:track:x",
        }
        mock_create_pl.return_value = {"id": "pl1"}

        create_period_playlist("all_time", 10)

        name_arg = mock_create_pl.call_args[0][1]
        assert "All Time" in name_arg
