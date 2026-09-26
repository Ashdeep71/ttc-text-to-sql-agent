import requests
from pathlib import Path

API = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show"
DATASETS = ["ttc-subway-delay-data", "ttc-bus-delay-data", "ttc-streetcar-delay-data"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUT = PROJECT_ROOT / "data" / "raw"


def download_all():
    for dataset in DATASETS:
        resp = requests.get(API, params={"id": dataset}, timeout=30)
        resp.raise_for_status()
        pkg = resp.json()["result"]

        for r in pkg["resources"]:
            # keep real uploaded Excel/CSV files, skip XML/JSON copies and datastore dumps
            if r.get("url_type") != "upload" or r["format"].upper() not in ("XLSX", "CSV"):
                continue

            filename = r["url"].split("/")[-1]
            target = OUT / dataset / filename
            target.parent.mkdir(parents=True, exist_ok=True)

            # "since-2025" files are refreshed monthly, so always re-download those
            if target.exists() and "since" not in filename:
                print("Skipping", filename)
                continue

            print("Downloading", filename)
            data = requests.get(r["url"], timeout=60)
            data.raise_for_status()
            target.write_bytes(data.content)


if __name__ == "__main__":
    download_all()