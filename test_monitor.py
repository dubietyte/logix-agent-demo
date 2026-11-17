#!/usr/bin/env python3
"""Logix automatic tests: 12 edge-case scenarios + the 30-truck test day.
Run: python3 test_monitor.py   -> prints a PASS/FAIL table (takes about 1 second)
"""
import contextlib, io, os, shutil, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor as m

NOW = "2026-11-18 10:00"
BASE = dict(plate="T01", driver="Jonas", driver_lang="LT", location="Kaunas LT", lat="54.8985", lon="23.9036",
            status="driving", clock="8:00", cup="4:00", bed="10:00", task_id="ORD-1", task_type="unloading",
            task_address="Vilnius LT", task_lat="54.6872", task_lon="25.2797", task_time="2026-11-18 13:00",
            task_fix="no", client="Client A", goods_on_board="yes", km_left="100", next_task_time="", data_time=NOW)
FREE = dict(BASE, task_id="", task_type="", task_address="", task_lat="", task_lon="", task_time="", task_fix="",
            client="", goods_on_board="no", km_left="", status="resting")


def row(**kw):
    return dict(BASE, **kw)


def free(**kw):
    return dict(FREE, **kw)


def kinds(rows):
    p, f, ok, unk = m.check(rows)
    return {r["plate"]: sorted(k for k, _ in x) for r, x in p}, [r["plate"] for r, _ in f], unk


def run_report(rows, prev=None, decisions=None):
    d = tempfile.mkdtemp()
    try:
        m.set_dir(d)
        path = os.path.join(d, "fleet_now.csv")
        _write(path, rows)
        pp = None
        if prev:
            pp = os.path.join(d, "fleet_prev.csv"); _write(pp, prev)
        if decisions:
            with open(os.path.join(d, "decisions.csv"), "w") as fh:
                fh.write("task_id,new_plate,approved_at\n" + "".join(f"{a},{b},{c}\n" for a, b, c in decisions))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            m.report(path, pp)
        return out.getvalue()
    finally:
        shutil.rmtree(d)


def _write(path, rows):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(BASE)); w.writeheader(); w.writerows(rows)


TESTS = []


def test(name):
    def deco(fn):
        TESTS.append((name, fn)); return fn
    return deco


@test("S01 all trucks on time -> ALL OK")
def _():
    out = run_report([row(), row(plate="T02"), free(plate="F1")])
    return "STATUS: ALL OK" in out


@test("S02 late, goods on board -> LATE, no swap")
def _():
    out = run_report([row(task_time="2026-11-18 11:00", km_left="150"), free(plate="F1")])
    return "LATE [NEW]" in out and "NOT POSSIBLE (goods already" in out


@test("S03 FIX loading will be missed -> LATE + nearest free truck first")
def _():
    rows = [row(task_type="loading", task_fix="yes", goods_on_board="no", task_time="2026-11-18 11:00", km_left="150",
                task_lat="54.8985", task_lon="23.9036", task_address="Kaunas LT"),
            free(plate="FAR", location="Klaipeda LT", lat="55.7033", lon="21.1443"),
            free(plate="NEAR", location="Kaunas LT", lat="54.8985", lon="23.9036")]
    out = run_report(rows)
    cand = out.split("replacement candidates")[1]
    return "LATE [NEW]" in out and cand.index("NEAR") < cand.index("FAR")


@test("S04 FIX time already passed -> MISSED_FIX")
def _():
    k, _, _ = kinds([row(task_fix="yes", task_time="2026-11-18 09:30")])
    return k == {"T01": ["MISSED_FIX"]}


@test("S05 Bed 0:00 -> MUST_REST_NOW")
def _():
    k, _, _ = kinds([row(bed="0:00", task_time="2026-11-19 03:00")])
    return "MUST_REST_NOW" in k.get("T01", [])


@test("S06 Clock under 0:30 -> MUST_REST_NOW")
def _():
    k, _, _ = kinds([row(clock="0:20", task_time="2026-11-19 03:00")])
    return "MUST_REST_NOW" in k.get("T01", [])


@test("S07 must rest AND late -> both problems shown")
def _():
    k, _, _ = kinds([row(bed="0:00", task_time="2026-11-18 12:00")])
    return k == {"T01": ["LATE", "MUST_REST_NOW"]}


@test("S08 no free truck -> 'none free'")
def _():
    out = run_report([row(task_type="loading", goods_on_board="no", task_time="2026-11-18 10:30", km_left="150")])
    return "replacement candidates: none free" in out


@test("S09 unknown km / hours -> CANNOT CHECK, no crash, no guess")
def _():
    out = run_report([row(km_left="unknown", clock="unknown", cup="unknown", bed="unknown"),
                      row(plate="T02", task_fix="yes", task_time="2026-11-18 09:00", km_left="unknown")])
    return "[CANNOT CHECK]" in out and "T01" in out.split("[CANNOT CHECK]")[1] and "km left unknown" in out


@test("S10 free-truck rules (no task / next task >24h / next task <24h)")
def _():
    _, f, _ = kinds([free(plate="A"), free(plate="B", next_task_time="2026-11-19 14:00"),
                     free(plate="C", next_task_time="2026-11-18 13:00")])
    return f == ["A", "B"]


@test("S11 approved swap -> HANDLED, never suggested again, new truck busy")
def _():
    rows = [row(task_id="ORD-9", task_type="loading", task_fix="yes", goods_on_board="no", task_time="2026-11-18 09:00"),
            free(plate="NEW1")]
    out = run_report(rows, decisions=[("ORD-9", "NEW1", "09:30")])
    return "[HANDLED] ORD-9" in out and "[PROBLEM]" not in out and "NEW1 at" not in out.split("[FREE TRUCKS]")[1]


@test("S12 same problem in next check -> ONGOING (not NEW)")
def _():
    late = row(task_time="2026-11-18 11:00", km_left="150")
    out = run_report([late], prev=[late])
    return "LATE [ONGOING]" in out


@test("S13 long trip needs daily rest -> ETA includes 11 h rest")
def _():
    out = run_report([row(km_left="700", clock="5:00", bed="6:00", task_time="2026-11-18 20:00")])
    return "+11:00 daily rest" in out and "LATE" in out


@test("S14 must rest now -> new ETA for 11 h and 9 h rest shown")
def _():
    out = run_report([row(bed="0:00", km_left="140", task_time="2026-11-19 03:00")])
    return "11 h rest" in out and "2026-11-18 23:00" in out and "2026-11-18 21:00" in out


@test("S15 missed FIX -> new ETA shown; driver language spelled out")
def _():
    out = run_report([row(task_fix="yes", task_time="2026-11-18 09:30", km_left="70", driver_lang="RU")])
    return "new ETA 2026-11-18 11:00" in out and "driver message language: Russian" in out


# ---- 30-truck test day: expected problems per check ----
DAY = {
    "08-00": {"DEMO23": ["LATE"]},
    "08-30": {"DEMO23": ["LATE"]},
    "09-00": {"DEMO23": ["LATE"]},
    "09-30": {"DEMO07": ["LATE"], "DEMO12": ["LATE"], "DEMO18": ["MUST_REST_NOW"], "DEMO23": ["MISSED_FIX"]},
    "10-00": {"DEMO07": ["LATE"], "DEMO12": ["LATE"], "DEMO18": ["MUST_REST_NOW"], "DEMO23": ["MISSED_FIX"]},
    "10-30": {"DEMO07": ["LATE"], "DEMO12": ["MISSED_FIX"], "DEMO18": ["MUST_REST_NOW"], "DEMO23": ["MISSED_FIX"]},
    "11-00": {"DEMO07": ["LATE"], "DEMO18": ["MUST_REST_NOW"], "DEMO23": ["MISSED_FIX"]},
}
DAY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "day_test")
for hhmm, exp in DAY.items():
    def make(hhmm=hhmm, exp=exp):
        def fn():
            k, f, unk = kinds(m.load(os.path.join(DAY_DIR, f"fleet_{hhmm}.csv")))
            ok = k == exp and any("DEMO27" in u for u in unk) and "DEMO26" not in f
            if hhmm in ("09-30", "10-00"):
                out = run_report(m.load(os.path.join(DAY_DIR, f"fleet_{hhmm}.csv")))
                block = out.split("[PROBLEM] DEMO12")[1].split("[PROBLEM]")[0]
                ok = ok and block.split("* ")[1].startswith("DEMO20")   # best replacement = DEMO20 in Kaunas
            return ok
        return fn
    TESTS.append((f"DAY {hhmm.replace('-', ':')} 30 trucks -> {', '.join(f'{p} {v[0]}' for p, v in exp.items())}", make()))


if __name__ == "__main__":
    t0 = time.time(); fails = 0
    print(f"{'RESULT':7} TEST"); print("-" * 90)
    for name, fn in TESTS:
        try:
            ok = fn()
        except Exception as e:  # a crash is a failure
            ok = False; name += f"  (CRASH: {e})"
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL':7} {name}")
    print("-" * 90)
    print(f"{len(TESTS) - fails}/{len(TESTS)} passed in {time.time() - t0:.2f} s")
    sys.exit(1 if fails else 0)
