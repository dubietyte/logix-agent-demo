# Logix fleet-monitor demo

Demo of the Logistic Agent watching a fleet and replanning.

- `monitor.py`: fast maths (arrival times, driver hours, free trucks, replacement candidates)
- `AGENTS_monitor.md`: rules for the AI agent (decide, draft messages, ask the dispatcher)
- `data/snapshots/`: 4 simulated fleet snapshots (14:00, 14:30, 15:00, 15:30) with fake plates DEMO01 to DEMO08

Run: `python3 monitor.py --next` (one check per snapshot), `python3 monitor.py --reset` to start again.

## 30-truck test day + automatic tests (17 Nov)
- `data/day_test/`: 7 checks (08:00-11:00) of a simulated 30-truck fleet (DEMO01-DEMO30) with planted problems: traffic jam (DEMO07), breakdown before FIX loading (DEMO12, best swap DEMO20), driver must rest (DEMO18), border queue -> missed FIX (DEMO23), unknown data (DEMO27), long trip with daily rest (DEMO30). Regenerate with `python3 tools/gen_day.py`.
- `python3 monitor.py --dir data/day_test --next` runs the test day.
- `python3 test_monitor.py`: 13 edge-case scenarios + 7 day checks, PASS/FAIL table in about 1 second.

## Real-data test 18 Nov (Smartcars, private)
Real LocTracker screenshots (4 trucks, 17:40 and 18:30) found 3 bugs, all fixed: date-only task time crashed the script; truck waiting at the unloading address for a FIX next morning was shown as free; truck at its loading address with no next task was shown as free. New rule STANDING: resting > 11 h with an open task -> ask why, never guess. Real data stays only in Hermes (data/real_1811), never here.
