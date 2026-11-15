#!/bin/sh
# Installs the Logix fleet-monitor demo into Hermes.
# Usage (in Hermes terminal): sh install.sh
set -e
DEST=/data/logistics-agent
cp "$DEST/AGENTS.md" "$DEST/AGENTS.md.bak_before_monitor"
mkdir -p "$DEST/data/snapshots"
cp monitor.py "$DEST/monitor.py"
cp $(ls data/snapshots/fleet_*.csv 2>/dev/null || ls fleet_*.csv) "$DEST/data/snapshots/"
grep -q "## Monitor and replan" "$DEST/AGENTS.md" || cat AGENTS_monitor.md >> "$DEST/AGENTS.md"
python3 "$DEST/monitor.py" --reset
echo "Installed. Backup: $DEST/AGENTS.md.bak_before_monitor"
