#!/bin/bash
# Vienna Research Radar — biweekly LinkedIn import check.
#
# Cron fires every Thursday at 14:00, 15:00, 16:00 and 17:00. This gate drops the
# off weeks, anchored on Thursday 20 August 2026. The importer no-ops once the
# issue already exists locally and only mails when it actually drafts something,
# so the four hourly runs cost nothing after the first one lands the issue.
set -u

REPO=/Users/benjaminmissbach/vienna-research-radar-site
ANCHOR=${ANCHOR:-2026-08-20}   # overridable so the gate can be smoke-tested

# ponytail: date arithmetic in days, not ISO week parity — week numbers flip in
# 53-week years and would silently invert the schedule.
anchor_s=$(date -j -f "%Y-%m-%d %H:%M:%S" "$ANCHOR 00:00:00" +%s) || exit 1
days=$(( ( $(date +%s) - anchor_s ) / 86400 ))

[ "$days" -lt 0 ] && exit 0            # before the anchor: not our schedule yet
[ $(( days % 14 )) -ne 0 ] && exit 0   # off week

cd "$REPO" || exit 1
echo "=== $(date '+%Y-%m-%d %H:%M') (day $days since $ANCHOR) ==="
exec /usr/bin/python3 scripts/import-linkedin-issue.py --mail
