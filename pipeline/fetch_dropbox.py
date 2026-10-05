#!/usr/bin/env python3
"""Download the latest survey data from Dropbox into ./data.

Needs three environment variables (stored as GitHub secrets):
  DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN

settings.json -> fetch.mode chooses what is downloaded:
  "sync"  the files CSPro's own Dropbox sync keeps under
          /CSPro/DataSync/<DICTIONARY>/data/   (no PC needed)
  "csdb"  the two .csdb files from fetch.dropbox_csdb_folder
          (use this if a PC runs the DownloadData .pff files into a Dropbox folder)
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"


def _request(req, tries=5):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                time.sleep(int(e.headers.get("Retry-After", 2 ** attempt)))
                continue
            raise RuntimeError(f"Dropbox said {e.code}: {body[:400]}") from None
        except urllib.error.URLError:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def access_token():
    missing = [k for k in ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        sys.exit("Missing secrets: " + ", ".join(missing) + " (see README, step 2)")
    # same call as the SERWE dashboard's fetch script
    data = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": os.environ["DROPBOX_REFRESH_TOKEN"]}).encode()
    basic = base64.b64encode(f"{os.environ['DROPBOX_APP_KEY']}:{os.environ['DROPBOX_APP_SECRET']}".encode()).decode()
    req = urllib.request.Request("https://api.dropbox.com/oauth2/token", data=data, headers={"Authorization": "Basic " + basic})
    return json.loads(_request(req))["access_token"]


def rpc(token, endpoint, payload):
    req = urllib.request.Request(API + endpoint, data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return json.loads(_request(req))


def list_folder(token, path):
    res = rpc(token, "/files/list_folder", {"path": path, "recursive": False})
    entries = res["entries"]
    while res.get("has_more"):
        res = rpc(token, "/files/list_folder/continue", {"cursor": res["cursor"]})
        entries += res["entries"]
    return [e for e in entries if e[".tag"] == "file"]


def download(token, path, dest):
    req = urllib.request.Request(CONTENT + "/files/download", data=b"",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Dropbox-API-Arg": json.dumps({"path": path}),
                                          "Content-Type": "text/plain"})   # Dropbox wants an empty body here
    blob = _request(req)
    with open(dest, "wb") as f:
        f.write(blob)
    return len(blob)


def main():
    cfg = json.load(open(os.path.join(ROOT, "config", "settings.json"), encoding="utf-8"))
    fetch = cfg["fetch"]
    data_dir = os.path.join(ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    token = access_token()

    for src in cfg["sources"]:
        sid = src["id"]
        if fetch["mode"] == "csdb":
            path = fetch["dropbox_csdb_folder"].rstrip("/") + "/" + src["csdb"]
            size = download(token, path, os.path.join(data_dir, f"{sid}.csdb"))
            print(f"[{sid}] downloaded {path} ({size / 1024:.0f} KB)")
            continue

        folder = f"{fetch['dropbox_sync_root'].rstrip('/')}/{src['dictionary']}/data"
        try:
            entries = list_folder(token, folder)
        except RuntimeError as e:
            sys.exit(f"[{sid}] could not list {folder}\n{e}\n"
                     "Check that the token belongs to the Dropbox account the tablets sync to, "
                     "and that the app has 'Full Dropbox' access.")
        out = os.path.join(data_dir, sid, "sync")
        os.makedirs(out, exist_ok=True)
        manifest = {e["name"]: e["server_modified"] for e in entries}
        with ThreadPoolExecutor(8) as pool:
            sizes = list(pool.map(lambda e: download(token, e["path_lower"], os.path.join(out, e["name"])), entries))
        json.dump(manifest, open(os.path.join(data_dir, sid, "manifest.json"), "w"))
        print(f"[{sid}] downloaded {len(entries)} sync files from {folder} ({sum(sizes) / 1024:.0f} KB)")
        # the dictionary the tablets are using now (for interviewer and supervisor names)
        try:
            dfolder = f"{fetch['dropbox_sync_root'].rstrip('/')}/{src['dictionary']}/dict"
            dcf = next(e for e in list_folder(token, dfolder) if e["name"].lower().endswith(".dcf"))
            download(token, dcf["path_lower"], os.path.join(data_dir, sid, "dictionary.dcf"))
            print(f"[{sid}] downloaded the current dictionary")
        except Exception as e:                                   # not essential
            print(f"[{sid}] could not read the dictionary from Dropbox ({type(e).__name__}); using the copy in dict/")


if __name__ == "__main__":
    main()
