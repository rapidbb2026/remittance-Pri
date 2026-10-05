"""Readers for CSPro 8 data.

Two input formats are supported and both return the same thing: a list of
case dicts  {uuid, key, deleted, partial, vals: {ITEM_NAME: value}}.

1. read_csdb()       - a .csdb file (plain SQLite) as produced by the
                       DownloadData-*.pff sync on a PC.
2. read_sync_files() - the files CSPro itself keeps in Dropbox under
                       /CSPro/DataSync/<DICT_NAME>/data/. Each file is named
                       <device-id>$<uuid> and is a ZIP holding one JSON file
                       per interview. Layout taken from the CSPro 8.1 source
                       (zSyncO/FileBasedSyncService.cpp, zCaseO/CaseJsonSerializer.cpp).

Only the Python standard library is used.
"""
import io
import json
import re
import sqlite3
import zipfile

SYNC_FILE_RE = re.compile(r"^[0-9a-fA-F\-]+\$[0-9a-fA-F\-]{36}$")
CASE_META_KEYS = {"key", "uuid", "label", "deleted", "verified", "partialSave",
                  "caseNote", "notes", "clock", "position"}


def _clean(v):
    """Normalise one stored value: trim padded text, blank -> None."""
    if v is None:
        return None
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


# --------------------------------------------------------------------------
# .csdb (SQLite)
# --------------------------------------------------------------------------
def read_csdb(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    if "cases" not in tables or "level-1" not in tables:
        raise ValueError(f"{path}: not a CSPro .csdb file (is it an encrypted .csdbe?)")

    cases = {}
    l1_to_uuid = {}
    for r in con.execute(
        "select c.id, c.key, c.deleted, c.partial_save_mode, l.* "
        "from cases c join `level-1` l on l.`case-id` = c.id"
    ):
        d = dict(r)
        uuid = d.pop("id")
        mode = d.pop("partial_save_mode")
        case = {
            "uuid": uuid,
            "key": d.pop("key"),
            "deleted": bool(d.pop("deleted")),
            # CSPro stores 1 = add, 2 = modify, 3 = verify
            "partial": {"1": "add", "2": "modify", "3": "verify"}.get(str(mode)) if mode is not None else None,
            "vals": {},
        }
        l1 = d.pop("level-1-id")
        d.pop("case-id", None)
        for k, v in d.items():
            case["vals"][k.upper()] = _clean(v)
        cases[uuid] = case
        l1_to_uuid[l1] = uuid

    for t in tables:
        cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
        if t == "level-1" or "level-1-id" not in cols:
            continue
        seen = set()
        for r in con.execute(f'select * from "{t}" order by 1'):
            d = dict(r)
            l1 = d.pop("level-1-id")
            if l1 in seen or l1 not in l1_to_uuid:   # first occurrence only
                continue
            seen.add(l1)
            d.pop(f"{t}-id", None)
            vals = cases[l1_to_uuid[l1]]["vals"]
            for k, v in d.items():
                vals[k.upper()] = _clean(v)
    con.close()
    return list(cases.values())


# --------------------------------------------------------------------------
# CSPro Dropbox / FTP sync files
# --------------------------------------------------------------------------
def _code(node):
    """An item is written as {"code": value}; blank items are {} or absent."""
    if isinstance(node, list):          # multiply-occurring item: first one
        node = node[0] if node else None
    if isinstance(node, dict):
        v = node.get("code")
        if isinstance(v, (dict, list)):
            return None
        return _clean(v)
    return None


def _parse_case_json(obj):
    level = None
    for k, v in obj.items():
        if k not in CASE_META_KEYS and isinstance(v, dict):
            level = v
            break
    vals = {}
    if level:
        for name, node in level.items():
            if isinstance(node, list):
                occ = node[0] if node else None
                if isinstance(occ, dict) and "code" not in occ:
                    # a record: list of occurrences, each {ITEM: {"code": ..}}
                    for item, inode in occ.items():
                        vals[item.upper()] = _code(inode)
                    continue
            vals[name.upper()] = _code(node)
    ps = obj.get("partialSave")
    clock = {}
    for c in obj.get("clock") or []:
        if isinstance(c, dict):
            dev = c.get("deviceId") or c.get("device")
            if dev is not None:
                clock[dev] = c.get("revision", 0)
    return {
        "uuid": obj.get("uuid"),
        "key": obj.get("key"),
        "deleted": bool(obj.get("deleted")),
        "partial": (ps.get("mode") or "add") if isinstance(ps, dict) else None,
        "vals": vals,
        "_clock": clock,
    }


def _newer(a, b):
    """True if case version b should replace a (vector clock, else file time)."""
    ca, cb = a.get("_clock") or {}, b.get("_clock") or {}
    if ca or cb:
        devs = set(ca) | set(cb)
        b_ge = all(cb.get(d, 0) >= ca.get(d, 0) for d in devs)
        a_ge = all(ca.get(d, 0) >= cb.get(d, 0) for d in devs)
        if b_ge and not a_ge:
            return True
        if a_ge and not b_ge:
            return False
    return b["_mtime"] >= a["_mtime"]


def read_sync_files(files, log=print):
    """files: iterable of (name, modified_time, bytes). Returns merged cases."""
    cases = {}
    n_files = n_skipped = 0
    for name, mtime, blob in sorted(files, key=lambda f: (f[1], f[0])):
        base = name.rsplit("/", 1)[-1]
        if not SYNC_FILE_RE.match(base):
            continue
        n_files += 1
        if blob[:2] != b"PK":
            n_skipped += 1          # pre-8.1 (V2) upload: not supported here
            continue
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for member in z.namelist():
                if not member.endswith(".json") or member == "binary-data.json":
                    continue
                case = _parse_case_json(json.loads(z.read(member).decode("utf-8-sig")))
                if not case["uuid"]:
                    continue
                case["_mtime"] = mtime
                old = cases.get(case["uuid"])
                if old is None or _newer(old, case):
                    cases[case["uuid"]] = case
    if n_skipped:
        log(f"WARNING: {n_skipped} sync file(s) are in the old pre-8.1 format and were skipped.")
    log(f"  sync files read: {n_files}, interviews found: {len(cases)}")
    for c in cases.values():
        c.pop("_clock", None)
        c.pop("_mtime", None)
    return list(cases.values())


# --------------------------------------------------------------------------
# Dictionary (.dcf, CSPro 8 JSON)
# --------------------------------------------------------------------------
def read_dictionary(path):
    """Returns {name, level, items: {ITEM: {label, type, values: [(code, label)]}}}."""
    with open(path, encoding="utf-8-sig") as f:
        d = json.load(f)
    items = {}
    level = d["levels"][0]

    def add(it):
        values = []
        for vs in it.get("valueSets", [])[:1]:
            for v in vs.get("values", []):
                pair = v["pairs"][0]
                if "value" not in pair:
                    continue
                code = pair["value"]
                if isinstance(code, str):
                    code = code.strip()
                    if it.get("contentType") != "alpha":
                        try:
                            code = int(float(code))
                        except ValueError:
                            pass
                elif isinstance(code, float) and code.is_integer():
                    code = int(code)
                values.append((code, v["labels"][0]["text"].strip() if v.get("labels") else str(code)))
        items[it["name"].upper()] = {
            "label": it["labels"][0]["text"].strip(),
            "type": it.get("contentType", "numeric"),
            "values": values,
        }

    for it in level["ids"]["items"]:
        add(it)
    for rec in level["records"]:
        for it in rec["items"]:
            add(it)
    return {"name": d["name"], "level": level["name"], "items": items}
