#!/usr/bin/env python3
"""Download Spotify albums/playlists as MP3 (via spotDL) and copy them to a USB music device."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from spotdl.types.song import Song
from spotdl.utils.formatter import create_file_name

FORMAT = "mp3"
# Tried in order per track; later providers catch songs the earlier ones can't find
AUDIO_PROVIDERS = ["youtube-music", "youtube", "soundcloud", "bandcamp"]
RETRIES = 2
URL_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?(album|playlist|track)/([A-Za-z0-9]+)")
JUNK_NAMES = {".DS_Store", ".Spotlight-V100", ".fseventsd", ".Trashes"}


def parse_url(url: str) -> tuple[str, str]:
    match = URL_RE.search(url)
    if not match:
        sys.exit(f"Not a Spotify album/playlist/track URL: {url}")
    return match.group(1), match.group(2)


def output_template(out_dir: Path, kind: str) -> str:
    folder = {"album": "{album}", "playlist": "{list-name}", "track": "Singles"}[kind]
    return str(out_dir / folder / "{artists} - {title}.{output-ext}")


def download(url: str, out_dir: Path, bitrate: str) -> tuple[Path, list[Path]]:
    """Run spotDL sync for one URL. Returns (folder, expected track paths)."""
    kind, spotify_id = parse_url(url)
    template = output_template(out_dir, kind)
    save_file = out_dir / ".sync" / f"{kind}-{spotify_id}.spotdl"
    save_file.parent.mkdir(parents=True, exist_ok=True)

    client_id, client_secret = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    creds = ["--client-id", client_id, "--client-secret", client_secret] if client_id and client_secret else []

    print(f"\n==> Downloading {kind} {url}")
    paths: list[Path] = []
    for attempt in range(1 + RETRIES):
        # First run creates the sync file; later runs sync from it (new tracks in, removed tracks out)
        # and only download tracks that aren't on disk yet, which makes them a cheap retry
        query = [str(save_file)] if save_file.exists() else [url, "--save-file", str(save_file)]
        cmd = [sys.executable, "-m", "spotdl", "sync", *query,
               "--output", template, "--format", FORMAT, "--bitrate", bitrate,
               "--audio", *AUDIO_PROVIDERS, *creds]
        result = subprocess.run(cmd)
        if result.returncode != 0 or not save_file.exists():
            print(f"!! spotDL failed for {url} (exit code {result.returncode})")
            return out_dir, []

        songs = json.loads(save_file.read_text(encoding="utf-8"))["songs"]
        paths = [create_file_name(Song.from_dict(s), template, FORMAT) for s in songs]
        missing = sum(not p.exists() for p in paths)
        if not missing or attempt == RETRIES:
            break
        print(f"\n==> Retrying {missing} missing track(s) (attempt {attempt + 2}/{1 + RETRIES})")

    folder = paths[0].parent if paths else out_dir
    return folder, paths


def find_device() -> Path | None:
    volumes = [
        v for v in sorted(Path("/Volumes").iterdir())
        if not v.name.startswith((".", "com.apple"))
        and os.path.ismount(v)
        and os.path.realpath(v) != "/"
    ]
    if not volumes:
        return None
    if len(volumes) == 1:
        return volumes[0]
    print("\nMultiple drives found:")
    for i, v in enumerate(volumes, 1):
        print(f"  {i}. {v}")
    choice = input("Copy to which drive? (number, or Enter to skip) ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(volumes):
        return volumes[int(choice) - 1]
    return None


def remove_junk(root: Path) -> int:
    """Delete macOS metadata files that headphones tend to list as broken tracks."""
    removed = 0
    for path in list(root.rglob("*")):
        if path.name in JUNK_NAMES or path.name.startswith("._"):
            try:
                shutil.rmtree(path) if path.is_dir() else path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def copy_to_device(tracks: list[Path], out_dir: Path, device: Path, prune_folders: set[Path]) -> int:
    pending = []
    for src in tracks:
        dest = device / src.relative_to(out_dir)
        if not (dest.exists() and dest.stat().st_size == src.stat().st_size):
            pending.append((src, dest))

    needed = sum(src.stat().st_size for src, _ in pending)
    free = shutil.disk_usage(device).free
    if needed > free:
        sys.exit(f"Not enough space on {device}: need {needed / 1e6:.0f} MB, {free / 1e6:.0f} MB free.")

    for i, (src, dest) in enumerate(pending, 1):
        print(f"  [{i}/{len(pending)}] {dest.relative_to(device)}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)

    # Remove tracks from the device that are no longer in the playlist
    wanted = {device / t.relative_to(out_dir) for t in tracks}
    for folder in prune_folders:
        device_folder = device / folder.relative_to(out_dir)
        for stale in device_folder.glob(f"*.{FORMAT}"):
            if stale not in wanted:
                print(f"  removing {stale.relative_to(device)}")
                stale.unlink()

    junk = remove_junk(device)
    if junk:
        print(f"  cleaned {junk} macOS metadata file(s)")
    return len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="Spotify album/playlist/track URLs")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "output", help="local download folder")
    parser.add_argument("--bitrate", default="192k", help="MP3 bitrate (default: 192k)")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--device", type=Path, help="mounted device path, e.g. /Volumes/SWIM PRO")
    target.add_argument("--no-copy", action="store_true", help="only download, don't copy to a device")
    parser.add_argument("--prune", action="store_true",
                        help="also delete tracks on the device that are no longer in the playlist")
    parser.add_argument("--eject", action="store_true", help="eject the device when done")
    args = parser.parse_args()

    out_dir = args.out.resolve()
    all_tracks, folders, missing = [], set(), []
    for url in args.urls:
        folder, paths = download(url, out_dir, args.bitrate)
        for p in paths:
            (all_tracks if p.exists() else missing).append(p)
        if paths and folder != out_dir / "Singles":
            folders.add(folder)

    copied, device = 0, None
    if not args.no_copy and all_tracks:
        device = args.device or find_device()
        if device and not device.is_dir():
            sys.exit(f"Device not found: {device}")
        if device:
            print(f"\n==> Copying to {device}")
            copied = copy_to_device(all_tracks, out_dir, device, folders if args.prune else set())

    print("\n==> Summary")
    print(f"  tracks ready:  {len(all_tracks)}  (in {out_dir})")
    if missing:
        print(f"  not matched:   {len(missing)}")
        for p in missing:
            print(f"    - {p.stem}")
    if device:
        print(f"  copied:        {copied} new to {device}")
        if args.eject:
            subprocess.run(["diskutil", "eject", str(device)])
        else:
            print(f'  eject with:    diskutil eject "{device}"')
    elif not args.no_copy and all_tracks:
        print("  no device found, skipped copying")


if __name__ == "__main__":
    main()
