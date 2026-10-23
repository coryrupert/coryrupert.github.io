#!/usr/bin/env python3
"""Build streaming-catalog.json from the TVMaze show index.

Pages https://api.tvmaze.com/shows?page=0 until the index ends. A show is
filed under the streaming service that matches its home outlet (web channel,
otherwise network). This is the show's home service, not every place it is
currently licensed.

Keep SERVICES in sync with StreamingService.all in
BingeYourself/Services/StreamingService.swift, and with the copy of this
script on coryrupert.github.io.
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

USER_AGENT = "BingeYourselfCatalog/1.0 (https://github.com/coryrupert/binge-yourself)"
PAUSE_SECONDS = 0.55
PAGE_CAP = 800

# id, aliases. First match wins, same order as StreamingService.all.
SERVICES = [
    ("netflix", ["netflix"]),
    ("hulu", ["hulu"]),
    ("disney-plus", ["disney plus"]),
    ("max", ["max", "hbo", "hbo max"]),
    ("prime-video", ["amazon prime video", "prime video", "amazon prime", "amazon video"]),
    ("apple-tv-plus", ["apple tv plus", "apple tv"]),
    ("peacock", ["peacock"]),
    ("paramount-plus", ["paramount plus", "paramount plus with showtime", "showtime"]),
    ("crunchyroll", ["crunchyroll"]),
    ("amc-plus", ["amc plus"]),
    ("shudder", ["shudder"]),
    ("mgm-plus", ["mgm plus", "epix"]),
    ("starz", ["starz"]),
    ("britbox", ["britbox", "brit box"]),
    ("espn-plus", ["espn plus"]),
    ("discovery-plus", ["discovery plus"]),
    ("criterion", ["criterion channel"]),
    ("dropout", ["dropout"]),
    ("youtube-premium", ["youtube premium"]),
]


def normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    folded = folded.lower().replace("+", " plus ").replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def service_id_for(outlet: str | None) -> str | None:
    if not outlet:
        return None
    key = normalize(outlet)
    if not key:
        return None
    for service_id, aliases in SERVICES:
        if key in aliases:
            return service_id
    return None


def outlet_name(show: dict) -> str | None:
    web = (show.get("webChannel") or {}).get("name")
    if isinstance(web, str) and web.strip():
        return web.strip()
    network = (show.get("network") or {}).get("name")
    if isinstance(network, str) and network.strip():
        return network.strip()
    return None


def poster(show: dict) -> str | None:
    image = show.get("image") or {}
    for key in ("medium", "original"):
        value = image.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def year_of(show: dict) -> str | None:
    premiered = show.get("premiered") or ""
    if isinstance(premiered, str) and len(premiered) >= 4 and premiered[:4].isdigit():
        return premiered[:4]
    return None


def entry(show: dict, channel: str) -> dict | None:
    title = show.get("name")
    show_id = show.get("id")
    if not isinstance(title, str) or not title.strip() or not isinstance(show_id, int):
        return None
    row = {"id": show_id, "t": title.strip(), "c": channel}
    year = year_of(show)
    if year:
        row["y"] = year
    image = poster(show)
    if image:
        row["p"] = image
    status = show.get("status")
    if isinstance(status, str) and status.strip():
        row["s"] = status.strip()
    return row


def fetch_page(page: int) -> list:
    url = f"https://api.tvmaze.com/shows?page={page}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    delay = PAUSE_SECONDS
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return []
            if error.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < 5:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    return []


def build() -> dict:
    buckets: dict[str, dict[int, dict]] = {service_id: {} for service_id, _ in SERVICES}
    unmatched: dict[str, int] = {}
    page = 0
    while page < PAGE_CAP:
        shows = fetch_page(page)
        if not shows:
            break
        for show in shows:
            channel = outlet_name(show)
            service_id = service_id_for(channel)
            if service_id is None or channel is None:
                if channel:
                    unmatched[channel] = unmatched.get(channel, 0) + 1
                continue
            row = entry(show, channel)
            if row is None:
                continue
            buckets[service_id][row["id"]] = row
        counts = ", ".join(f"{service_id}={len(rows)}" for service_id, rows in buckets.items() if rows)
        print(f"page {page}: {counts}", flush=True)
        page += 1
        time.sleep(PAUSE_SECONDS)

    services = {}
    for service_id, _ in SERVICES:
        rows = list(buckets[service_id].values())
        rows.sort(key=lambda row: (row["t"].casefold(), row["id"]))
        if rows:
            services[service_id] = rows
    print("unmatched outlets:", flush=True)
    for name, count in sorted(unmatched.items(), key=lambda item: (-item[1], item[0]))[:25]:
        print(f"  {count:5d}  {name}", flush=True)
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "services": services,
    }


def main() -> None:
    destination = sys.argv[1] if len(sys.argv) > 1 else "BingeYourself/Resources/streaming-catalog.json"
    catalog = build()
    payload = json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with open(destination, "wb") as handle:
        handle.write(payload)
        handle.write(b"\n")
    total = sum(len(rows) for rows in catalog["services"].values())
    print(f"wrote {total} shows across {len(catalog['services'])} services to {destination} ({len(payload)} bytes)", flush=True)


if __name__ == "__main__":
    main()
