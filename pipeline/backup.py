#!/usr/bin/env python3
"""Backup of the full survey data, locked with your backup password.

Every run makes remittance_backup_YYYY-MM-DD.zip, encrypts it with the BACKUP_PASSWORD secret
(AES-256-GCM, key from PBKDF2-SHA256) and puts it on the site as backup.bin, where the
"Download backup" button unlocks it in your browser. Once a day the same locked file is also kept
as the only asset of the GitHub release "latest-backup"; the previous day's file is removed.
The zip is
containing
  - <DICTIONARY>.csdb   the CSPro data files exactly as downloaded (open them in CSPro)
  - sync_files_<id>.zip every CSPro sync file found in Dropbox (the uploads made since the .csdb)
  - <id>_all_cases.csv / .dta  every interview of one questionnaire, combined from both of the above
  - combined_all_cases.csv / .dta  both questionnaires together, with a 'form' column
  - <DICTIONARY>.dcf    the dictionaries, to read the codes
The CSV and Stata files hold ALL cases: complete, partial, refused and deleted
(see the columns 'deleted' and 'partial'), with the original answer codes as stored by CSPro.
Stata files carry the question texts as variable labels and the answer options as value labels.

  python pipeline/backup.py                 # write the backup into ./backup only
  python pipeline/backup.py --encrypt site/backup.bin   # ...and lock it for the site (needs BACKUP_PASSWORD)
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from cspro_read import read_dictionary          # noqa: E402
import build                                    # noqa: E402

DHAKA = dt.timezone(dt.timedelta(hours=6))
META = ["form", "uuid", "case_key", "deleted", "partial"]


def dictionary_path(src, data_dir):
    p = os.path.join(data_dir, src["id"], "dictionary.dcf")
    if os.path.exists(p):
        return p
    p = os.path.join(ROOT, "dict", src["dictionary"] + ".dcf")
    return p if os.path.exists(p) else None


def frame(cases, src, items):
    import pandas as pd
    rows = []
    for c in cases:
        r = {"form": src["id"], "uuid": c["uuid"], "case_key": c.get("key") or "",
             "deleted": int(bool(c.get("deleted"))), "partial": c.get("partial") or ""}
        for k in items:
            r[k] = c["vals"].get(k)
        extra = [k for k in c["vals"] if k not in items]   # items no longer in the dictionary: keep them too
        for k in extra:
            r[k] = c["vals"][k]
        rows.append(r)
    df = pd.DataFrame(rows)
    cols = META + list(items) + [c for c in df.columns if c not in META and c not in items]
    return df.reindex(columns=cols)


def stata_name(n, used):
    s = re.sub(r"[^A-Za-z0-9_]", "_", n)[:32] or "v"
    if not re.match(r"[A-Za-z_]", s):
        s = ("v" + s)[:32]
    base, i = s, 1
    while s.lower() in used:
        i += 1
        s = f"{base[:29]}_{i}"
    used.add(s.lower())
    return s


def write_dta(df, items, path):
    import pandas as pd
    out = {}
    var_labels, value_labels, used = {}, {}, set()
    for col in df.columns:
        name = stata_name(col, used)
        meta = items.get(col)
        s = df[col]
        numeric = meta is not None and meta["type"] != "alpha"
        if numeric:
            num = pd.to_numeric(s, errors="coerce")
            out[name] = num
            codes = [(c, lab) for c, lab in (meta.get("values") or []) if isinstance(c, int) and not isinstance(c, bool)]
            if codes and num.dropna().apply(lambda x: float(x).is_integer()).all():
                if num.notna().any() and num.abs().max() < 2_000_000_000:
                    out[name] = num.astype("Int64").astype("float64")
                    value_labels[name] = {int(c): str(lab)[:32000] for c, lab in codes}
        elif col == "deleted":
            out[name] = s.astype("int8")
        else:
            out[name] = s.map(lambda x: "" if x is None or (isinstance(x, float) and x != x) else str(x))
        if meta:
            var_labels[name] = (meta.get("label") or col)[:80]
    out = pd.DataFrame(out, index=df.index)
    long_str = [c for c in out.columns if out[c].dtype == object and len(out) and out[c].map(len).max() > 2045]
    out.to_stata(path, write_index=False, version=118, variable_labels=var_labels,
                 value_labels=value_labels or None, convert_strl=long_str)


def make_backup(cfg, data_dir, out_dir):
    import pandas as pd
    today = dt.datetime.now(DHAKA).strftime("%Y-%m-%d")
    work = os.path.join(out_dir, f"remittance_backup_{today}")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    frames, all_items, summary = [], {}, []
    for src in cfg["sources"]:
        sid = src["id"]
        cases = build.load_source(src, data_dir, {})
        dpath = dictionary_path(src, data_dir)
        items = read_dictionary(dpath)["items"] if dpath else {}
        if dpath:
            shutil.copy(dpath, os.path.join(work, src["dictionary"] + ".dcf"))
        csdb = os.path.join(data_dir, f"{sid}.csdb")
        if os.path.exists(csdb):
            shutil.copy(csdb, os.path.join(work, src["dictionary"].lower() + ".csdb"))
        sync_dir = os.path.join(data_dir, sid, "sync")
        if os.path.isdir(sync_dir) and os.listdir(sync_dir):
            with zipfile.ZipFile(os.path.join(work, f"sync_files_{sid}.zip"), "w", zipfile.ZIP_DEFLATED) as z:
                for n in os.listdir(sync_dir):
                    z.write(os.path.join(sync_dir, n), n)
        df = frame(cases, src, items)
        df.to_csv(os.path.join(work, f"{sid}_all_cases.csv"), index=False, encoding="utf-8-sig")
        write_dta(df, items, os.path.join(work, f"{sid}_all_cases.dta"))
        frames.append(df)
        for k, v in items.items():                     # English question texts win in the combined file
            if k not in all_items or src["id"] == "en":
                all_items[k] = v
        summary.append(f"{src['label']}: {len(df)} cases ({int(df['deleted'].sum())} deleted, "
                       f"{int((df['partial'] != '').sum())} partial)")
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.to_csv(os.path.join(work, "combined_all_cases.csv"), index=False, encoding="utf-8-sig")
    write_dta(combined, all_items, os.path.join(work, "combined_all_cases.dta"))
    with open(os.path.join(work, "README.txt"), "w", encoding="utf-8") as f:
        f.write(f"Remittance Survey 2026 - backup made {dt.datetime.now(DHAKA):%Y-%m-%d %H:%M} (Dhaka)\n\n"
                + "\n".join(summary) + "\n\n" + (__doc__.split("containing", 1)[1].split("  python", 1)[0]))
    zpath = work + ".zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(os.listdir(work)):
            z.write(os.path.join(work, n), n)
    print(f"Backup written: {zpath} ({os.path.getsize(zpath) / 1024:.0f} KB)")
    for line in summary:
        print("  " + line)
    return zpath


def upload(zpath, folder):
    import fetch_dropbox as fd
    token = fd.access_token()
    name = os.path.basename(zpath)
    try:
        have = {e["name"] for e in fd.list_folder(token, folder)}
    except RuntimeError:
        have = set()
    if name in have:
        print(f"Today's backup is already in Dropbox ({folder}/{name}); nothing to do.")
        return
    import urllib.request
    req = urllib.request.Request(fd.CONTENT + "/files/upload", data=open(zpath, "rb").read(), headers={
        "Authorization": f"Bearer {token}",
        "Dropbox-API-Arg": json.dumps({"path": f"{folder}/{name}", "mode": "overwrite", "mute": True}),
        "Content-Type": "application/octet-stream"})
    try:
        fd._request(req)
    except RuntimeError as e:
        if "scope" in str(e) or "files.content.write" in str(e):
            sys.exit("Backup NOT uploaded: the Dropbox app is not allowed to write files. In the Dropbox App Console, "
                     "tick 'files.content.write' under Permissions, then make a new refresh token and update the "
                     "DROPBOX_REFRESH_TOKEN secret (README, step 2).\n" + str(e))
        raise
    print(f"Uploaded to Dropbox: {folder}/{name}")


def already_done_today(folder):
    import fetch_dropbox as fd
    name = f"remittance_backup_{dt.datetime.now(DHAKA):%Y-%m-%d}.zip"
    try:
        return name in {e["name"] for e in fd.list_folder(fd.access_token(), folder)}
    except Exception:
        return False


def encrypt(zpath, out_bin, password, summary):
    """AES-256-GCM; the page derives the same key with PBKDF2 and unlocks it in the browser."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv, iters = os.urandom(16), os.urandom(12), 310_000
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iters).derive(password.encode("utf-8"))
    blob = AESGCM(key).encrypt(iv, open(zpath, "rb").read(), None)
    with open(out_bin, "wb") as f:              # PRIB1 | salt 16 | iv 12 | iterations (4 bytes) | data
        f.write(b"PRIB1" + salt + iv + iters.to_bytes(4, "big") + blob)
    info = {"file": os.path.basename(zpath), "made": dt.datetime.now(DHAKA).strftime("%Y-%m-%d %H:%M"),
            "bytes": os.path.getsize(zpath), "summary": summary}
    with open(os.path.join(os.path.dirname(out_bin) or ".", "backup.json"), "w") as f:
        json.dump(info, f)
    print(f"Locked copy written: {out_bin} ({os.path.getsize(out_bin) / 1024:.0f} KB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--settings", default=os.path.join(ROOT, "config", "settings.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "backup"))
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--encrypt", default="", metavar="OUT.bin", help="lock the zip with BACKUP_PASSWORD for the site")
    ap.add_argument("--check", action="store_true", help="only check whether today's backup exists")
    args = ap.parse_args()
    cfg = json.load(open(args.settings, encoding="utf-8"))
    folder = cfg.get("backup", {}).get("dropbox_folder", "/PRI_Backups").rstrip("/")
    if args.check:                                  # exit 0 = today's backup is already in Dropbox
        sys.exit(0 if already_done_today(folder) else 1)
    if args.upload and already_done_today(folder):
        print("Today's backup is already in Dropbox; nothing to do.")
        return
    if args.encrypt and not os.environ.get("BACKUP_PASSWORD"):
        print("No BACKUP_PASSWORD secret yet, so no backup was made (README: Backup).")
        return
    zpath = make_backup(cfg, args.data_dir, args.out)
    if args.encrypt:
        encrypt(zpath, args.encrypt, os.environ["BACKUP_PASSWORD"], open(os.path.join(zpath[:-4], "README.txt"), encoding="utf-8").read().split("\n\n")[1])
    if args.upload:
        upload(zpath, folder)


if __name__ == "__main__":
    main()
