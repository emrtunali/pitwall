"""Run the site locally: sync the latest data, start a web server, open the browser."""

from __future__ import annotations

import functools
import http.server
import json
import threading
import webbrowser
from pathlib import Path

import httpx

LIVE = "https://emrtunali.github.io/pitwall"


def sync_from_site(site_dir: Path, year: int = 2026, base: str = LIVE) -> int:
    """Download any race the published site has and this copy lacks.

    The published site is rebuilt from OpenF1 every day by GitHub Actions, so this is the quickest way
    to get new races (seconds, instead of rebuilding from the API). Returns the number of races fetched.
    """
    out = site_dir / "data" / str(year)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        index = client.get(f"{base}/data/{year}/index.json")
        index.raise_for_status()
        remote = index.json()
        local_path = out / "index.json"
        local = json.loads(local_path.read_text()) if local_path.exists() else {}
        fresh = remote.get("updated_at") != local.get("updated_at")
        fetched = 0
        for race in remote["races"]:
            d = out / race["slug"]
            if (d / "race.json").exists() and (d / "positions.bin").exists() and not fresh:
                continue
            d.mkdir(parents=True, exist_ok=True)
            for name in ("race.json", "positions.bin"):
                r = client.get(f"{base}/data/{year}/{race['slug']}/{name}")
                r.raise_for_status()
                (d / name).write_bytes(r.content)
            fetched += 1
            print(f"  ↓ {race['name']}", flush=True)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        champ = client.get(f"{base}/data/{year}/championship.json")
        if champ.status_code == 200:
            (out / "championship.json").write_bytes(champ.content)
        local_path.write_text(index.text)
    return fetched


def serve(site_dir: Path, port: int = 8000, open_browser: bool = True) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site_dir))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Pitwall is running at {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
