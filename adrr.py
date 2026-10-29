# /// script
# requires-python = ">=3.10"
# dependencies = ["requests", "pyyaml"]
# ///
"""Download the ADRR (R&D Data Archive) datasets from the PRISME data provision HMI.

Usage:
    uv run adrr.py                 # download everything not yet downloaded
    uv run adrr.py --list          # show what would be downloaded
    uv run adrr.py --match '2024*' # only paths matching a glob, e.g. 'FIR_*' or '*/Flights_*'
"""

import argparse
import fnmatch
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

ROOT = Path(__file__).parent
BACKEND_PATH = "/prisme_data_provision_backend"
RETRIES = 3


def load_config(path=ROOT / "credentials.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def login(cfg):
    """Return a requests.Session authenticated against the EUROCONTROL extranet."""
    base_url = cfg["adrr"]["base_url"]
    host = urlparse(base_url).netloc
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (adrr-download)"

    # Visiting the app first sets the cookies the login form expects.
    session.get(base_url)

    resp = session.post(
        f"https://{host}/auth4u/up",
        data={
            "login-form-type": "pwd",
            "am-eai-username": cfg["adrr"]["username"],
            "am-eai-password": str(cfg["adrr"]["password"]),
            "am-eai-referer": urlparse(base_url).path,
            "am-eai-environment": "ext",
            "am-eai-hostname": host,
            "am-eai-protocol": "https",
        },
    )
    resp.raise_for_status()

    check = session.get(base_url)
    if "auth4ulogin" in check.url or 'id="loginform"' in check.text:
        sys.exit("Login failed: check the username/password in credentials.yaml")
    return session


def is_login_page(resp):
    return "auth4ulogin" in resp.url or resp.headers.get("Content-Type", "").startswith("text/html")


class Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.backend = f"https://{urlparse(cfg['adrr']['base_url']).netloc}{BACKEND_PATH}"
        self.session = login(cfg)

    def relogin(self):
        self.session = login(self.cfg)

    def list_files(self):
        """Return all (non-directory) file entries in the archive."""
        resp = self.session.get(f"{self.backend}/files", headers={"Accept": "application/json"})
        resp.raise_for_status()
        files = []

        def walk(node):
            for child in node["dataFiles"]:
                if child["isDirectory"]:
                    walk(child)
                else:
                    files.append(child)

        walk(resp.json())
        return files

    def download(self, entry, dest):
        """Stream one file to dest, via a .part file so interrupted downloads are never mistaken for complete ones."""
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.session.post(f"{self.backend}/files/download", json=[entry], stream=True, timeout=(30, 300)) as resp:
            resp.raise_for_status()
            if is_login_page(resp):
                raise SessionExpired()
            with open(part, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        part.replace(dest)
        # Stamp with the server's modification time so updated files are detected on the next run.
        os.utime(dest, (entry["updatedAtTs"], entry["updatedAtTs"]))


class SessionExpired(Exception):
    pass


def is_up_to_date(entry, dest):
    return dest.exists() and dest.stat().st_mtime >= entry["updatedAtTs"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="only list the files that would be downloaded")
    parser.add_argument("--match", help="only files whose path matches this glob")
    args = parser.parse_args()

    cfg = load_config()
    output_dir = ROOT / cfg.get("download", {}).get("output_dir", "data")
    client = Client(cfg)

    files = client.list_files()
    if args.match:
        files = [f for f in files if fnmatch.fnmatch(f["formatedPath"], args.match)]
    todo = [f for f in files if not is_up_to_date(f, output_dir / f["formatedPath"])]
    print(f"{len(files)} files in archive, {len(files) - len(todo)} already downloaded, {len(todo)} to download")

    if args.list:
        for f in todo:
            print(f"  {f['formatedPath']}  ({f['size']})")
        return

    failed = []
    for i, entry in enumerate(todo, 1):
        dest = output_dir / entry["formatedPath"]
        print(f"[{i}/{len(todo)}] {entry['formatedPath']} ({entry['size']})", flush=True)
        for attempt in range(1, RETRIES + 1):
            try:
                client.download(entry, dest)
                break
            except (requests.RequestException, SessionExpired) as e:
                print(f"    attempt {attempt} failed: {e!r}", flush=True)
                if attempt == RETRIES:
                    failed.append(entry["formatedPath"])
                else:
                    time.sleep(5 * attempt)
                    client.relogin()

    if failed:
        print(f"\n{len(failed)} files failed (re-run to retry):")
        for path in failed:
            print(f"  {path}")
        sys.exit(1)
    print("\nAll done.")


if __name__ == "__main__":
    main()
