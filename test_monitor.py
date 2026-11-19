#!/usr/bin/env python3
"""Logix automatic tests: edge-case scenarios + the 30-truck test day.
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
    return {r["plate"]: sorted(k for k, _ in x if k != "INFO") for r, x in p}, [r["plate"] for r, _ in f], unk


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
        w = csv.DictWriter(fh, fieldnames=list(BASE) + ["status_for"], restval=""); w.writeheader(); w.writerows(rows)


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
    return "[HANDLED] ORD-9" in out and "[PROBLEM" not in out and "NEW1 at" not in out.split("[FREE TRUCKS]")[1]


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
    return ("new ETA 2026-11-18 11:00 = 1:30 after the FIX time" in out and "driver message language: Russian" in out
            and 'starting with: "Здравствуйте, Jonas!"' in out)


@test("S16 breaks use up Bed time -> daily rest needed (real-data case)")
def _():
    # 587 km = 8:23 driving < Bed 8:42, but + 0:45 break = 9:08 > Bed -> must take daily rest first
    from datetime import datetime
    e, txt = m.eta(datetime(2026, 11, 13, 19, 0), 587, m.hm("9:53"), m.hm("4:30"), m.hm("8:42"))
    return "+11:00 daily rest (Bed 8:42" in txt and e.strftime("%d %H:%M") == "14 14:23"


@test("S17 task without a task number is still a task (not a free truck)")
def _():
    k, f, _ = kinds([row(task_id="", task_time="2026-11-18 11:00", km_left="150")])
    return f == [] and k == {"T01": ["LATE"]}


@test("S18 less than 0:45 left -> REST_SOON warning; resting driver -> no warning")
def _():
    k, _, _ = kinds([row(bed="0:31", clock="0:33", task_time="2026-11-20 10:00", km_left="80"),
                     row(plate="T02", status="resting", bed="0:00", clock="0:10", task_time="2026-11-20 10:00")])
    return k == {"T01": ["REST_SOON"]}


@test("S19 free truck with unknown hours is never suggested as replacement")
def _():
    out = run_report([row(task_type="loading", goods_on_board="no", task_time="2026-11-18 10:30", km_left="150"),
                      free(plate="UNK", clock="unknown", cup="unknown", bed="unknown")])
    return "none free" in out and "check if the truck is in use" in out


@test("S20 free truck that must rest -> MUST_REST_NOW + 'MUST REST FIRST'")
def _():
    out = run_report([free(plate="F1", status="unknown", bed="0:00")])
    return "MUST_REST_NOW" in out and "MUST REST FIRST" in out


@test("S21 fixed priority order: MISSED_FIX, MUST_REST, LATE to FIX, other LATE (biggest first), REST_SOON")
def _():
    out = run_report([row(plate="LATE_SMALL", task_time="2026-11-18 11:00", km_left="120"),
                      row(plate="REST_SOON", bed="0:31", clock="0:33", task_time="2026-11-20 10:00", km_left="80"),
                      row(plate="LATE_BIG", task_time="2026-11-18 11:00", km_left="250"),
                      row(plate="LATE_FIX", task_fix="yes", task_time="2026-11-18 11:00", km_left="100"),
                      row(plate="REST_NOW", bed="0:00", task_time="2026-11-20 10:00"),
                      row(plate="MISSED", task_fix="yes", task_time="2026-11-18 09:00")])
    order = [l.split("] ")[1].split(" ")[0] for l in out.splitlines() if l.startswith("[PROBLEM ")]
    return order == ["MISSED", "REST_NOW", "LATE_FIX", "LATE_BIG", "LATE_SMALL", "REST_SOON"]


@test("S22 date-only task time (real LocTracker) -> no crash, deadline = end of that day")
def _():
    k, f, _ = kinds([row(task_time="2026-11-19", km_left="239")])
    out = run_report([row(task_time="2026-11-18", km_left="900")])
    return k == {} and f == [] and "LATE" in out and "date only" in out


@test("S23 at unloading address, FIX tomorrow, goods on board -> waiting, NOT free (real 18 Nov case)")
def _():
    rows = [row(status="resting", km_left="0", task_fix="yes", task_time="2026-11-19 07:00", bed="0:27", clock="1:47")]
    k, f, _ = kinds(rows)
    return k == {} and f == [] and "waiting for 19.11 07:00 FIX - not free" in run_report(rows)


@test("S24 at loading address, no next task -> ask dispatcher, NOT free (real 18 Nov case)")
def _():
    k, f, unk = kinds([row(task_type="loading", goods_on_board="unknown", km_left="0", task_time="2026-11-18", status="resting")])
    return k == {} and f == [] and any("NO unloading task" in u for u in unk)


@test("S25 resting > 11 h with open task -> STANDING (ask why, never guess); 10 h -> nothing")
def _():
    k, _, _ = kinds([row(status="resting", status_for="11:59", task_time="2026-11-19", km_left="239"),
                     row(plate="T02", status="resting", status_for="10:00", task_time="2026-11-19", km_left="239")])
    return k == {"T01": ["STANDING"]}


@test("S26 unknown driver language -> English + ask the dispatcher")
def _():
    out = run_report([row(driver="", driver_lang="unknown", bed="0:00", task_time="2026-11-20 10:00")])
    return 'UNKNOWN - write the driver\'s message in English, starting with: "Hello!"' in out and "SEPARATE line" in out


@test("S27 second check: ongoing-only problem -> one-line UPDATE; old CANNOT CHECK / free trucks not repeated")
def _():
    st = row(status="resting", status_for="11:06", task_time="2026-11-19", km_left="239")
    ld = row(plate="L1", task_type="loading", goods_on_board="unknown", km_left="0", task_time="2026-11-18", status="resting")
    fr = free(plate="F1")
    out = run_report([dict(st, status_for="11:59"), ld, fr], prev=[st, ld, fr])
    return ("ONGOING ONLY (STANDING)" in out and "replacement" not in out.split("[FREE")[0]
            and "[ONGOING - do not repeat] L1" in out and "[ONGOING - do not repeat] F1" in out)


# ---- 30-truck test day: expected problems per check ----
DAY = {
    "08-00": {"DEMO23": ["LATE"]},
    "08-30": {"DEMO23": ["LATE"]},
    "09-00": {"DEMO18": ["REST_SOON"], "DEMO23": ["LATE"]},
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
                block = out.split("] DEMO12")[1].split("[PROBLEM")[0]
                ok = ok and block.split("* ")[1].startswith("DEMO20")   # best replacement = DEMO20 in Kaunas
            return ok
        return fn
    TESTS.append((f"DAY {hhmm.replace('-', ':')} 30 trucks -> {', '.join(f'{p} {v[0]}' for p, v in exp.items())}", make()))


# ---- private real-data check (only where the real file exists, e.g. in Hermes; never on GitHub) ----
import csv as _csv, glob as _glob
for _exp_file in sorted(_glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "real_*", "expected.csv"))):
    REAL = os.path.dirname(_exp_file)
    for exp in _csv.DictReader(open(_exp_file, encoding="utf-8")):
        def make(exp=exp, REAL=REAL):
            def fn():
                rows = m.load(os.path.join(REAL, exp["file"]))
                k, f, unk = kinds(rows)
                plate, want = exp["plate"], exp["expect"]
                if want == "FREE":
                    return plate in f
                if want == "CANNOT_CHECK":
                    return any(u.startswith(plate) for u in unk)
                if want == "OK":
                    return plate not in k and plate not in f and not any(u.startswith(plate) for u in unk)
                return k.get(plate) == sorted(want.split("+"))
            return fn
        TESTS.append((f"REAL {os.path.basename(REAL)}/{exp['file']} {exp['plate']} -> {exp['expect']} ({exp['note']})", make()))


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
