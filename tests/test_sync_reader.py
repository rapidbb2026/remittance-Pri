#!/usr/bin/env python3
"""Self-check for the CSPro sync-file reader.

Takes a .csdb, rewrites its interviews in the layout CSPro uses in Dropbox
(/CSPro/DataSync/<DICT>/data/<device>$<uuid>, a ZIP with one JSON per interview),
reads that back and confirms it matches reading the .csdb directly.

  python tests/test_sync_reader.py path/to/file.csdb [path/to/dictionary.dcf]
"""
import io, json, os, sys, uuid, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))
from cspro_read import read_csdb, read_sync_files, read_dictionary

def to_sync_json(case, level_name, records):
    lvl = {"IDCODE": {"code": case["vals"].get("IDCODE")}}
    for rec, items in records.items():
        occ = {k: {"code": case["vals"][k]} for k in items if case["vals"].get(k) is not None}
        lvl[rec] = [occ]
    obj = {"key": case["key"], "uuid": case["uuid"], level_name: lvl, "clock": [{"deviceId": "dev1", "revision": 2}]}
    if case["deleted"]:
        obj["deleted"] = True
    if case["partial"]:
        obj["partialSave"] = {"mode": case["partial"], "name": "A1"}
    return obj

def main():
    csdb = sys.argv[1]
    cases = read_csdb(csdb)
    if len(sys.argv) > 2:
        d = json.load(open(sys.argv[2], encoding="utf-8-sig"))
        level = d["levels"][0]["name"]
        records = {r["name"]: [i["name"] for i in r["items"]] for r in d["levels"][0]["records"]}
    else:
        level = "LEVEL"
        records = {"ALL": sorted({k for c in cases for k in c["vals"] if k != "IDCODE"})}
    files = []
    # an older, stale copy of every interview first: the reader must keep the newer one
    for batch, stamp, rev in ((cases, "2026-01-01T00:00:00Z", 1), (cases, "2026-01-02T00:00:00Z", 2)):
        for i in range(0, len(batch), 25):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for c in batch[i:i + 25]:
                    obj = to_sync_json(c, level, records)
                    obj["clock"][0]["revision"] = rev
                    if rev == 1:
                        obj[level]["IDCODE"] = {"code": -1}
                    z.writestr(c["uuid"] + ".json", json.dumps(obj))
            files.append((f"aaaaaaaaaaaaaaaa${uuid.uuid4()}", stamp, buf.getvalue()))
    back = {c["uuid"]: c for c in read_sync_files(files, log=lambda *a: None)}
    assert len(back) == len(cases), (len(back), len(cases))
    for c in cases:
        b = back[c["uuid"]]
        assert b["deleted"] == c["deleted"] and b["partial"] == c["partial"], c["uuid"]
        a_vals = {k: v for k, v in c["vals"].items() if v is not None}
        b_vals = {k: v for k, v in b["vals"].items() if v is not None}
        assert a_vals == b_vals, (c["uuid"], set(a_vals.items()) ^ set(b_vals.items()))
    print(f"OK: {len(cases)} interviews read identically from both formats")

if __name__ == "__main__":
    main()
