#!/bin/sh
# Installs / updates the Logix fleet-monitor demo in Hermes.
set -e
DEST=/data/logistics-agent
[ -f "$DEST/AGENTS.md.bak_before_monitor" ] || cp "$DEST/AGENTS.md" "$DEST/AGENTS.md.bak_before_monitor"
mkdir -p "$DEST/data/snapshots"
cp monitor.py test_monitor.py "$DEST/"
mkdir -p "$DEST/tools" "$DEST/data/day_test"
cp tools/gen_day.py "$DEST/tools/"
cp data/day_test/fleet_*.csv data/day_test/example_ai_*.json "$DEST/data/day_test/"
cp $(ls data/snapshots/fleet_*.csv 2>/dev/null || ls fleet_*.csv) "$DEST/data/snapshots/"
# replace the old "Monitor and replan" section (always the last section) with the new one
sed -i '/^## Monitor and replan/,$d' "$DEST/AGENTS.md"
cat AGENTS_monitor.md >> "$DEST/AGENTS.md"
python3 "$DEST/monitor.py" --reset
python3 "$DEST/monitor.py" --dir data/day_test --reset
python3 "$DEST/test_monitor.py"
echo "Installed. Original backup: $DEST/AGENTS.md.bak_before_monitor"
