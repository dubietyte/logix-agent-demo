#!/usr/bin/env python3
"""Generates a simulated working morning for a 30-truck fleet (fake plates DEMO01-DEMO30).
7 snapshots every 30 min (08:00-11:00) with planted problems. Output: data/day_test/fleet_HH-MM.csv
"""
import csv, math, os
from datetime import datetime, timedelta

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "day_test")
COLS = "plate,driver,driver_lang,location,lat,lon,status,clock,cup,bed,task_id,task_type,task_address,task_lat,task_lon,task_time,task_fix,client,goods_on_board,km_left,next_task_time,data_time".split(",")
START = datetime(2026, 11, 18, 8, 0)
STEPS = 7
KMH, ROAD = 70, 1.3

C = {  # city: (lat, lon, country)
    "Vilnius": (54.6872, 25.2797, "LT"), "Kaunas": (54.8985, 23.9036, "LT"), "Klaipeda": (55.7033, 21.1443, "LT"),
    "Panevezys": (55.7348, 24.3575, "LT"), "Siauliai": (55.9349, 23.3137, "LT"), "Marijampole": (54.5599, 23.3541, "LT"),
    "Alytus": (54.3963, 24.0459, "LT"), "Jonava": (55.0833, 24.2833, "LT"), "Ukmerge": (55.25, 24.78, "LT"),
    "Utena": (55.4977, 25.5992, "LT"), "Kedainiai": (55.2883, 23.9747, "LT"), "Riga": (56.9496, 24.1052, "LV"),
    "Jelgava": (56.6511, 23.7214, "LV"), "Tallinn": (59.437, 24.7536, "EE"), "Tartu": (58.378, 26.729, "EE"),
    "Warsaw": (52.2297, 21.0122, "PL"), "Bialystok": (53.1325, 23.1688, "PL"), "Kolbiel": (52.0661, 21.4886, "PL"),
    "Lodz": (51.7592, 19.456, "PL"), "Poznan": (52.4064, 16.9252, "PL"), "Gdansk": (54.352, 18.6466, "PL"),
    "Suwalki": (54.1118, 22.9309, "PL"), "Berlin": (52.52, 13.405, "DE"), "Lublin": (51.2465, 22.5684, "PL"),
}


NEXT = {"Riga": "Tallinn", "Siauliai": "Klaipeda", "Bialystok": "Vilnius", "Panevezys": "Riga", "Kaunas": "Warsaw"}


def km(a, b):
    (la1, lo1, _), (la2, lo2, _) = C[a], C[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x)) * ROAD


def f_hm(h):
    h = max(0, h)
    m = int(round(h * 60))
    return f"{m // 60}:{m % 60:02d}"


# plate, driver, lang, origin, dest, task_type, fix, client, goods, clock, cup, bed, delay windows [(from_step, to_step)], extra
T = [
    # --- planted problems ---
    ("DEMO07", "Oleg", "RU", "Bialystok", "Kolbiel", "unloading", "no", "Baltic Foods", "yes", 6.0, 3.5, 9.0, [(1, 4)], {"buffer": 0.6}),      # traffic jam -> LATE, goods on board
    ("DEMO12", "Marius", "LT", "Panevezys", "Kaunas", "loading", "yes", "Nordic Paper", "no", 7.0, 4.0, 10.0, [(1, 4)], {"buffer": 0.7}),     # breakdown -> will miss FIX loading -> swap
    ("DEMO18", "Andrej", "RU", "Utena", "Klaipeda", "unloading", "no", "Agro Trade", "yes", 6.5, 4.0, 1.4, [], {}),                          # Bed runs out -> MUST_REST_NOW
    ("DEMO23", "Tomas", "LT", "Kaunas", "Riga", "unloading", "yes", "Riga Retail", "yes", 7.0, 4.0, 9.0, [(0, 7)], {"task_time": START + timedelta(hours=1, minutes=15), "start_frac": 0.55}),  # border queue -> FIX missed
    ("DEMO27", "Pavel", "RU", "Vilnius", "Tallinn", "unloading", "no", "Estonia Trade", "yes", None, None, None, [], {"unknown": True}),    # unknown hours / km
    ("DEMO30", "Rokas", "LT", "Vilnius", "Berlin", "unloading", "no", "Berlin Food", "yes", 8.0, 4.0, 9.0, [], {}),                          # long trip, daily rest planned -> on time
    # --- normal trips ---
    ("DEMO01", "Jonas", "LT", "Vilnius", "Warsaw", "unloading", "no", "Baltic Foods", "yes", 8.0, 4.5, 11.0, [], {}),
    ("DEMO02", "Sergej", "RU", "Kaunas", "Klaipeda", "unloading", "no", "Port Logistics", "yes", 7.5, 4.0, 10.0, [], {}),
    ("DEMO03", "Darius", "LT", "Siauliai", "Riga", "loading", "yes", "Riga Retail", "no", 9.0, 4.5, 12.0, [], {}),
    ("DEMO05", "Piotr", "PL", "Suwalki", "Lodz", "unloading", "no", "Agro Trade", "yes", 8.0, 4.0, 11.0, [], {}),
    ("DEMO06", "Viktor", "RU", "Marijampole", "Poznan", "unloading", "no", "Nordic Paper", "yes", 8.5, 4.5, 12.0, [], {}),
    ("DEMO08", "Andrius", "LT", "Klaipeda", "Gdansk", "unloading", "no", "Port Logistics", "yes", 8.0, 4.0, 11.0, [], {}),
    ("DEMO09", "Igor", "RU", "Riga", "Tallinn", "unloading", "no", "Estonia Trade", "yes", 9.0, 4.5, 12.0, [], {}),
    ("DEMO10", "Mantas", "LT", "Alytus", "Lublin", "unloading", "no", "Agro Trade", "yes", 9.0, 4.5, 12.0, [], {}),
    ("DEMO11", "Dmitrij", "RU", "Jelgava", "Siauliai", "loading", "no", "Baltic Foods", "no", 9.0, 4.5, 12.0, [], {}),
    ("DEMO13", "Laurynas", "LT", "Tartu", "Riga", "unloading", "no", "Riga Retail", "yes", 9.0, 4.5, 12.0, [], {}),
    ("DEMO14", "Maksim", "RU", "Warsaw", "Bialystok", "loading", "yes", "Agro Trade", "no", 8.0, 4.5, 11.0, [], {}),
    ("DEMO15", "Paulius", "LT", "Kedainiai", "Vilnius", "unloading", "no", "Nordic Paper", "yes", 7.0, 4.0, 10.0, [], {}),
    ("DEMO16", "Taras", "UA", "Lublin", "Warsaw", "unloading", "no", "Baltic Foods", "yes", 9.0, 4.5, 12.0, [], {}),
    ("DEMO17", "Arturas", "LT", "Ukmerge", "Panevezys", "loading", "no", "Port Logistics", "no", 9.0, 4.5, 12.0, [], {}),
    ("DEMO19", "Krzysztof", "PL", "Gdansk", "Poznan", "unloading", "no", "Nordic Paper", "yes", 9.0, 4.5, 12.0, [], {}),
]
# free / not busy trucks: plate, driver, lang, city, status, clock, cup, bed, next_task_hours (None = no next task)
FREE = [
    ("DEMO04", "Evaldas", "LT", "Vilnius", "resting", 9.0, 4.5, 13.0, None),
    ("DEMO20", "Vytautas", "LT", "Kaunas", "resting", 9.0, 4.5, 13.0, None),       # best replacement for DEMO12 (Kaunas)
    ("DEMO21", "Nikolaj", "RU", "Jonava", "other", 8.0, 4.5, 12.0, None),          # 2nd replacement
    ("DEMO22", "Saulius", "LT", "Marijampole", "resting", 9.0, 4.5, 13.0, 30),     # next task in 30 h -> free
    ("DEMO24", "Aleksandr", "RU", "Klaipeda", "resting", 9.0, 4.5, 13.0, None),
    ("DEMO25", "Gintaras", "LT", "Vilnius", "resting", 0.4, 0.4, 0.5, None),       # free but almost no hours
    ("DEMO26", "Robert", "PL", "Warsaw", "resting", 9.0, 4.5, 13.0, 3),            # next task in 3 h -> NOT free
    ("DEMO28", "Edgar", "LT", "Siauliai", "other", 9.0, 4.5, 13.0, None),
    ("DEMO29", "Wojciech", "PL", "Bialystok", "resting", 9.0, 4.5, 13.0, None),
]


def build():
    os.makedirs(OUT, exist_ok=True)
    trucks = []
    for i, (p, d, l, o, de, tt, fix, cl, goods, clock, cup, bed, delays, ex) in enumerate(T):
        total = km(o, de)
        frac = ex.get("start_frac", 0.1 + (i % 5) * 0.08)
        left = total * (1 - frac)
        drive_h = left / KMH
        if ex.get("task_time"):
            tt_time = ex["task_time"]
        else:
            avail = min(clock, bed) if clock else 99
            rest = 11 if drive_h > avail else (0.75 if cup and drive_h > cup else 0)
            tt_time = START + timedelta(hours=drive_h + rest + ex.get("buffer", 1.5))
            tt_time = tt_time.replace(minute=(tt_time.minute // 15) * 15, second=0, microsecond=0)
        trucks.append(dict(p=p, d=d, l=l, o=o, de=de, tt=tt, fix=fix, cl=cl, goods=goods, clock=clock, cup=cup, bed=bed,
                           delays=delays, left=left, total=total, tt_time=tt_time, unknown=ex.get("unknown"),
                           task_id=f"ORD-{200 + int(p[4:])}", done=False))
    for s in range(STEPS):
        now = START + timedelta(minutes=30 * s)
        rows = []
        for t in trucks:
            if s > 0:  # move 30 min
                stuck = any(a <= s - 1 < b for a, b in t["delays"])
                if t["clock"] is not None:
                    if t["cup"] <= 0:
                        t["cup"] = 4.5  # break taken in this slot
                        t["bed"] -= 0.5
                    elif t["bed"] <= 0 and t["p"] != "DEMO18":
                        pass
                    else:
                        if not stuck:
                            t["left"] = max(0, t["left"] - KMH * 0.5)
                        t["clock"] -= 0.5; t["cup"] -= 0.5; t["bed"] -= 0.5
                elif not stuck:
                    t["left"] = max(0, t["left"] - KMH * 0.5)
            f = 1 - t["left"] / t["total"]
            (la1, lo1, c1), (la2, lo2, c2) = C[t["o"]], C[t["de"]]
            lat, lon = la1 + (la2 - la1) * f, lo1 + (lo2 - lo1) * f
            near = t["o"] if f < 0.5 else t["de"]
            if t["left"] < 1 and t["tt"] == "loading":
                # loaded -> new unloading task, truck stays busy
                nd = NEXT[t["de"]]
                t.update(o=t["de"], de=nd, tt="unloading", goods="yes", fix="no", task_id=t["task_id"] + "-U")
                t["total"] = t["left"] = km(t["o"], nd)
                need = t["left"] / KMH
                avail = min(t["clock"], t["bed"])
                t["tt_time"] = (now + timedelta(hours=need + (11 if need > avail else 0.75) + 2)).replace(minute=0)
                f = 0.0
                (la1, lo1, c1), (la2, lo2, c2) = C[t["o"]], C[t["de"]]
                lat, lon, near = la1, lo1, t["o"]
            arrived = t["left"] < 1
            if arrived:
                # task finished -> truck free at destination
                rows.append(dict(plate=t["p"], driver=t["d"], driver_lang=t["l"], location=f"{t['de']} {C[t['de']][2]}",
                                 lat=f"{la2:.4f}", lon=f"{lo2:.4f}", status="other",
                                 clock=f_hm(t["clock"]) if t["clock"] is not None else "unknown",
                                 cup=f_hm(t["cup"]) if t["cup"] is not None else "unknown",
                                 bed=f_hm(t["bed"]) if t["bed"] is not None else "unknown",
                                 task_id="", task_type="", task_address="", task_lat="", task_lon="", task_time="",
                                 task_fix="", client="", goods_on_board="no", km_left="", next_task_time="",
                                 data_time=now.strftime("%Y-%m-%d %H:%M")))
                continue
            stuck_now = any(a <= s < b for a, b in t["delays"])
            status = "driving"
            if t["clock"] is not None and t["cup"] <= 0:
                status = "resting"
            loc = f"near {near} {C[near][2]}" + (" (traffic jam)" if stuck_now and t["p"] == "DEMO07" else "")
            if t["p"] == "DEMO12" and stuck_now:
                loc, status = f"near {near} {C[near][2]} (breakdown)", "other"
            if t["p"] == "DEMO23":
                loc, status = "Lithuania-Latvia border (queue)", "other"
            rows.append(dict(
                plate=t["p"], driver=t["d"], driver_lang=t["l"], location=loc,
                lat=f"{lat:.4f}", lon=f"{lon:.4f}", status=status,
                clock=f_hm(t["clock"]) if t["clock"] is not None else "unknown",
                cup=f_hm(t["cup"]) if t["cup"] is not None else "unknown",
                bed=f_hm(t["bed"]) if t["bed"] is not None else "unknown",
                task_id=t["task_id"], task_type=t["tt"], task_address=f"{t['de']} {C[t['de']][2]}",
                task_lat=f"{la2:.4f}", task_lon=f"{lo2:.4f}", task_time=t["tt_time"].strftime("%Y-%m-%d %H:%M"),
                task_fix=t["fix"], client=t["cl"], goods_on_board=t["goods"],
                km_left="unknown" if t["unknown"] else f"{t['left']:.0f}", next_task_time="",
                data_time=now.strftime("%Y-%m-%d %H:%M")))
        for (p, d, l, city, st, clock, cup, bed, nxt) in FREE:
            la, lo, cc = C[city]
            rows.append(dict(plate=p, driver=d, driver_lang=l, location=f"{city} {cc}", lat=f"{la:.4f}", lon=f"{lo:.4f}",
                             status=st, clock=f_hm(clock), cup=f_hm(cup), bed=f_hm(bed), task_id="", task_type="",
                             task_address="", task_lat="", task_lon="", task_time="", task_fix="", client="",
                             goods_on_board="no", km_left="",
                             next_task_time=(START + timedelta(hours=nxt)).strftime("%Y-%m-%d %H:%M") if nxt else "",
                             data_time=now.strftime("%Y-%m-%d %H:%M")))
        rows.sort(key=lambda r: r["plate"])
        path = os.path.join(OUT, f"fleet_{now:%H-%M}.csv")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader(); w.writerows(rows)
        print("wrote", path, len(rows), "trucks")


if __name__ == "__main__":
    build()
