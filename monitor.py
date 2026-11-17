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
  add  --dir data/day_test  to any command to use another snapshot folder (e.g. the 30-truck test day)
"""
import csv
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
    s = (s or "").strip()
    return datetime.strptime(s, "%Y-%m-%d %H:%M") if s else None


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
        at_last = (km_left == 0 and not nxt)
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
            if late_min > LATE_LIMIT_MIN:
                found.append(("LATE", f"ETA {e:%Y-%m-%d %H:%M} vs {r['task_type']} {r['task_time']}{' FIX' if r['task_fix'].lower()=='yes' else ''} -> {fmt_h(late_min/60)} late. Math: {math_txt}"))
            elif not found:
                fmt = "%H:%M" if e.date() == now.date() else "%d.%m %H:%M"
                ok.append(f"{plate}: on time (ETA {e:{fmt}}, {r['task_type']} {task_time:{fmt}})")
        if not found and task_time and (km_left is None or (clock is None and bed is None)):
            miss = [k for k in ("km_left", "clock", "bed") if num(r[k]) is None and hm(r[k]) is None] if km_left is None \
                else [k for k in ("clock", "cup", "bed") if hm(r[k]) is None]
            unknown.append(f"{plate} ({r['task_id']} {r['task_type']} {r['task_time']}): cannot check, unknown {', '.join(miss)} - ask the dispatcher")
        if found:
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
        else:
            k = (4, 0)
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
    prev_keys = set()
    if prev_path and os.path.exists(prev_path):
        for r, found in check(load(prev_path))[0]:
            for kind, _ in found:
                prev_keys.add((r["plate"], kind))

    problems, free, ok, unknown = check(rows)
    swaps = approved_swaps()
    busy = {p for p, _ in swaps.values()}
    free = [(r, n) for r, n in free if r["plate"] not in busy]
    handled = [(r, f) for r, f in problems if r["task_id"] in swaps]
    problems = [(r, f) for r, f in problems if r["task_id"] not in swaps]
    problems.sort(key=priority)
    print(f"=== FLEET CHECK  data_time {rows[0]['data_time']}  file {os.path.basename(path)} ===")
    if not problems:
        print("STATUS: ALL OK - nothing to report to the dispatcher.")
    else:
        print(f"STATUS: {len(problems)} truck(s) with problems")
    for n, (r, found) in enumerate(problems, 1):
        print(f"\n[PROBLEM {n} of {len(problems)}] {r['plate']} (driver {r['driver']}, lang {r['driver_lang']}) at {r['location']}")
        print(f"  driver message language: {LANG.get(r['driver_lang'].upper(), r['driver_lang'])} - write this driver's message ONLY in this language, "
              f"starting with: \"{greeting(r)}\"")
        if not (r["task_type"].strip() or r["task_time"].strip()):
            print("  no active task (free truck)")
            for kind, txt in found:
                tag = "ONGOING" if (r["plate"], kind) in prev_keys else "NEW"
                print(f"  - {kind} [{tag}]: {txt}")
            continue
        print(f"  task {r['task_id'] or '(no number)'}: {r['task_type']} at {r['task_address']} for client {r['client']}, goods on board: {r['goods_on_board']}")
        for kind, txt in found:
            tag = "ONGOING" if (r["plate"], kind) in prev_keys else "NEW"
            print(f"  - {kind} [{tag}]: {txt}")
        if r["goods_on_board"].lower() == "yes":
            print("  replacement: NOT POSSIBLE (goods already on this truck) -> options: keep truck, inform client")
        else:
            reps = replacements(r, free)
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
        print(f"\n[HANDLED] {r['task_id']} already moved from {r['plate']} to {newp} (approved {when}). "
              f"Do not suggest it again. {r['plate']} is free for another job; {newp} is busy with {r['task_id']}.")
    print("\n[FREE TRUCKS]")
    for r, note in free or []:
        print(f"  {r['plate']} at {r['location']} - {note} (Clock {r['clock']}, Bed {r['bed']})")
    if not free:
        print("  none")
    if unknown:
        print("\n[CANNOT CHECK] (data missing - do not guess, ask the dispatcher)")
        for line in unknown:
            print("  " + line)
    print("\n[OK]")
    for line in ok:
        print("  " + line)


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
        print("Demo reset. Next check: " + snapshots()[0])
        return
    if args and args[0] == "--approve":
        new = not os.path.exists(DECISIONS)
        with open(DECISIONS, "a", encoding="utf-8") as f:
            if new:
                f.write("task_id,new_plate,approved_at\n")
            f.write(f"{args[1]},{args[2]},{args[3] if len(args) > 3 else ''}\n")
        print(f"Saved: {args[1]} -> {args[2]}")
        return
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
