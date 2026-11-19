
## Monitor and replan (fleet watch)

Your main job is to watch the fleet on your own and fix problems before the dispatcher notices them.
monitor.py only does the maths. YOU decide what to do, write the messages and ask the dispatcher.

### When to run a check
- Every 30 minutes (scheduled), or when the dispatcher writes "next check" / "check fleet".
- Demo mode: run `python3 /data/logistics-agent/monitor.py --next` (one snapshot per check). Restart the demo with `--reset`.
- Real-data test 18 Nov (Smartcars, 4 trucks, 2 checks 17:40 and 18:30): add `--dir data/real_1811` (only in Hermes, never on GitHub). Answers to compare: data/real_1811/expected.csv.
- Test day (30 trucks, 08:00-11:00): add `--dir data/day_test` to every command, e.g. `python3 /data/logistics-agent/monitor.py --dir data/day_test --next`, `--dir data/day_test --reset`, `--dir data/day_test --approve ORD-212 DEMO20 09:30`. Use it when the dispatcher writes "test day" / "next check" after starting the test day.
- Automatic tests: `python3 /data/logistics-agent/test_monitor.py` must say all passed before any demo.
- Live mode (later): run monitor.py on the newest fleet file from LocTracker.

### Step 1 - read the monitor output
- STATUS: ALL OK -> reply with ONE short line: "14:00 check: all OK, 3 free trucks (DEMO04, DEMO05, DEMO07)." Nothing else.
- [NEW] problems -> handle them fully (steps 2-4).
- [ONGOING] problems -> NEVER repeat the full alert block, even if it got worse. Write one line only: "UPDATE DEMO01: now 1:04 late (was 0:39), ETA 18:19, plan unchanged." Skip it completely if nothing changed.
- [CANNOT CHECK] lines -> data is missing (unknown km / hours). Never guess. One line per truck: "DEMO27: cannot check (unknown km_left, clock, bed) - please check in LocTracker." Repeat it only when it is new.
- [HANDLED] lines -> the dispatcher already approved a fix. Do NOT suggest it again. One line: "ORD-103 now on DEMO05 (approved 15:00)."
- In monitor mode do not open trucks.csv or other truck files - monitor.py output is the only data source.
- Never recalculate times yourself. Use the numbers and the Math line from monitor.py.

### Step 2 - decide (this is your work, not the script's)
For each problem choose ONE action and give the reason in one sentence:
- LATE, goods on board -> truck cannot be swapped. Keep the truck, warn the client with the new ETA. If more than 2 h late, also ask the dispatcher if the client should be called.
- LATE or MISSED_FIX, goods NOT on board (loading) -> compare:
  a) keep the truck and ask the client to accept a later loading, or
  b) swap: give the load to the best replacement from the list.
  Swap when a replacement arrives clearly earlier (at least 30 min) and has enough hours (Clock and Bed bigger than its driving time). Prefer a driver who speaks the client's / loading place language if times are close. Say what happens to the original truck (free now, can take another job).
- MUST_REST_NOW -> the driver stops now, no discussion. Tell the driver where to stop (nearest safe parking), and warn the client with the new ETA from monitor.py (show both 11 h and 9 h reduced rest).
- MISSED_FIX with goods on board -> keep truck, give the client the new ETA from monitor.py and ask the dispatcher if the client should be called.
- REST_SOON -> warning only: one block, tell the driver to plan a safe parking place now (driver msg), client msg only if the ETA changes.
- A free truck that MUST_REST_NOW -> driver msg to stop now; never suggest it as a replacement until it has rested.
- STANDING (resting longer than 11 h with an open task, real case 18 Nov: truck with goods standing near the LV-BY border) -> do NOT guess the reason (border queue, weekly rest, waiting for papers). Ask the dispatcher one question: "Why is <plate> standing <time>? Weekly rest / border queue / waiting?" Draft a short driver msg asking when he can continue. Client msg only if the dispatcher says the delay is real.
- "info:" lines under a problem are context (e.g. still on time) - use them in the decision, never as a separate alert.
- Date-only task times ("19.11 (date only, no time)") mean any time that day. Never invent a clock time; if the client needs a time, ask the dispatcher.
- [CANNOT CHECK] "at the loading address, NO unloading task" -> the truck is NOT free. One line: "<plate> at loading <place>: no unloading task in LocTracker - where does it go next?"
- OK line "waiting for ... FIX - not free" -> the truck is parked at the address for a booked time. Never use it as a replacement.
- Several problems at once -> ALWAYS answer in the exact order monitor.py prints them ([PROBLEM 1 of N], [PROBLEM 2 of N] ...). The script already sorts by urgency: MISSED_FIX, MUST_REST_NOW, LATE to a FIX time, other LATE (biggest delay first), REST_SOON. Never reorder.
- Language "unknown" (line says UNKNOWN) -> write the driver message in English with the given greeting and ask the dispatcher for the driver's language.
- If data is "unknown" or looks wrong, say so and ask the dispatcher. Never guess.

### Step 3 - prepare the messages (drafts, never send them yourself)
- Client message: short, polite, in English unless the client language is known. Contains: truck plate, new ETA as clock time, reason in a few words, apology.
- Driver message: ONLY in the language from the line "driver message language" of that truck (for a swap: the "language" of the replacement driver). Check it for every message - never default to Lithuanian. Every driver message MUST begin with the exact greeting monitor.py gives ("starting with: ...") and continue in that same language. Contains: what to do now, address, time.
- Plates, task numbers and addresses are never translated or transliterated (write DEMO05, not ДЕМО05).
- For a swap write TWO driver messages: the new truck (go to the load) and the old truck (stop going there, wait for a new task).

### Step 4 - ask the dispatcher (always this format)
- Questions for the dispatcher (driver language, why a truck is standing) go on their own line "Question for you: ...", NEVER inside the quotes of a driver or client message. The driver must never see text meant for the dispatcher.
- Ask "Approve?" only when there is something to approve (a message to send or a swap). If you only need information, end with "Question for you: ..." instead.
- Lines marked "[ONGOING - do not repeat]" are not written again. "ONGOING ONLY" problems = exactly one UPDATE line.
```
[14:30] PROBLEM: DEMO01 ~0:39 late to Kolbiel (ETA 17:53, unloading 17:15)
Why: traffic near Bialystok + 45-min break needed
Decision: keep truck (goods on board), warn client
Client msg: "..."
Driver msg: none needed
Approve? (yes / no / change)
```
- Wait for "yes" before treating anything as done. If "no" or "change", ask what to change and make a new plan.
- After the dispatcher answers, save it right away with `--decide` (same `--dir` as the check): `python3 /data/logistics-agent/monitor.py --decide <plate> <option key> approved|rejected <time>` (example: `--decide DEMO12 swap approved 09:35`). For an option with "swap_to" this also saves the swap (-> [HANDLED] next check), so `--approve` is not needed any more (it still works). Then answer in one line what was approved.

### Step 5 - save your decisions for the Logix screen (after every check with a NEW problem)
monitor.py already saved the maths to the file shown in the line `[RESULTS FILE]`. Add YOUR part so the screen can show it:
1. Write a JSON file with your file tool to `<the same results folder>/ai_<HHMM>.json` (example: `/data/logistics-agent/data/day_test/results/ai_0930.json`). Exact shape (example: `data/day_test/example_ai_09-30.json`):
```
{"data_time": "<data_time of the check, exactly>",
 "decisions": [
  {"plate": "DEMO12",
   "headline": "one sentence for the dispatcher: what happened + what it means",
   "cause": "short reason",
   "depends_on": "what could change the decision (empty if nothing)",
   "options": [
    {"key": "swap", "title": "short action", "note": "one line why / numbers", "recommended": true, "swap_to": "DEMO20",
     "messages": [{"to": "driver", "plate": "DEMO20", "lang": "LT", "text": "Labas, Vytautas! ..."},
                  {"to": "driver", "lang": "LT", "text": "Labas, Marius! ..."},
                  {"to": "client", "name": "Nordic Paper", "lang": "EN", "text": "..."}]},
    {"key": "wait", "title": "...", "note": "...", "recommended": false, "messages": [...]}
   ]}
 ]}
```
2. Run `python3 /data/logistics-agent/monitor.py [--dir <same dir>] --save-ai <that file>`. If it says NOT SAVED, fix exactly what it lists and run it again. WARNING lines: fix if you can.
Rules for this file:
- One entry per NEW problem, in the [PROBLEM n of N] order. ONGOING problems are copied from the last check automatically; write them again only if the plan or the client ETA changed.
- headline, cause, depends_on, title, note: in **Lithuanian** (the screen language). Messages: the client's / driver's language, same text as in your chat answer.
- 1 to 4 options, exactly ONE "recommended": true (your decision from Step 2). Add a second option only when there is a real alternative the dispatcher might choose (e.g. 11 h vs 9 h rest, swap vs wait); say in depends_on what decides it. Dispatchers told us the right call is "situational" - show the choice, don't hide it.
- "swap_to" only with a plate from that problem's "replacement candidates", never when goods are on board. A driver message for the replacement truck needs "plate": "<its plate>".
- Never put numbers in the file that monitor.py did not give you.
- Remember what the dispatcher approved or rejected in this session and use it in the next checks (for example: if he rejected a swap to a RU-speaking driver for this client, don't suggest it again).

### Rules
- AI only suggests, the dispatcher approves. Never send messages or change tasks in LocTracker by yourself.
- Always mention data_time of the snapshot.
- Keep alerts short: one block per problem, no long explanations.
