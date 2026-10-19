"""Download the latest NHSBSA 'Pharmacy and appliance contractor dispensing data' files.

The portal runs CKAN, so we ask its API for the list of monthly files rather
than guessing URLs (each month has its own resource id). If the API call
fails we fall back to the June 2026 file, checked by hand on 19 Oct 2026.
"""
import re
from pathlib import Path

import requests

PACKAGE_ID = "25230765-9494-4fde-b3fc-af9c00037dfb"
API = "https://opendata.nhsbsa.net/api/3/action/package_show"
FALLBACK = {
    "202606": "https://opendata.nhsbsa.net/dataset/25230765-9494-4fde-b3fc-af9c00037dfb/resource/"
              "9ce852ed-0cba-47ee-b503-0117123ca3a8/download/dispensing_data_202606.csv",
}
MONTH_RE = re.compile(r"dispensing_data_(\d{6})\.csv", re.I)


def list_month_urls():
    r = requests.get(API, params={"id": PACKAGE_ID}, timeout=60)
    r.raise_for_status()
    urls = {}
    for res in r.json()["result"]["resources"]:
        m = MONTH_RE.search(res.get("url", "")) or MONTH_RE.search(res.get("name", ""))
        if m:
            urls[m.group(1)] = res["url"]
    if not urls:
        raise RuntimeError("API answered but listed no monthly CSVs")
    return urls


def download_latest(months, data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        urls = list_month_urls()
    except Exception as e:  # network, API change, etc.
        print(f"Couldn't list files from the NHS API ({e}). Using the June 2026 file only.")
        urls = FALLBACK

    chosen = sorted(urls, reverse=True)[:months]
    paths = []
    for month in chosen:
        path = data_dir / f"dispensing_data_{month}.csv"
        if not path.exists():
            print(f"Downloading {month}...")
            with requests.get(urls[month], stream=True, timeout=300) as r:
                r.raise_for_status()
                tmp = path.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                tmp.rename(path)
        else:
            print(f"Using saved file for {month}")
        paths.append((month, path))
    return paths
