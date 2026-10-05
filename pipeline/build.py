#!/usr/bin/env python3
"""Merge the Bangla and English survey data and write site/data.json.

Only counts, shares and summary statistics are written. No respondent-level
answers leave this script.

Usage
  python pipeline/build.py                       (reads ./data, as left by fetch_dropbox.py)
  python pipeline/build.py --csdb bn=a.csdb en=b.csdb   (run on your own PC)
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cspro_read import read_csdb, read_sync_files, read_dictionary  # noqa: E402
from spec import MODULES, CHANNELS, FORMAL, CURRENCIES              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DHAKA = dt.timezone(dt.timedelta(hours=6))


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------
# Loading and harmonising
# --------------------------------------------------------------------------
def load_source(src, data_dir, csdb_override):
    sid = src["id"]
    if sid in csdb_override:
        log(f"[{sid}] reading {csdb_override[sid]}")
        return read_csdb(csdb_override[sid])
    csdb = os.path.join(data_dir, f"{sid}.csdb")
    sync_dir = os.path.join(data_dir, sid, "sync")
    if os.path.exists(csdb):
        log(f"[{sid}] reading {csdb}")
        return read_csdb(csdb)
    if os.path.isdir(sync_dir):
        log(f"[{sid}] reading CSPro sync files in {sync_dir}")
        manifest = {}
        mpath = os.path.join(data_dir, sid, "manifest.json")
        if os.path.exists(mpath):
            manifest = json.load(open(mpath))
        files = []
        for name in os.listdir(sync_dir):
            p = os.path.join(sync_dir, name)
            with open(p, "rb") as f:
                files.append((name, manifest.get(name) or os.path.getmtime(p), f.read()))
        # manifest values are ISO strings, getmtime is a float: make them comparable
        files = [(n, m if isinstance(m, str) else dt.datetime.fromtimestamp(m, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), b)
                 for n, m, b in files]
        return read_sync_files(files, log)
    raise SystemExit(f"No data found for source '{sid}'. Expected {csdb} or {sync_dir}/")


def harmonise(cases, sid, dict_items, recodes):
    """Bring one source onto the common coding. Returns the non-deleted cases."""
    out, deleted = [], 0
    for c in cases:
        if c["deleted"]:
            deleted += 1
            continue
        v = c["vals"]
        for name, meta in dict_items.items():
            x = v.get(name)
            if x is None:
                continue
            if meta["type"] == "alpha":
                v[name] = str(x)
            elif not isinstance(x, (int, float)):
                try:
                    f = float(x)
                    v[name] = int(f) if f.is_integer() else f
                except (TypeError, ValueError):
                    v[name] = None            # CSPro special value (missing / refused)
        # answer codes that changed between versions of the forms (see settings.json)
        for name, mapping in recodes.items():
            if v.get(name) is not None and str(v[name]) in mapping:
                v[name] = mapping[str(v[name])]
        c["src"] = sid
        out.append(c)
    return out, deleted


def parse_date(x):
    try:
        s = str(int(x))
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return None


def derive(cases, cfg, today):
    """Adds status, converted amounts and quality flags to every case."""
    per_usd = cfg["rates_per_usd"]
    bdt = per_usd["BDT"]
    expected_cur = {int(k): v for k, v in cfg.get("country_currency", {}).items()}
    tol = cfg.get("rate_check_tolerance", 0.3)

    def usd(amount, cur):
        if amount is None or cur is None:
            return None
        code = cur if isinstance(cur, str) else CURRENCIES.get(cur)
        if code not in per_usd:
            return None
        return amount / per_usd[code]

    ids = Counter((c["src"], c["vals"].get("IDCODE")) for c in cases)
    for c in cases:
        v = c["vals"]
        agree = v.get("AGREE")
        if c["partial"] == "modify" and agree == 1:
            c["status"] = "reopened"
        elif c["partial"]:
            c["status"] = "partial"
        elif agree == 2:
            c["status"] = "refused"
        elif agree == 1:
            c["status"] = "complete"
        else:
            c["status"] = "partial"
        c["country"] = v.get("DES_COUNTRY_NAME")
        c["date"] = parse_date(v.get("INT_DATE"))

        m = {}
        for _, _, items in MODULES:
            for iid, typ, _, opt in items:
                if typ == "money":
                    cur = "BDT" if opt["currency"] == "BDT" else v.get(opt["currency"])
                    m[iid] = usd(v.get(opt["amount"]), cur)
        ch_cur = v.get(cfg.get("channel_amount_currency", "C3_CURRENCY"))
        for k, _ in CHANNELS:
            m["D1_" + k] = usd(v.get(f"D1_{k}_AMOUNT"), ch_cur) if v.get(f"D1_{k}_USED") == 1 else None
        c["usd"] = m

        y, mo = v.get("B1_01"), v.get("B1_02")
        v["B1_YEARS"] = None if y is None and mo is None else round((y or 0) + (mo or 0) / 12, 2)

        fee = None
        if v.get("D8_STATUS") == 2:
            fee = 0.0
        elif v.get("D8_STATUS") == 1:
            fee = m.get("D8")
        v["FEE_PCT"] = round(100 * fee / m["D6"], 3) if fee is not None and m.get("D6") else None

        d6, d7 = v.get("D6_AMOUNT"), v.get("D7_AMOUNT_BDT")
        c["implied_rate"] = d7 / d6 if d6 and d7 and v.get("D7_DK") == 1 else None

        flags = []
        if c["status"] != "refused":
            if ids[(c["src"], v.get("IDCODE"))] > 1:
                flags.append("dup")
            if c["date"] is None:
                flags.append("nodate")
            elif c["date"] > today:
                flags.append("future")
            if v.get("SUPERNAME") is None or v.get("INTNAME") is None:
                flags.append("nostaff")
            exp = expected_cur.get(c["country"])
            if exp is not None and any(v.get(k) not in (None, exp) for k in ("B9_02", "C3_CURRENCY", "D6_CURRENCY")):
                flags.append("currency")
            cur = CURRENCIES.get(v.get("D6_CURRENCY"))
            if c["implied_rate"] and cur in per_usd:
                ref = bdt / per_usd[cur]
                if abs(c["implied_rate"] / ref - 1) > tol:
                    flags.append("rate")
        c["flags"] = flags


# --------------------------------------------------------------------------
# Statistics helpers
# --------------------------------------------------------------------------
def quantile(s, q):
    if not s:
        return None
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def r(x, nd=2):
    if x is None:
        return None
    x = round(x, nd)
    return int(x) if float(x).is_integer() else x


def nice(x):
    if x <= 0:
        return 1
    e = math.floor(math.log10(x))
    f = x / 10 ** e
    for n in (1, 2, 2.5, 5, 10):
        if f <= n:
            return n * 10 ** e
    return 10 ** (e + 1)


def histogram(s):
    distinct = sorted(set(s))
    if all(float(x).is_integer() for x in distinct) and len(distinct) <= 14 and distinct[-1] - distinct[0] <= 14:
        cnt = Counter(s)
        return {"kind": "v", "bins": [[int(x), int(x), cnt.get(x, 0)] for x in range(int(distinct[0]), int(distinct[-1]) + 1)]}
    lo = 0 if s[0] >= 0 else s[0]
    hi = quantile(s, 0.95)
    if hi <= lo:
        hi = s[-1]
    if hi <= lo:
        return {"kind": "v", "bins": [[r(lo), r(lo), len(s)]]}
    step = nice((hi - lo) / 10)
    lo = math.floor(lo / step) * step
    nb = max(1, math.ceil((hi - lo) / step - 1e-9))
    counts = [0] * (nb + 1)
    for x in s:
        i = int((x - lo) // step)
        counts[min(max(i, 0), nb)] += 1
    bins = [[r(lo + i * step, 4), r(lo + (i + 1) * step, 4), counts[i]] for i in range(nb)]
    if counts[nb]:
        bins.append([r(lo + nb * step, 4), None, counts[nb]])
    return {"kind": "b", "bins": bins}


def num_summary(vals, min_n, total=False):
    s = sorted(x for x in vals if x is not None)
    n = len(s)
    if n == 0:
        return {"n": 0}
    if n < min_n:
        return {"n": n, "sup": True}
    out = {"n": n, "mean": r(sum(s) / n), "med": r(quantile(s, .5)), "p25": r(quantile(s, .25)),
           "p75": r(quantile(s, .75)), "min": r(s[0]), "max": r(s[-1]), "hist": histogram(s)}
    if total:
        out["sum"] = r(sum(s), 0)
    return out


def money_summary(usd_vals, bdt_rate, min_n):
    u = [x for x in usd_vals if x is not None]
    return {"USD": num_summary(u, min_n, True), "BDT": num_summary([x * bdt_rate for x in u], min_n, True)}


def share(num, den):
    return r(100 * num / den, 1) if den else None


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
LAST_CODES = {"96", "97", "98", "99", "X", "Z"}
FLAGS = {
    "dup": "Same ID code used twice",
    "nodate": "Interview date missing",
    "future": "Interview date in the future",
    "nostaff": "Supervisor or interviewer missing",
    "currency": "Currency does not match country",
    "rate": "Sent vs received amount looks wrong",
}

# numbers shown in "Descriptive statistics": (key, question, label, unit)
STATS = [
    ("A2", "A2", "Age", "years"), ("A7", "A7", "Family members in Bangladesh", "people"),
    ("A8", "A8", "Family members living with respondent", "people"),
    ("B1_YEARS", "B1", "Time in destination country", "years"),
    ("B6", "B6", "Days worked per week", "days"), ("B7", "B7", "Hours worked per day", "hours"),
    ("B9", "B9", "Total income last month", "money"), ("B10", "B10", "Living expenses per month", "money"),
    ("C2", "C2", "Times money was sent in 12 months", "times"),
    ("C3", "C3", "Total sent in 12 months", "money"),
    ("D6", "D6", "Amount sent, last transaction", "money"),
    ("D7", "D7", "Amount received in Bangladesh, last transaction", "money"),
    ("D8", "D8", "Fee paid by sender", "money"),
    ("FEE_PCT", "D8", "Sender fee as % of amount sent", "%"),
    ("D9", "D9", "Other direct costs", "money"), ("D12", "D12", "Fee paid by recipient", "money"),
    ("E11", "E11", "Separate fee for hundi transaction", "money"),
    ("E17", "E17", "Fee for advance-payment arrangement", "money"),
]


def staff_label(kind, code, names, show):
    if code is None:
        return "Not recorded"
    if show and code in names:
        return names[code].strip()
    return f"{kind} {int(code):02d}" if isinstance(code, (int, float)) else f"{kind} {code}"


UNTRANSLATED = set()


def clean_text(x):
    return re.sub(r"\s+", " ", re.sub(r"[\u200b-\u200f\ufeff]", "", str(x))).strip()


def text_top(values, aliases, limit=15):
    groups = defaultdict(Counter)
    for x in values:
        if not x:
            continue
        t = clean_text(x)
        if not t:
            continue
        key = t.casefold()
        if key in aliases:
            t = aliases[key]
            key = t.casefold()
        elif re.search(r"[\u0980-\u09ff]", t):      # Bangla with no English spelling in settings.json yet
            UNTRANSLATED.add(t)
            t, key = "Not yet translated", "not yet translated"
        elif t.islower():
            t = t.title()
        groups[key][t] += 1
    rows = sorted(((c.most_common(1)[0][0], sum(c.values())) for c in groups.values()), key=lambda x: (-x[1], x[0]))
    return rows[:limit]


CUR = ["GBP", "MYR", "USD", "AED", "SAR", "BDT"]
CUR_IDX = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, "BDT": 5}


def answer_cells(res, D, forms, day_of, country_of):
    """Counts per day x country x questionnaire for every choice question (the page adds them up)."""
    out = {}

    def add(key, group, question, label, multi, values, getter, sort=False, top=None):
        labels = [lab for _, lab in values]
        index = {str(c): i for i, (c, _) in enumerate(values)}
        cells = defaultdict(lambda: [0, Counter()])
        for c in res:
            got = getter(c["vals"])
            if not got:
                continue
            cell = cells[(day_of(c), country_of(c), forms.index(c["src"]))]
            cell[0] += 1
            for code in got:
                if code == "none":
                    continue
                if code not in index:
                    index[code] = len(labels)
                    labels.append(f"Code {code} (no label in dictionary)" if values else code)
                cell[1][index[code]] += 1
        if not values:                       # plain numbers such as years: keep them in order
            order = sorted(range(len(labels)), key=lambda i: labels[i])
            remap = {old: new for new, old in enumerate(order)}
            labels = [labels[i] for i in order]
            for cell in cells.values():
                cell[1] = Counter({remap[i]: n for i, n in cell[1].items()})
        last = [i for i, (c, _) in enumerate(values) if str(c) in LAST_CODES]
        out[key] = {"group": group, "question": question, "label": label, "multi": multi, "options": labels,
                    "sort": bool(sort), "top": top, "last": last,
                    "cells": [[d, k, f, n] + [x for pair in sorted(cnt.items()) for x in pair]
                              for (d, k, f), (n, cnt) in sorted(cells.items())]}

    for mid, mtitle, items in MODULES:
        group = f"{mid}. {mtitle}"
        for iid, typ, title, opt in items:
            if typ == "cat":
                vals = D[iid]["values"] if iid in D and not opt.get("numeric_codes") else []
                add(iid, group, iid.split("_")[0] if iid.startswith(("C8", "CB")) else iid.replace("_STATUS", "").replace("_DK", ""),
                    title, False, vals, lambda v, k=iid: [str(v[k])] if v.get(k) is not None else None,
                    opt.get("sort", False), 20 if opt.get("top") else None)
            elif typ == "multi":
                add(iid, group, iid, title, True, D[iid]["values"],
                    lambda v, k=iid: sorted(set(str(v[k]).replace(" ", ""))) if v.get(k) else None, opt.get("sort", False))
            elif typ == "channels":
                add("D1", group, "D1", title, True, CHANNELS,
                    lambda v: ([k for k, _ in CHANNELS if v.get(f"D1_{k}_USED") == 1] or ["none"]) if v.get("D1_01_USED") is not None else None)
            elif typ == "trust":
                for k, name in CHANNELS[:8]:
                    add(f"E2_{k}", group, f"E2.{int(k)}", f"Trust in: {name}", False, D[f"E2_{k}"]["values"],
                        lambda v, kk=f"E2_{k}": [str(v[kk])] if v.get(kk) is not None else None)
    return out


def number_rows(res, cfg, forms, day_of, country_of, n_countries):
    """Every number, one row per answer, so the page can filter by date and re-convert currencies.
    Row = [value, day, country, questionnaire] (+ [currency] for money, + fee details for the fee share)."""
    money = {iid: opt for _, _, items in MODULES for iid, typ, _, opt in items if typ == "money"}
    groups = {mid: f"{mid}. {t}" for mid, t, _ in MODULES}
    list_ids = cfg["privacy"].get("list_flagged_case_ids", True)
    out = {}
    for key, q, label, unit in STATS:
        rows, ids, usd = [], [], []
        for c in res:
            v = c["vals"]
            base = [day_of(c), country_of(c), forms.index(c["src"])]
            if unit == "money":
                opt = money[key]
                amt = v.get(opt["amount"])
                cur = CUR_IDX.get("BDT" if opt["currency"] == "BDT" else v.get(opt["currency"]))
                if amt is None or cur is None:
                    continue
                rows.append([amt] + base + [cur])
                usd.append(c["usd"][key])
            elif key == "FEE_PCT":
                if v.get("FEE_PCT") is None:
                    continue
                d6c = CUR_IDX.get(v.get("D6_CURRENCY"))
                paid = v.get("D8_STATUS") == 1
                rows.append([v.get("D8_AMOUNT") if paid else 0] + base + [CUR_IDX.get(v.get("D8_CURRENCY")) if paid else d6c, v.get("D6_AMOUNT"), d6c])
                usd.append(v["FEE_PCT"])
            else:
                if v.get(key) is None:
                    continue
                rows.append([v[key]] + base)
                usd.append(v[key])
            ids.append(v.get("IDCODE"))
        # ID codes are published only for outliers (all countries, or within a country)
        marks = {}
        if list_ids:
            for scope in [None] + list(range(n_countries)):
                sel = [i for i, row in enumerate(rows) if scope is None or row[2] == scope]
                vals = sorted(usd[i] for i in sel)
                if len(vals) < 4:
                    continue
                q1, q3 = quantile(vals, .25), quantile(vals, .75)
                lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
                for i in sel:
                    if (usd[i] < lo or usd[i] > hi) and ids[i] is not None:
                        marks[i] = str(ids[i])
        out[key] = {"group": groups[q[0]], "question": q, "label": label, "unit": unit, "rows": rows, "ids": marks}
    return out


def channel_rows(res, forms, country_of):
    out = []
    ccy = lambda c: CUR_IDX.get(c["vals"].get("C3_CURRENCY"))  # noqa: E731
    for k, _ in CHANNELS:
        out.append([[c["vals"][f"D1_{k}_AMOUNT"], ccy(c), country_of(c), c["vals"].get(f"D1_{k}_TIMES")] for c in res
                    if c["vals"].get(f"D1_{k}_USED") == 1 and c["vals"].get(f"D1_{k}_AMOUNT") is not None and ccy(c) is not None])
    return out


def view(sub, cfg, D, forms, today):
    """Everything the dashboard shows for one country selection."""
    min_n = cfg["privacy"]["min_n_for_statistics"]
    show = cfg["privacy"]["show_staff_names"]
    list_ids = cfg["privacy"].get("list_flagged_case_ids", True)
    bdt = cfg["rates_per_usd"]["BDT"]
    in_results = {"complete"} | ({"reopened"} if cfg.get("results_include_reopened", True) else set())
    res = [c for c in sub if c["status"] in in_results]
    V = [c["vals"] for c in res]
    countries = dict(D["DES_COUNTRY_NAME"]["values"])
    sup_names, int_names = dict(D["SUPERNAME"]["values"]), dict(D["INTNAME"]["values"])
    week_ago = today - dt.timedelta(days=6)

    def split(key_fn, cases=res):
        tot, by = Counter(), defaultdict(lambda: {f: 0 for f in forms})
        for c in cases:
            k = key_fn(c)
            if k is None:
                continue
            tot[k] += 1
            by[k][c["src"]] += 1
        return tot, by

    c_tot, c_by = split(lambda c: countries.get(c["country"], "Not recorded"))
    d_tot, d_by = split(lambda c: c["date"].isoformat() if c["date"] else None)
    days = sorted(d_tot)
    place_labels = dict(D["TYPE"]["values"])
    p_tot, p_by = split(lambda c: place_labels.get(c["vals"].get("TYPE")))
    r_labels = dict(D["RECR_METHOD"]["values"])
    r_tot, r_by = split(lambda c: r_labels.get(c["vals"].get("RECR_METHOD")))

    def staff(kind, field, names):
        rows = defaultdict(lambda: {"interviews": 0, "today": 0, "partial": 0, "flags": 0, "last": None})
        for c in sub:
            row = rows[staff_label(kind, c["vals"].get(field), names, show)]
            if c["status"] in in_results:
                row["interviews"] += 1
                if c["date"] == today:
                    row["today"] += 1
                if c["date"]:
                    d = c["date"].isoformat()
                    row["last"] = max(row["last"] or d, d)
            if c["partial"]:
                row["partial"] += 1
            row["flags"] += 1 if c["flags"] else 0
        return [{"name": k, **v} for k, v in sorted(rows.items(), key=lambda x: -x[1]["interviews"])]

    issues = []
    for c in sub:
        for f in c["flags"]:
            issues.append({"issue": FLAGS[f], "id": str(c["vals"].get("IDCODE") or "") if list_ids else "",
                           "enumerator": staff_label("Interviewer", c["vals"].get("INTNAME"), int_names, show),
                           "form": c["src"], "d": c["date"].isoformat() if c["date"] else ""})
    issues.sort(key=lambda x: x["d"], reverse=True)

    def pct(test, base):
        b = [v for v in V if base(v)]
        return {"p": share(sum(1 for v in b if test(v)), len(b)), "n": len(b)}

    def med(iid):
        s = sorted(c["usd"][iid] for c in res if c["usd"].get(iid) is not None)
        return {"v": r(quantile(s, .5)) if len(s) >= min_n else None, "n": len(s)}

    asked = lambda v: v.get("D1_01_USED") is not None  # noqa: E731
    used = lambda keys: (lambda v: any(v.get(f"D1_{k}_USED") == 1 for k in keys))  # noqa: E731
    fee = sorted(v["FEE_PCT"] for v in V if v.get("FEE_PCT") is not None)

    ch_rows, total_amt = [], 0.0
    for k, name in CHANNELS:
        users = [c for c in res if c["vals"].get(f"D1_{k}_USED") == 1]
        amts = sorted(c["usd"]["D1_" + k] for c in users if c["usd"].get("D1_" + k) is not None)
        times = sorted(c["vals"][f"D1_{k}_TIMES"] for c in users if c["vals"].get(f"D1_{k}_TIMES") is not None)
        total_amt += sum(amts)
        ch_rows.append({"label": name, "base": sum(1 for v in V if v.get(f"D1_{k}_USED") is not None), "used": len(users),
                        **{f: sum(1 for c in users if c["src"] == f) for f in forms},
                        "med": r(quantile(amts, .5)) if len(amts) >= min_n else None,
                        "times": r(quantile(times, .5)) if len(times) >= min_n else None, "_sum": sum(amts)})
    for row in ch_rows:
        s = row.pop("_sum")
        row["share"] = share(s, total_amt) if (row["used"] >= min_n or s == 0) else None

    trust = []
    for k, name in CHANNELS[:8]:
        cnt = Counter(str(v[f"E2_{k}"]) for v in V if v.get(f"E2_{k}") is not None)
        trust.append({"label": name, "n": sum(cnt.values()), "c": dict(cnt)})

    per_usd, rates = cfg["rates_per_usd"], []
    for code, cur in CURRENCIES.items():
        imp = sorted(c["implied_rate"] for c in res if c["vals"].get("D6_CURRENCY") == code and c["implied_rate"])
        hun = sorted(c["vals"]["E10_RATE_BDT"] for c in res
                     if (c["vals"].get("C3_CURRENCY") or c["vals"].get("D6_CURRENCY")) == code and c["vals"].get("E10_RATE_BDT"))
        if imp or hun:
            rates.append({"cur": cur, "ref": r(bdt / per_usd[cur]), "imp_n": len(imp), "imp": r(quantile(imp, .5)) if len(imp) >= min_n else None,
                          "hun_n": len(hun), "hun": r(quantile(hun, .5)) if len(hun) >= min_n else None})

    aliases = {clean_text(a).casefold(): b for a, b in cfg.get("aliases", {}).get("CITY", {}).items()}
    prov = {clean_text(a).casefold(): b for a, b in cfg.get("aliases", {}).get("D5_NAME", {}).items()}
    open_ok = cfg["privacy"].get("publish_open_text", [])
    return {
        "totals": {"interviews": len(res), "received": len(sub),
                   "today": sum(1 for c in res if c["date"] == today),
                   "last7": sum(1 for c in res if c["date"] and week_ago <= c["date"] <= today),
                   "refused": sum(1 for c in sub if c["status"] == "refused"),
                   "partial": sum(1 for c in sub if c["partial"]),          # same meaning as CSPro: any partly saved case
                   "reopened": sum(1 for c in sub if c["status"] == "reopened")},
        "form": {f: sum(1 for c in res if c["src"] == f) for f in forms},
        "form_total": {f: sum(1 for c in sub if c["src"] == f) for f in forms},
        "form_partial": {f: sum(1 for c in sub if c["src"] == f and c["partial"]) for f in forms},
        "country": dict(c_tot), "country_form": {k: v for k, v in c_by.items()},
        "timeline": {d: d_tot[d] for d in days}, "timeline_form": {d: d_by[d] for d in days},
        "city": text_top([v.get("CITY") for v in V], aliases) if "CITY" in open_ok else [],
        "providers": text_top([v.get("D5_NAME") for v in V], prov) if "D5_NAME" in open_ok else [],
        "place": {k: p_by[k] for k, _ in p_tot.most_common()},
        "recruit": {k: r_by[k] for k, _ in r_tot.most_common()},
        "enumerators": staff("Interviewer", "INTNAME", int_names),
        "supervisors": staff("Supervisor", "SUPERNAME", sup_names),
        "issues": issues[:300], "issues_total": len(issues),
        "kpi": {"sent12": pct(lambda v: v.get("C1") == 1, lambda v: v.get("C1") is not None),
                "formal": pct(used(FORMAL), asked), "hundi": pct(used(["06"]), asked), "carry": pct(used(["07", "08"]), asked),
                "aware": pct(lambda v: v.get("E3") == 1, lambda v: v.get("E3") is not None)},
        "channels": [{k: v for k, v in row.items() if k not in ("med", "share")} for row in ch_rows],
        "trust": trust, "rates": rates,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def compare_dictionaries(dicts):
    """Log any item whose answer codes differ between the forms."""
    ids = list(dicts)
    base = dicts[ids[0]]["items"]
    for other in ids[1:]:
        o = dicts[other]["items"]
        for name in sorted(set(base) | set(o)):
            if name not in base or name not in o:
                log(f"  NOTE {name}: only in one dictionary")
                continue
            a = {str(c) for c, _ in base[name]["values"]}
            b = {str(c) for c, _ in o[name]["values"]}
            if a != b and name not in ("SUPERNAME", "INTNAME"):
                log(f"  NOTE {name}: answer codes differ ({ids[0]} only: {sorted(a - b)}, {other} only: {sorted(b - a)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--out", default=os.path.join(ROOT, "site", "data.json"))
    ap.add_argument("--settings", default=os.path.join(ROOT, "config", "settings.json"))
    ap.add_argument("--csdb", nargs="*", default=[], metavar="ID=PATH")
    args = ap.parse_args()

    cfg = json.load(open(args.settings, encoding="utf-8"))
    override = dict(x.split("=", 1) for x in args.csdb)
    labels = read_dictionary(os.path.join(ROOT, cfg["labels_dictionary"]))
    D = labels["items"]

    dicts = {}
    for src in cfg["sources"]:
        p = os.path.join(ROOT, "dict", src["dictionary"] + ".dcf")
        if os.path.exists(p):
            dicts[src["id"]] = read_dictionary(p)
    if len(dicts) > 1:
        log("Comparing dictionaries")
        compare_dictionaries(dicts)

    # staff added after the dictionaries in dict/ were saved: take their names from the
    # dictionary the tablets use now (downloaded from Dropbox), English one first
    for sid in sorted((s["id"] for s in cfg["sources"]), key=lambda x: x != "en"):
        live = os.path.join(args.data_dir, sid, "dictionary.dcf")
        if not os.path.exists(live):
            continue
        try:
            items = read_dictionary(live)["items"]
        except Exception:
            continue
        for field in ("SUPERNAME", "INTNAME"):
            known = {c for c, _ in D[field]["values"]}
            for code, lab in items.get(field, {}).get("values", []):
                if code not in known and not re.search(r"[\u0980-\u09ff]", lab):
                    D[field]["values"].append((code, lab))
                    known.add(code)

    now = dt.datetime.now(DHAKA)
    cases, src_meta = [], []
    for src in cfg["sources"]:
        raw = load_source(src, args.data_dir, override)
        kept, deleted = harmonise(raw, src["id"], (dicts.get(src["id"]) or labels)["items"], cfg.get("recodes", {}))
        log(f"[{src['id']}] interviews: {len(kept)} (+{deleted} deleted, ignored)")
        cases += kept
        src_meta.append({"id": src["id"], "label": src["label"], "cases": len(kept), "deleted": deleted})
    derive(cases, cfg, now.date())

    forms = [s["id"] for s in cfg["sources"]]
    countries = D["DES_COUNTRY_NAME"]["values"]
    views = {"all": view(cases, cfg, D, forms, now.date())}
    for code, _ in countries:
        views[str(code)] = view([c for c in cases if c["country"] == code], cfg, D, forms, now.date())

    in_results = {"complete"} | ({"reopened"} if cfg.get("results_include_reopened", True) else set())
    res = [c for c in cases if c["status"] in in_results]
    days = sorted({c["date"].isoformat() for c in res if c["date"]})
    day_idx = {d: i for i, d in enumerate(days)}
    ctry_idx = {code: i for i, (code, _) in enumerate(countries)}
    day_of = lambda c: day_idx[c["date"].isoformat()] if c["date"] else -1   # noqa: E731
    country_of = lambda c: ctry_idx.get(c["country"], -1)                     # noqa: E731
    ans = answer_cells(res, D, forms, day_of, country_of)
    job_idx = {code: i for i, (code, _) in enumerate(D["B5"]["values"])}

    unlabelled = []
    for key, a in ans.items():
        for i, lab in enumerate(a["options"]):
            if "(no label in dictionary)" in lab:
                n = sum(cell[j + 1] for cell in a["cells"] for j in range(4, len(cell), 2) if cell[j] == i)
                unlabelled.append({"id": key, "label": lab, "n": n})
                log(f"  NOTE {key}: {lab} ({n} interviews)")
    for t in sorted(UNTRANSLATED):
        log(f"  NOTE typed answer still in Bangla, add an English spelling under aliases in settings.json: {t}")

    out = {
        "title": cfg.get("title", "Remittance Survey"),
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "forms": src_meta,
        "countries": [[str(c), lab] for c, lab in countries],
        "rates_per_usd": cfg["rates_per_usd"], "rates_note": cfg.get("rates_note", ""),
        "min_n": cfg["privacy"]["min_n_for_statistics"],
        "targets": {str(k): v for k, v in cfg.get("targets", {}).items() if v},
        "trust_labels": [[str(c), lab] for c, lab in D["E2_01"]["values"]],
        "unlabelled": unlabelled,
        "untranslated": len(UNTRANSLATED),
        "days": days, "currencies": CUR,
        "numbers": number_rows(res, cfg, forms, day_of, country_of, len(countries)),
        "answers": ans,
        "channel_amounts": channel_rows(res, forms, country_of),
        # sent and received for the same transaction, only where the respondent knew both
        "last_pairs": [[c["vals"]["D6_AMOUNT"], CUR_IDX[c["vals"]["D6_CURRENCY"]], c["vals"]["D7_AMOUNT_BDT"], country_of(c)] for c in res
                       if c["vals"].get("D6_AMOUNT") and c["vals"].get("D6_CURRENCY") in CUR_IDX and c["vals"].get("D7_AMOUNT_BDT") and c["vals"].get("D7_DK") == 1],
        "jobs": [lab for _, lab in D["B5"]["values"]],
        "income_by_job": [[c["vals"]["B9_01"], CUR_IDX[c["vals"]["B9_02"]], country_of(c), job_idx[c["vals"]["B5"]]] for c in res
                          if c["vals"].get("B9_01") is not None and c["vals"].get("B9_02") in CUR_IDX and c["vals"].get("B5") in job_idx],
        "views": views,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(os.path.dirname(args.out), "status.json"), "w") as f:
        json.dump({"checked": now.strftime("%Y-%m-%d %H:%M")}, f)
    log(f"Wrote {args.out} ({os.path.getsize(args.out) / 1024:.0f} KB), {len(cases)} interviews, {len(views)} country views")


if __name__ == "__main__":
    main()
