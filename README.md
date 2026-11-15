# Logix fleet-monitor demo

Demo of the Logistic Agent watching a fleet and replanning.

- `monitor.py`: fast maths (arrival times, driver hours, free trucks, replacement candidates)
- `AGENTS_monitor.md`: rules for the AI agent (decide, draft messages, ask the dispatcher)
- `data/snapshots/`: 4 simulated fleet snapshots (14:00, 14:30, 15:00, 15:30) with fake plates DEMO01 to DEMO08

Run: `python3 monitor.py --next` (one check per snapshot), `python3 monitor.py --reset` to start again.
