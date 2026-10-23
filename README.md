# spotify2mp3

Turn a Spotify album or playlist into MP3s and copy them to bone-conduction headphones (or any player that mounts as a USB drive).

Spotify's own audio is DRM-protected, so this uses [spotDL](https://github.com/spotDL/spotify-downloader). spotDL reads the track list and metadata from Spotify, downloads the matching audio from YouTube Music, and encodes it to tagged MP3 with cover art. Use it only for music you have the right to keep, on your own devices.

## Setup

Requires Python 3.10+, ffmpeg and Deno (`brew install ffmpeg deno`). yt-dlp needs Deno to download some YouTube videos.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional, but recommended because spotDL's shared Spotify credentials often get rate-limited: create a free app at https://developer.spotify.com/dashboard and export its keys:

```sh
export SPOTIFY_CLIENT_ID=...
export SPOTIFY_CLIENT_SECRET=...
```

## Usage

```sh
# download, then copy to the plugged-in headphones (auto-detected under /Volumes)
python spotify2mp3.py https://open.spotify.com/playlist/...

# several at once, explicit device, eject when done
python spotify2mp3.py <url1> <url2> --device "/Volumes/SWIM PRO" --eject

# just download
python spotify2mp3.py https://open.spotify.com/album/... --no-copy
```

Files go to `output/<Playlist or Album>/<Artist> - <Title>.mp3`, and the same folder is created on the device.

Running the same URL again syncs it: only new tracks are downloaded, and tracks removed from the playlist are deleted locally. Add `--prune` to also delete them from the device.

| Option | Default | |
|---|---|---|
| `--out` | `./output` | local download folder |
| `--bitrate` | `192k` | MP3 bitrate (the YouTube source is about 128–160k, so higher only uses up space) |
| `--device` | auto-detect | mounted device path |
| `--no-copy` | | skip copying |
| `--prune` | | delete tracks on the device that are no longer in the playlist |
| `--eject` | | eject the device when done |

macOS junk files (`._*`, `.DS_Store`, `.Trashes`, …) are removed from the device after copying, so the headphones don't list them as broken tracks.

## When a track isn't found

Each track is searched on YouTube Music, then YouTube, then SoundCloud, then Bandcamp. Tracks that still fail are retried twice automatically, and anything left is listed under "not matched" in the summary. Running the command again retries just those tracks.
