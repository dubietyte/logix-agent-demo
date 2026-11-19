#!/usr/bin/env python3
"""Logix fleet monitor - fast problem finder.

The script only does the maths (arrival times, driver hours, free trucks,
replacement candidates). The AI agent reads this output, decides what to do,
writes messages and asks the dispatcher for approval (see AGENTS.md,
section "Monitor and replan").

Usage:
  python3 monitor.py data/snapshots/fleet_14-30.csv
  python3 monitor.py data/snapshots/fleet_14-30.csv --prev data/snapshots/fleet_14-00.csv
  python3 monitor.py --next        # runs the next snapshot in order (demo mode)
  python3 monitor.py --reset       # start the demo again from the first snapshot
  python3 monitor.py --approve ORD-103 DEMO05 15:00   # save an approved swap
  python3 monitor.py --save-ai results/ai_09-30.json   # merge the AI's decisions + messages into the latest results file
  python3 monitor.py --decide DEMO12 swap approved 09:35   # save the dispatcher's answer (swaps also go to decisions.csv)
Every check is also saved for the Logix screen: <dir>/results/check_<date>_<HHMM>.json and <dir>/results/latest.json
  add  --dir data/day_test  to any command to use another snapshot folder (e.g. the 30-truck test day)
"""
import csv
import json
import re
import math
import os
import sys
from datetime import datetime, timedelta

AVG_KMH = 70            # average truck speed (same as AGENTS.md)
ROAD_FACTOR = 1.3       # straight line -> road km (rough, for replacements only)
BREAK_H = 0.75          # 45-min break
DAILY_REST_H = 11       # normal daily rest (9 h reduced possible)
LATE_LIMIT_MIN = 15     # report as late if more than this
REST_SOON_H = 0.75      # warn when less than 0:45 driving / Bed time is left
STANDING_H = 11         # resting longer than a normal daily rest with an open task -> ask why
SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "snapshots")
STATE_FILE = os.path.join(SNAP_DIR, ".last_check")
DECISIONS = os.path.join(SNAP_DIR, "decisions.csv")   # approved swaps: task_id,new_plate,approved_at


LANG = {"LT": "Lithuanian", "RU": "Russian", "PL": "Polish", "UA": "Ukrainian", "LV": "Latvian", "EN": "English", "DE": "German"}


GREET = {"LT": "Labas, {n}!", "RU": "Здравствуйте, {n}!", "PL": "Dzień dobry, {n}!", "UA": "Добрий день, {n}!",
         "LV": "Labdien, {n}!", "EN": "Hello, {n}!", "DE": "Guten Tag, {n}!"}


def greeting(r):
    lang = r["driver_lang"].strip().upper()
    name = r["driver"].strip() if r["driver"].strip().lower() not in ("", "unknown") else ""
    g = GREET.get(lang, "Hello, {n}!").format(n=name or "driver")
    return g.replace(", driver!", "!") if not name else g


def set_dir(path):
    global SNAP_DIR, STATE_FILE, DECISIONS
    base = os.path.dirname(os.path.abspath(__file__))
    SNAP_DIR = path if os.path.isabs(path) else os.path.join(base, path)
    STATE_FILE = os.path.join(SNAP_DIR, ".last_check")
    DECISIONS = os.path.join(SNAP_DIR, "decisions.csv")


def num(s):
    """'12.5' -> 12.5; '' or 'unknown' -> None"""
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def approved_swaps():
    """{task_id: (new_plate, approved_at)} - written by the agent after the dispatcher says yes."""
    out = {}
    if os.path.exists(DECISIONS):
        for r in csv.reader(open(DECISIONS, encoding="utf-8")):
            if len(r) >= 2 and r[0] != "task_id":
                out[r[0].strip()] = (r[1].strip(), r[2].strip() if len(r) > 2 else "")
    return out


def hm(s):
    """'4:30' -> 4.5 hours; '' or 'unknown' -> None"""
    s = (s or "").strip()
    if not s or s.lower() == "unknown":
        return None
    h, m = s.split(":")
    return int(h) + int(m) / 60


def fmt_h(x):
    m = int(round(x * 60))
    return f"{m // 60}:{m % 60:02d}"


def dt(s):
    """'2026-11-18 17:00' -> datetime. Date only ('2026-11-19', common in real LocTracker data)
    -> end of that day 23:59 (task can be done any time that day)."""
    s = (s or "").strip()
    if not s:
        return None
    if " " not in s:
        return datetime.strptime(s, "%Y-%m-%d").replace(hour=23, minute=59)
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def date_only(s):
    s = (s or "").strip()
    return bool(s) and " " not in s


def when(s, fmt_dt, ref):
    """Readable task time; date-only tasks say so."""
    if date_only(s):
        return f"{fmt_dt:%d.%m} (date only, no time)"
    return f"{fmt_dt:%H:%M}" if fmt_dt.date() == ref.date() else f"{fmt_dt:%d.%m %H:%M}"


def km_between(a_lat, a_lon, b_lat, b_lon):
    r = 6371
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x)) * ROAD_FACTOR


def eta(now, km, clock, cup, bed):
    """Arrival time with breaks and daily rest. Returns (eta, math_text).
    Clock = driving time left today; Bed = clock time until daily rest must START
    (breaks also use up Bed time)."""
    drive = km / AVG_KMH
    steps = [f"{km:.0f} km / {AVG_KMH} km/h = {fmt_h(drive)} driving"]
    need_break = cup is not None and drive > cup
    elapsed = drive + (BREAK_H if need_break else 0)
    over_clock = clock is not None and drive > clock
    over_bed = bed is not None and elapsed > bed
    total = drive
    if over_clock or over_bed:
        # daily rest also covers the break
        total += DAILY_REST_H
        why = (f"only {fmt_h(clock)} driving left today" if over_clock
               else f"Bed {fmt_h(bed)} < {fmt_h(elapsed)} driving{' + 0:45 break' if need_break else ''}")
        steps.append(f"+11:00 daily rest ({why}; with 9 h reduced rest ETA is 2:00 earlier)")
    elif need_break:
        total += BREAK_H
        steps.append(f"+0:45 break (Cup {fmt_h(cup)} < driving)")
    return now + timedelta(hours=total), "; ".join(steps)


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(rows):
    """Returns (problems, free_trucks, ok_trucks, cannot_check)."""
    problems, free, ok, unknown = [], [], [], []
    for r in rows:
        now = dt(r["data_time"])
        clock, cup, bed = hm(r["clock"]), hm(r["cup"]), hm(r["bed"])
        task_time = dt(r["task_time"])
        km_left = num(r["km_left"])
        nxt = dt(r["next_task_time"])
        plate = r["plate"]

        resting = r["status"].strip().lower() == "resting"
        must_rest = (not resting) and ((bed is not None and bed <= 0) or (clock is not None and clock < 0.5))

        # free truck rules (AGENTS.md); a task counts even without a task number (real LocTracker data)
        no_task = not (r["task_id"].strip() or r["task_type"].strip() or r["task_time"].strip())
        loading = r["task_type"].strip().lower() == "loading"
        waiting = task_time is not None and task_time > now          # booked time still ahead (e.g. FIX tomorrow)
        goods = r["goods_on_board"].strip().lower() == "yes"
        # at the last address = task done but not closed. NOT free if: loading (goods come on board next),
        # or waiting for a booked time, or goods still on board (real case 18 Nov: FIX unloading next morning)
        at_last = (km_left == 0 and not nxt and not loading and not waiting and not goods)
        if km_left == 0 and not nxt and loading and not no_task:
            unknown.append(f"{plate}: at the loading address ({r['task_address']}), NO unloading task in the queue - "
                           f"ask the dispatcher where it goes after loading (and mark loading done in LocTracker). Not a free truck.")
            continue
        far_next = no_task and nxt and (nxt - now) > timedelta(hours=24)
        if (no_task and not nxt) or far_next or at_last:
            note = "free"
            if at_last and not no_task:
                note = "free (at last address, close the task in LocTracker)"
            if far_next:
                note = f"free until {r['next_task_time']}"
            if clock is None and bed is None:
                note += " - driving hours unknown, check if the truck is in use"
            if must_rest:
                note += " - MUST REST FIRST"
                problems.append((r, [("MUST_REST_NOW", f"Bed {r['bed']}, Clock {r['clock']} - driver must stop now (no active task)")]))
            free.append((r, note))
            continue
        if no_task:
            ok.append(f"{plate}: no active task, next task {r['next_task_time']}")
            continue

        found = []
        rest_for = hm(r.get("status_for", ""))
        if resting and rest_for is not None and rest_for > STANDING_H and km_left and km_left > 0:
            found.append(("STANDING", f"resting {r['status_for']} (longer than an 11 h daily rest) with an open task and "
                          f"{km_left:.0f} km to go - ask the dispatcher why (weekly rest? border queue? waiting?). Do not guess the reason."))
        # must rest now
        if must_rest:
            txt = f"Bed {r['bed']}, Clock {r['clock']} - driver must stop now"
            if km_left is not None and task_time:
                d = km_left / AVG_KMH
                e11 = now + timedelta(hours=DAILY_REST_H + d)
                e9 = now + timedelta(hours=9 + d)
                txt += (f". New ETA if rest starts now: {e11:%Y-%m-%d %H:%M} (11 h rest) / {e9:%Y-%m-%d %H:%M} (9 h reduced rest)"
                        f" vs {r['task_type']} {r['task_time']}. Math: rest + {km_left:.0f} km / {AVG_KMH} km/h = {fmt_h(d)} driving")
            found.append(("MUST_REST_NOW", txt))
        elif not resting and min(x for x in (clock, bed, 99) if x is not None) < REST_SOON_H:
            left = min(x for x in (clock, bed) if x is not None)
            found.append(("REST_SOON", f"only {fmt_h(left)} left before the driver must rest (Clock {r['clock']}, Bed {r['bed']}) - plan a safe parking place now"))
        # missed FIX
        if r["task_fix"].lower() == "yes" and task_time and now > task_time:
            late_h = (now - task_time).total_seconds() / 3600
            left_txt = f"{km_left:.0f} km left" if km_left is not None else "km left unknown"
            if km_left is not None:
                e, math_txt = eta(now, km_left, clock, cup, bed)
                total_late = (e - task_time).total_seconds() / 3600
                left_txt += (f", new ETA {e:%Y-%m-%d %H:%M} = {fmt_h(total_late)} after the FIX time "
                             f"(tell the client this full delay, not only the time already passed). Math: {math_txt}")
            found.append(("MISSED_FIX", f"FIX {r['task_type']} {r['task_time']} passed {fmt_h(late_h)} ago, task still open, {left_txt}"))
        elif task_time and km_left is not None:
            e, math_txt = eta(now, km_left, clock, cup, bed)
            late_min = (e - task_time).total_seconds() / 60
            dnote = " (date only, so deadline = end of that day)" if date_only(r["task_time"]) else ""
            if late_min > LATE_LIMIT_MIN:
                found.append(("LATE", f"ETA {e:%Y-%m-%d %H:%M} vs {r['task_type']} {r['task_time']}{' FIX' if r['task_fix'].lower()=='yes' else ''}{dnote} -> {fmt_h(late_min/60)} late. Math: {math_txt}"))
            else:
                fmt = "%H:%M" if e.date() == now.date() else "%d.%m %H:%M"
                line = f"{plate}: on time (ETA {e:{fmt}}, {r['task_type']} {when(r['task_time'], task_time, now)})"
                if km_left == 0 and waiting:
                    line = f"{plate}: already at the {r['task_type']} address, waiting for {when(r['task_time'], task_time, now)}{' FIX' if r['task_fix'].lower()=='yes' else ''} - not free"
                if found:
                    found.append(("INFO", line.split(": ", 1)[1]))
                else:
                    ok.append(line)
        if not found and task_time and (km_left is None or (clock is None and bed is None)):
            miss = [k for k in ("km_left", "clock", "bed") if num(r[k]) is None and hm(r[k]) is None] if km_left is None \
                else [k for k in ("clock", "cup", "bed") if hm(r[k]) is None]
            unknown.append(f"{plate} ({r['task_id']} {r['task_type']} {r['task_time']}): cannot check, unknown {', '.join(miss)} - ask the dispatcher")
        if found and any(k != "INFO" for k, _ in found):
            problems.append((r, found))
    return problems, free, ok, unknown


def priority(item):
    """Fixed order for the dispatcher: MISSED_FIX, MUST_REST_NOW, LATE to a FIX time,
    other LATE (biggest delay first), REST_SOON."""
    r, found = item
    best = (9, 0)
    for kind, txt in found:
        if kind == "MISSED_FIX":
            k = (0, 0)
        elif kind == "MUST_REST_NOW":
            k = (1, 0)
        elif kind == "LATE":
            mm = re.search(r"-> (\d+):(\d\d) late", txt)
            delay = int(mm.group(1)) * 60 + int(mm.group(2)) if mm else 0
            k = (2 if r["task_fix"].lower() == "yes" else 3, -delay)
        elif kind == "REST_SOON":
            k = (4, 0)
        else:   # STANDING, INFO
            k = (5, 0)
        best = min(best, k)
    return best


def replacements(task_row, free):
    """Free trucks that could reach the task address, best first."""
    out = []
    for r, note in free:
        if r["plate"] == task_row["plate"]:
            continue
        if None in (num(r["lat"]), num(r["lon"]), num(task_row["task_lat"]), num(task_row["task_lon"])):
            continue  # location unknown -> never guess
        if hm(r["clock"]) is None and hm(r["bed"]) is None:
            continue  # driving hours unknown -> never suggest
        km = km_between(float(r["lat"]), float(r["lon"]), float(task_row["task_lat"]), float(task_row["task_lon"]))
        now = dt(r["data_time"])
        e, _ = eta(now, km, hm(r["clock"]), hm(r["cup"]), hm(r["bed"]))
        out.append((e, km, r))
    out.sort(key=lambda x: x[0])
    return out[:3]


def report(path, prev_path=None):
    rows = load(path)
    prev_keys, prev_unknown, prev_free = set(), set(), set()
    if prev_path and os.path.exists(prev_path):
        pp, pf, _, pu = check(load(prev_path))
        for r, found in pp:
            for kind, _ in found:
                prev_keys.add((r["plate"], kind))
        prev_unknown = {u.split(" ")[0].rstrip(":") for u in pu}
        prev_free = {r["plate"] for r, _ in pf}

    problems, free, ok, unknown = check(rows)
    swaps = approved_swaps()
    busy = {p for p, _ in swaps.values()}
    free = [(r, n) for r, n in free if r["plate"] not in busy]
    handled = [(r, f) for r, f in problems if r["task_id"] in swaps]
    problems = [(r, f) for r, f in problems if r["task_id"] not in swaps]
    problems.sort(key=priority)
    res = new_result(rows, path)
    print(f"=== FLEET CHECK  data_time {rows[0]['data_time']}  file {os.path.basename(path)} ===")
    if not problems:
        print("STATUS: ALL OK - nothing to report to the dispatcher.")
    else:
        print(f"STATUS: {len(problems)} truck(s) with problems")
    for n, (r, found) in enumerate(problems, 1):
        item = problem_item(n, r, found, prev_keys)
        res["problems"].append(item)
        print(f"\n[PROBLEM {n} of {len(problems)}] {r['plate']} (driver {r['driver'].strip() or 'name not given'}, lang {r['driver_lang']}) at {r['location']}")
        if r["driver_lang"].strip().upper() in LANG:
            print(f"  driver message language: {LANG[r['driver_lang'].strip().upper()]} - write this driver's message ONLY in this language, "
                  f"starting with: \"{greeting(r)}\"")
        else:
            print(f"  driver message language: UNKNOWN - write the driver's message in English, starting with: \"{greeting(r)}\", "
                  f"(the quoted message stays English only). Ask the dispatcher about the language on a SEPARATE line: \"Question for you: which language does the driver speak?\"")
        if not (r["task_type"].strip() or r["task_time"].strip()):
            print("  no active task (free truck)")
            for kind, txt in found:
                tag = "ONGOING" if (r["plate"], kind) in prev_keys else "NEW"
                print(f"  - {kind} [{tag}]: {txt}")
            continue
        if all(k == "INFO" or (r["plate"], k) in prev_keys for k, _ in found):
            kinds_txt = ", ".join(k for k, _ in found if k != "INFO")
            print(f"  ONGOING ONLY ({kinds_txt}) -> write ONE line: \"UPDATE {r['plate']}: <what changed>, plan unchanged.\" "
                  f"No decision block, no messages, no Approve. Skip it if nothing important changed.")
            for kind, txt in found:
                print(f"  - {'info' if kind == 'INFO' else kind + ' [ONGOING]'}: {txt}")
            continue
        print(f"  task {r['task_id'] or '(no number)'}: {r['task_type']} at {r['task_address']} for client {r['client']}, goods on board: {r['goods_on_board']}")
        for kind, txt in found:
            if kind == "INFO":
                print(f"  - info: {txt}")
                continue
            tag = "ONGOING" if (r["plate"], kind) in prev_keys else "NEW"
            print(f"  - {kind} [{tag}]: {txt}")
        if r["goods_on_board"].lower() == "yes":
            print("  replacement: NOT POSSIBLE (goods already on this truck) -> options: keep truck, inform client")
        else:
            reps = replacements(r, free)
            item["replacements"] = [rep_item(e, km, rr) for e, km, rr in reps]
            if reps:
                print("  replacement candidates (free trucks):")
                for e, km, rr in reps:
                    efmt = "%H:%M" if e.date() == dt(r["data_time"]).date() else "%d.%m %H:%M"
                    print(f"    * {rr['plate']} at {rr['location']}: ~{km:.0f} km, ETA {e:{efmt}}, Clock {rr['clock']}, Bed {rr['bed']}, "
                          f"driver {rr['driver']}, language {LANG.get(rr['driver_lang'].upper(), rr['driver_lang'])} (message starts: \"{greeting(rr)}\")")
            else:
                print("  replacement candidates: none free")
    for r, f in handled:
        newp, when = swaps[r["task_id"]]
        res["handled"].append({"task_id": r["task_id"], "from_plate": r["plate"], "to_plate": newp, "approved_at": when})
        print(f"\n[HANDLED] {r['task_id']} already moved from {r['plate']} to {newp} (approved {when}). "
              f"Do not suggest it again. {r['plate']} is free for another job; {newp} is busy with {r['task_id']}.")
    print("\n[FREE TRUCKS]")
    for r, note in free or []:
        tag = "[ONGOING - do not repeat]" if r["plate"] in prev_free else "[NEW]"
        print(f"  {tag} {r['plate']} at {r['location']} - {note} (Clock {r['clock']}, Bed {r['bed']})")
    if not free:
        print("  none")
    if unknown:
        print("\n[CANNOT CHECK] (data missing - do not guess, ask the dispatcher)")
        for line in unknown:
            tag = "[ONGOING - do not repeat]" if line.split(" ")[0].rstrip(":") in prev_unknown else "[NEW]"
            print(f"  {tag} {line}")
    print("\n[OK]  (one short line per truck; skip trucks already reported OK in the last check)")
    for line in ok:
        print("  " + line)
    res["free"] = [{"plate": r["plate"], "location": r["location"], "note": note, "clock": r["clock"], "bed": r["bed"]} for r, note in free]
    res["cannot_check"] = list(unknown)
    res["ok"] = list(ok)
    res["counts"] = {"trucks": len(rows), "problems": len(problems), "handled": len(handled), "free": len(free),
                     "cannot_check": len(unknown), "ok": len(rows) - len(problems) - len(handled) - len(unknown)}
    saved = save_result(res)
    if saved:
        print(f"\n[RESULTS FILE] {saved}")



# ---------------------------------------------------------------------------
# Results file for the Logix screen (website). The text above is for the chat,
# the JSON below is the same check in a form a web page can read.
# ---------------------------------------------------------------------------
STATUS_ORDER = ["MISSED_FIX", "MUST_REST_NOW", "LATE", "STANDING", "REST_SOON"]


def iso(x):
    return x.strftime("%Y-%m-%d %H:%M") if x else None


def results_dir():
    return os.path.join(SNAP_DIR, "results")


def new_result(rows, path):
    return {"version": 1, "data_time": rows[0]["data_time"] if rows else None, "file": os.path.basename(path),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "problems": [], "handled": [], "free": [], "cannot_check": [], "ok": [], "counts": {}}


def facts(r, found):
    """Numbers the screen shows in boxes (same maths as the text lines)."""
    now = dt(r["data_time"])
    km_left, task_time = num(r["km_left"]), dt(r["task_time"])
    clock, cup, bed = hm(r["clock"]), hm(r["cup"]), hm(r["bed"])
    kinds = [k for k, _ in found]
    out = {"km_left": km_left}
    if task_time and km_left is not None:
        e, math_txt = eta(now, km_left, clock, cup, bed)
        out["eta"] = iso(e)
        out["delay_min"] = max(0, int(round((e - task_time).total_seconds() / 60)))
        out["math"] = math_txt
    if "MUST_REST_NOW" in kinds and km_left is not None:
        d = km_left / AVG_KMH
        out["eta_after_11h_rest"] = iso(now + timedelta(hours=DAILY_REST_H + d))
        out["eta_after_9h_rest"] = iso(now + timedelta(hours=9 + d))
    if "MISSED_FIX" in kinds and task_time:
        out["minutes_since_fix"] = int(round((now - task_time).total_seconds() / 60))
    return out


def problem_item(n, r, found, prev_keys):
    lang = r["driver_lang"].strip().upper()
    kinds = [{"kind": k, "tag": "ONGOING" if (r["plate"], k) in prev_keys else "NEW", "text": t} for k, t in found if k != "INFO"]
    status = next((k for k in STATUS_ORDER if any(x["kind"] == k for x in kinds)), kinds[0]["kind"] if kinds else "INFO")
    has_task = bool(r["task_type"].strip() or r["task_time"].strip())
    goods = r["goods_on_board"].strip().lower() == "yes"
    return {
        "n": n, "plate": r["plate"], "status": status,
        "is_new": any(x["tag"] == "NEW" for x in kinds),
        "kinds": kinds, "info": [t for k, t in found if k == "INFO"],
        "driver": r["driver"].strip(), "driver_lang": lang if lang in LANG else "UNKNOWN",
        "driver_lang_name": LANG.get(lang, "unknown"), "greeting": greeting(r),
        "location": r["location"], "data_time": r["data_time"],
        "task": ({"task_id": r["task_id"], "type": r["task_type"], "address": r["task_address"], "time": r["task_time"],
                  "fix": r["task_fix"].strip().lower() == "yes", "client": r["client"]} if has_task else None),
        "goods_on_board": r["goods_on_board"].strip().lower(),
        "swap_possible": has_task and not goods,
        "facts": facts(r, found),
        "replacements": [],
        "ai": None, "decision": None,
    }


def rep_item(e, km, rr):
    lang = rr["driver_lang"].strip().upper()
    return {"plate": rr["plate"], "location": rr["location"], "km": round(km), "eta": iso(e),
            "clock": rr["clock"], "bed": rr["bed"], "driver": rr["driver"].strip(),
            "driver_lang": lang if lang in LANG else "UNKNOWN", "greeting": greeting(rr)}


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def check_file(data_time):
    return os.path.join(results_dir(), "check_" + data_time.replace(" ", "_").replace(":", "") + ".json")


def save_result(res):
    """Writes check_<time>.json + latest.json. Ongoing problems keep the AI plan and the
    dispatcher's answer from the previous check (the AI writes them only once)."""
    if not res["data_time"]:
        return None
    try:
        os.makedirs(results_dir(), exist_ok=True)
    except OSError:
        return None
    prev = _read_json(os.path.join(results_dir(), "latest.json"))
    if prev and prev.get("data_time") and prev["data_time"] < res["data_time"]:
        before = {p["plate"]: p for p in prev.get("problems", [])}
        for p in res["problems"]:
            old = before.get(p["plate"])
            if old and not p["is_new"] and old.get("status") == p["status"]:
                if old.get("ai"):
                    p["ai"] = dict(old["ai"], carried_from=old["ai"].get("carried_from") or prev["data_time"])
                if old.get("decision"):
                    p["decision"] = old["decision"]
    path = check_file(res["data_time"])
    _write_json(path, res)
    _write_json(os.path.join(results_dir(), "latest.json"), res)
    return path


MSG_TO = ("client", "driver")


def validate_ai(ai, res):
    """Returns (errors, warnings). Errors = the file is not saved."""
    errors, warnings = [], []
    if not isinstance(ai, dict) or not isinstance(ai.get("decisions"), list):
        return ['the file must look like {"data_time": "...", "decisions": [ ... ]}'], warnings
    if ai.get("data_time") != res.get("data_time"):
        errors.append(f"data_time {ai.get('data_time')!r} does not match the latest check {res.get('data_time')!r}")
    probs = {p["plate"]: p for p in res.get("problems", [])}
    seen = set()
    for i, d in enumerate(ai["decisions"], 1):
        plate = (d or {}).get("plate")
        where = f"decision {i} ({plate})"
        if plate not in probs:
            errors.append(f"{where}: {plate!r} is not a problem in this check (problems: {', '.join(probs) or 'none'})")
            continue
        if plate in seen:
            errors.append(f"{where}: {plate} appears twice")
        seen.add(plate)
        p = probs[plate]
        for key in ("headline", "cause"):
            if not str(d.get(key, "")).strip():
                errors.append(f"{where}: '{key}' is empty")
        opts = d.get("options")
        if not isinstance(opts, list) or not 1 <= len(opts) <= 4:
            errors.append(f"{where}: 'options' must be a list of 1-4 options")
            continue
        keys = [o.get("key") for o in opts]
        if len(set(keys)) != len(keys) or not all(keys):
            errors.append(f"{where}: every option needs its own 'key'")
        if sum(1 for o in opts if o.get("recommended")) != 1:
            errors.append(f"{where}: exactly ONE option must have \"recommended\": true")
        cands = {c["plate"] for c in p.get("replacements", [])}
        for o in opts:
            ow = f"{where} option {o.get('key')!r}"
            if not str(o.get("title", "")).strip():
                errors.append(f"{ow}: 'title' is empty")
            sw = o.get("swap_to")
            if sw:
                if not p["swap_possible"]:
                    errors.append(f"{ow}: swap_to {sw} not allowed - goods on board / no task, the truck cannot be swapped")
                elif sw not in cands:
                    errors.append(f"{ow}: swap_to {sw} is not in monitor.py's replacement list ({', '.join(cands) or 'none'}) - never guess a truck")
            msgs = o.get("messages", [])
            if not isinstance(msgs, list):
                errors.append(f"{ow}: 'messages' must be a list")
                continue
            for j, msg in enumerate(msgs, 1):
                mw = f"{ow} message {j}"
                if msg.get("to") not in MSG_TO:
                    errors.append(f"{mw}: 'to' must be \"client\" or \"driver\"")
                if not str(msg.get("text", "")).strip():
                    errors.append(f"{mw}: 'text' is empty")
                lang = str(msg.get("lang", "")).upper()
                if lang not in LANG:
                    errors.append(f"{mw}: 'lang' must be one of {', '.join(LANG)}")
                if msg.get("to") == "driver":
                    target = msg.get("plate") or plate
                    exp = p if target == plate else next((c for c in p.get("replacements", []) if c["plate"] == target), None)
                    if exp is None:
                        errors.append(f"{mw}: driver message for unknown truck {target!r}")
                    else:
                        want_lang = exp["driver_lang"]
                        if want_lang != "UNKNOWN" and lang != want_lang:
                            errors.append(f"{mw}: driver of {target} speaks {want_lang}, message is {lang}")
                        if not str(msg.get("text", "")).startswith(exp["greeting"]):
                            warnings.append(f"{mw}: should start with the greeting \"{exp['greeting']}\"")
    for plate, p in probs.items():
        if plate not in seen and p["is_new"] and not p.get("ai"):
            warnings.append(f"{plate}: NEW problem without an AI decision - the screen will show only the maths")
    return errors, warnings


def save_ai(path):
    """Merge the AI's decisions into latest.json and its check file. Returns True if saved."""
    res = _read_json(os.path.join(results_dir(), "latest.json"))
    if not res:
        print("ERROR: no results file yet - run a check first.")
        return False
    raw = sys.stdin.read() if path == "-" else None
    try:
        ai = json.loads(raw) if raw is not None else json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"ERROR: cannot read {path}: {e}")
        return False
    errors, warnings = validate_ai(ai, res)
    for w in warnings:
        print("WARNING: " + w)
    if errors:
        print("NOT SAVED - fix these and run --save-ai again:")
        for e in errors:
            print("  - " + e)
        return False
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    by_plate = {d["plate"]: d for d in ai["decisions"]}
    for p in res["problems"]:
        if p["plate"] in by_plate:
            d = by_plate[p["plate"]]
            p["ai"] = {k: d.get(k) for k in ("headline", "cause", "depends_on", "options")}
            p["ai"]["saved_at"] = stamp
    _write_json(check_file(res["data_time"]), res)
    _write_json(os.path.join(results_dir(), "latest.json"), res)
    print(f"Saved AI decisions for {len(by_plate)} of {len(res['problems'])} problem(s) in {check_file(res['data_time'])}")
    return True


def decide(plate, key, status, at=""):
    """Save the dispatcher's answer. An approved swap also goes to decisions.csv (-> [HANDLED] next check)."""
    if status not in ("approved", "rejected"):
        print("ERROR: status must be approved or rejected")
        return False
    res = _read_json(os.path.join(results_dir(), "latest.json"))
    p = next((x for x in (res or {}).get("problems", []) if x["plate"] == plate), None)
    if not p:
        print(f"ERROR: {plate} is not a problem in the latest check")
        return False
    opts = {o["key"]: o for o in ((p.get("ai") or {}).get("options") or [])}
    if opts and key not in opts:
        print(f"ERROR: option {key!r} not found for {plate} (options: {', '.join(opts)})")
        return False
    p["decision"] = {"status": status, "option": key, "at": at or datetime.now().strftime("%H:%M")}
    _write_json(check_file(res["data_time"]), res)
    _write_json(os.path.join(results_dir(), "latest.json"), res)
    sw = (opts.get(key) or {}).get("swap_to")
    if status == "approved" and sw and p.get("task") and p["task"]["task_id"]:
        approve_swap(p["task"]["task_id"], sw, p["decision"]["at"])
    print(f"Saved: {plate} -> {key} {status}")
    return True


def approve_swap(task_id, new_plate, at=""):
    new = not os.path.exists(DECISIONS)
    with open(DECISIONS, "a", encoding="utf-8") as f:
        if new:
            f.write("task_id,new_plate,approved_at\n")
        f.write(f"{task_id},{new_plate},{at}\n")
    print(f"Saved swap: {task_id} -> {new_plate}")


def snapshots():
    return sorted(f for f in os.listdir(SNAP_DIR) if f.startswith("fleet_") and f.endswith(".csv"))


def main():
    args = sys.argv[1:]
    if "--dir" in args:
        i = args.index("--dir")
        set_dir(args[i + 1])
        args = args[:i] + args[i + 2:]
    if args and args[0] == "--reset":
        for f in (STATE_FILE, DECISIONS):
            if os.path.exists(f):
                os.remove(f)
        if os.path.isdir(results_dir()):
            for f in os.listdir(results_dir()):
                if f.endswith(".json"):
                    os.remove(os.path.join(results_dir(), f))
        print("Demo reset. Next check: " + snapshots()[0])
        return
    if args and args[0] == "--approve":
        approve_swap(args[1], args[2], args[3] if len(args) > 3 else "")
        return
    if args and args[0] == "--save-ai":
        sys.exit(0 if save_ai(args[1]) else 1)
    if args and args[0] == "--decide":
        if len(args) < 4:
            print("Usage: monitor.py --decide <plate> <option_key> approved|rejected [time]")
            sys.exit(1)
        sys.exit(0 if decide(args[1], args[2], args[3], args[4] if len(args) > 4 else "") else 1)
    if args and args[0] == "--next":
        snaps = snapshots()
        last = open(STATE_FILE).read().strip() if os.path.exists(STATE_FILE) else None
        i = snaps.index(last) + 1 if last in snaps else 0
        if i >= len(snaps):
            print("No more snapshots. Run: python3 monitor.py --reset")
            return
        prev = os.path.join(SNAP_DIR, last) if last else None
        report(os.path.join(SNAP_DIR, snaps[i]), prev)
        with open(STATE_FILE, "w") as f:
            f.write(snaps[i])
        return
    if not args:
        print(__doc__)
        return
    prev = args[args.index("--prev") + 1] if "--prev" in args else None
    report(args[0], prev)


if __name__ == "__main__":
    main()
