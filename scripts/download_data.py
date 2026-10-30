"""Download the raw data listed in data/catalog.yaml and verify it.

Plain file downloads are checked against the sha256 recorded in the catalog.
SENAMHI station data comes from its interoperability API and needs SENAMHI_API_KEY
in .env (see .env.example); responses are stored as-is, one JSON file per station-month.

Usage:
    python scripts/download_data.py                   # download what is missing, verify everything
    python scripts/download_data.py --dataset dengue  # a single dataset
    python scripts/download_data.py --verify-only     # no downloads, only checks
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.yaml"
ENV_FILE = ROOT / ".env"
# The open data portal rejects some requests that lack a browser-like User-Agent.
USER_AGENT = "Mozilla/5.0 (academic project MAE-CDE-apache-spark)"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_env(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        # A missing file may come back as an HTML page instead of an HTTP error.
        if response.headers.get_content_type() == "text/html":
            raise ValueError("the URL returned an HTML page, not the file")
        with partial.open("wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
    partial.replace(target)


def check_file(entry: dict, verify_only: bool) -> bool:
    path = ROOT / entry["path"]
    if not path.exists():
        if verify_only:
            print(f"  MISSING    {entry['path']}")
            return False
        print(f"  fetching   {entry['path']} ...", flush=True)
        try:
            download_file(entry["url"], path)
        except (urllib.error.URLError, ValueError, TimeoutError) as error:
            print(f"  ERROR      {entry['path']}: {error}")
            return False

    actual = sha256(path)
    expected = entry.get("sha256")
    if expected is None:
        print(f"  NO SHA256  {entry['path']} -> record in the catalog:")
        print(f"             sha256: {actual}\n             bytes: {path.stat().st_size}")
        return False
    if actual != expected:
        print(f"  CHANGED    {entry['path']}: the source published a new version (sha256 {actual})")
        return False
    print(f"  ok         {entry['path']}")
    return True


class SenamhiApi:
    """Minimal read-only client for the SENAMHI interoperability API."""

    def __init__(self, base_url: str, api_key: str, requests_per_minute: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.interval = 60 / requests_per_minute
        self.last_call = 0.0

    def get(self, path: str, **params) -> bytes:
        url = self.base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"apikey": self.api_key, "Accept": "application/json", "User-Agent": USER_AGENT}
        request = urllib.request.Request(url, headers=headers)
        for attempt in range(1, 4):
            time.sleep(max(0.0, self.last_call + self.interval - time.monotonic()))
            self.last_call = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code != 429 or attempt == 3:
                    raise
            print("  rate limit reached, waiting 60 s ...", flush=True)
            time.sleep(60)


def save_api_response(path: Path, content: bytes) -> None:
    body = json.loads(content)
    if not body.get("status"):
        raise ValueError(body.get("message") or "the API returned status=false")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def month_range(start: str, end: str) -> list[str]:
    """Months from start to end (inclusive, 'YYYY-MM') as 'YYYYMM'."""
    year, month = map(int, start.split("-"))
    last = tuple(map(int, end.split("-")))
    months = []
    while (year, month) <= last:
        months.append(f"{year}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def check_senamhi(dataset: dict, verify_only: bool) -> bool:
    api = None
    if not verify_only:
        key = os.environ.get(dataset["api"]["key_env_var"])
        if not key:
            print(f"  ERROR      set {dataset['api']['key_env_var']} in .env (see .env.example)")
            return False
        api = SenamhiApi(dataset["api"]["base_url"], key, dataset["api"]["requests_per_minute"])

    wanted = month_range(dataset["period"]["start"], dataset["period"]["end"])
    all_ok = True
    for station in dataset["stations"]:
        code = station["code"]
        station_dir = ROOT / dataset["output_dir"] / code
        shown = station_dir.relative_to(ROOT)
        try:
            if api:
                for name, path in (("station.json", f"/stations/{code}"), ("periods.json", f"/stations/{code}/periods")):
                    if not (station_dir / name).exists():
                        save_api_response(station_dir / name, api.get(path))
            if not (station_dir / "periods.json").exists():
                print(f"  MISSING    {shown}/periods.json")
                all_ok = False
                continue

            published = {p["id"] for p in json.loads((station_dir / "periods.json").read_bytes())["data"]}
            months = [m for m in wanted if m in published]
            missing = [m for m in months if not (station_dir / f"{m}.json").exists()]
            if api:
                for month in missing:
                    print(f"  fetching   {shown}/{month}.json", flush=True)
                    save_api_response(station_dir / f"{month}.json", api.get(f"/stations/{code}/readings", period=month))
                missing = []
        except (urllib.error.URLError, OSError, ValueError) as error:
            print(f"  ERROR      {shown}: {error}")
            print("             A reset connection usually means your public IP is not registered in your SENAMHI account.")
            return False

        unpublished = len(wanted) - len(months)
        detail = f"{len(months)} months" + (f", {unpublished} not published by SENAMHI" if unpublished else "")
        if missing:
            print(f"  MISSING    {shown}: {len(missing)} of {detail}")
            all_ok = False
        else:
            print(f"  ok         {shown}: {detail}")
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", help="id of a single dataset to process (default: all)")
    parser.add_argument("--verify-only", action="store_true", help="do not download, only check")
    args = parser.parse_args()

    load_env(ENV_FILE)
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    datasets = [d for d in catalog["datasets"] if args.dataset in (None, d["id"])]
    if not datasets:
        print(f"Dataset '{args.dataset}' not found in {CATALOG.relative_to(ROOT)}")
        return 1

    all_ok = True
    for dataset in datasets:
        print(f"[{dataset['id']}] {dataset['name']}")
        if dataset.get("source") == "senamhi_api":
            all_ok &= check_senamhi(dataset, args.verify_only)
        else:
            for entry in dataset["files"]:
                all_ok &= check_file(entry, args.verify_only)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
