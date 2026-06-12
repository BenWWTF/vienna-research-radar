#!/usr/bin/env python3
"""
merge-dataset.py — Merge all weekly KW CSVs into research-data.csv and push to GitHub.

Run on Mac mini via cron every Tuesday at 8am Vienna time:
  0 7 * * 2 /usr/bin/python3 /Users/benjaminmissbach/vienna-research-radar-site/scripts/merge-dataset.py

Reads:  ~/nanoclaw/groups/whatsapp_vienna_research/data/findings/vienna_research_radar_KW*.csv
Writes: <repo>/research-data.csv
Then:   git commit + push
"""

import csv, glob, os, subprocess, sys
from pathlib import Path
from datetime import date

REPO = Path(__file__).parent.parent
FINDINGS = Path.home() / "nanoclaw/groups/whatsapp_vienna_research/data/findings"
OUT = REPO / "research-data.csv"
COLS = ['Title','Authors','Vienna Researchers','Journal','DOI','Domain','Field','OA Status','Cited By','Date','Abstract']


def read_csv(path):
    rows = {}
    with open(path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            doi = (row.get('DOI') or '').strip()
            if doi:
                rows[doi] = {c: (row.get(c) or '').strip() for c in COLS}
    return rows


def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd or REPO, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def main():
    sources = sorted(FINDINGS.glob("vienna_research_radar_KW*.csv"))
    if not sources:
        print("No KW CSV files found — nothing to merge.")
        sys.exit(0)

    # Start from existing cumulative CSV so we never lose data
    merged = {}
    if OUT.exists():
        merged = read_csv(OUT)
        print(f"Loaded {len(merged)} existing papers from {OUT.name}")

    print(f"Merging {len(sources)} weekly file(s)...")
    for path in sources:
        before = len(merged)
        merged.update(read_csv(path))
        added = len(merged) - before
        if added:
            print(f"  {path.name}: +{added} new papers")
        else:
            print(f"  {path.name}: (already fully merged)")

    rows = sorted(merged.values(), key=lambda r: r['Date'], reverse=True)

    with open(OUT, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    print(f"Written {len(rows)} papers → {OUT}")

    # Only commit if the file actually changed
    status = run(["git", "status", "--porcelain", "research-data.csv"])
    if not status:
        print("research-data.csv unchanged — nothing to push.")
        return

    week = date.today().isocalendar()
    msg = f"Dataset: KW{week.week} {week.year} ({len(rows)} papers total)"
    run(["git", "add", "research-data.csv"])
    run(["git", "commit", "-m", msg])
    run(["git", "push"])
    print(f"Pushed: {msg}")

    # Sync CSV to research.wwtf.at
    import subprocess as _sp
    ssh_key = str(Path.home() / ".ssh/id_github")
    try:
        _sp.run(
            ["rsync", "-az", "-e", f"ssh -i {ssh_key} -o StrictHostKeyChecking=no",
             str(OUT), "wwtfres@research.wwtf.at:public_html/research-data.csv"],
            check=True
        )
        print("Synced research-data.csv → research.wwtf.at")
    except Exception as e:
        print(f"rsync to research.wwtf.at failed (non-fatal): {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
