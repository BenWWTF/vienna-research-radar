#!/usr/bin/env python3
"""
publish-issue.py — Publish a new newsletter issue to the Vienna Research Radar site.

Usage:
  python3 scripts/publish-issue.py <issue-html> "<Title>" <YYYY-MM-DD> <papers>

Example:
  python3 scripts/publish-issue.py issue-03.html "The Climate Edition" 2026-06-25 412

What it does:
  1. Copies <issue-html> from the Open Design project dir into the repo
  2. Fixes internal links (landing.html → index.html, admin.html → dataset.html)
  3. Prepends a new issue card to archive.html
  4. Updates the "Read the latest issue" link on index.html
  5. git add + commit + push
"""

import csv, re, sys, shutil, subprocess
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).parent.parent
OD_PROJECT = Path.home() / "apps/open-design/.od/projects/b9e6ea69-8aab-4d39-b60d-41020921a083"
ARCHIVE = REPO / "archive.html"
INDEX = REPO / "index.html"

MONTHS_DE = {1:"Jänner",2:"Februar",3:"März",4:"April",5:"Mai",6:"Juni",
             7:"Juli",8:"August",9:"September",10:"Oktober",11:"November",12:"Dezember"}
MONTHS_EN = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
             7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}


def run(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd or REPO, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {' '.join(str(c) for c in cmd)}\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def check_duplicates(issue_html_path):
    """Warn if any DOI links in the new issue already appear in a published issue."""
    html = Path(issue_html_path).read_text(encoding='utf-8')
    # Extract all href doi.org links from the new issue
    new_dois = set(re.findall(r'href="(https://(?:doi\.org|www\.doi\.org)/[^"]+)"', html))
    if not new_dois:
        return

    # Scan all existing issue HTML files in the repo
    seen = {}  # doi -> filename
    for existing in sorted(REPO.glob('issue-*.html')):
        if existing.name == Path(issue_html_path).name:
            continue
        ex_html = existing.read_text(encoding='utf-8')
        for doi in re.findall(r'href="(https://(?:doi\.org|www\.doi\.org)/[^"]+)"', ex_html):
            seen[doi] = existing.name

    dupes = [(doi, seen[doi]) for doi in new_dois if doi in seen]
    if dupes:
        print(f"\nWARNING: {len(dupes)} DOI(s) already appear in a previous issue:")
        for doi, fname in dupes:
            print(f"  {doi}  ← {fname}")
        ans = input("Continue anyway? [y/N] ").strip().lower()
        if ans != 'y':
            print("Aborted.")
            sys.exit(1)
    else:
        print(f"Duplicate check: {len(new_dois)} DOI links checked, no duplicates found.")


def extract_teaser(html):
    m = re.search(r'class="hero-lede"[^>]*>(.*?)</p>', html, re.S)
    if not m:
        return ""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()


def extract_sections(html):
    labels = re.findall(r'class="section-label"[^>]*>.*?<span[^>]*>(.*?)</span>', html, re.S)
    return [re.sub(r'<[^>]+>', '', l).strip() for l in labels if l.strip()]


def issue_num_from_filename(filename):
    m = re.search(r'(\d+)', filename)
    return int(m.group(1)) if m else None


def format_date_en(dt):
    return f"{dt.day} {MONTHS_EN[dt.month]} {dt.year}"


def make_card(num, filename, title, date_str, papers, teaser, sections):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    date_en = format_date_en(dt)
    num_str = f"{num:02d}"
    pills = "\n".join(f'                <span class="card-pill">{s}</span>' for s in sections[:4])
    return f'''        <a
          class="issue-card fade-up"
          href="{filename}"
          aria-label="Issue #{num} – {title}, {date_en}"
        >
          <span class="card-num">#{num_str}</span>
          <div>
            <p class="card-title">{title}</p>
            <p class="card-teaser">
              {teaser}
            </p>
            <div class="card-meta">
              <time datetime="{date_str}">{date_en}</time>
              <span class="meta-sep">/</span>
              <span>{papers} papers</span>
              <span class="meta-sep">/</span>
              <div class="card-pills" aria-label="Sections">
{pills}
              </div>
            </div>
          </div>
          <span class="card-arrow" aria-hidden="true">→</span>
        </a>'''


def main():
    # Parse optional --src flag
    raw_args = sys.argv[1:]
    src_override = None
    if "--src" in raw_args:
        idx = raw_args.index("--src")
        src_override = Path(raw_args[idx + 1])
        raw_args = raw_args[:idx] + raw_args[idx + 2:]

    if len(raw_args) != 4:
        print("Usage: publish-issue.py <issue-html> \"<Title>\" <YYYY-MM-DD> <papers> [--src <path>]")
        sys.exit(1)

    filename, title, date_str, papers = raw_args[0], raw_args[1], raw_args[2], int(raw_args[3])

    src = src_override if src_override else OD_PROJECT / filename
    if not src.exists():
        print(f"Source file not found: {src}")
        sys.exit(1)

    dst = REPO / filename
    shutil.copy2(src, dst)
    print(f"Copied {filename}")

    # Duplicate check before touching archive/index
    check_duplicates(dst)

    # Fix internal links
    html = dst.read_text(encoding='utf-8')
    html = html.replace('landing.html', 'index.html').replace('admin.html', 'dataset.html')
    dst.write_text(html, encoding='utf-8')

    # Copy hero image if referenced locally
    img_match = re.search(r'url\("([^"]+\.(jpg|jpeg|png|webp))"\)', html)
    if img_match:
        img_name = img_match.group(1)
        img_src = OD_PROJECT / img_name
        img_dst = REPO / img_name
        if img_src.exists() and not img_dst.exists():
            shutil.copy2(img_src, img_dst)
            print(f"Copied hero image: {img_name}")

    # Extract teaser and sections from issue HTML
    teaser = extract_teaser(html)
    sections = extract_sections(html)
    num = issue_num_from_filename(filename)

    # Prepend card to archive.html
    archive_html = ARCHIVE.read_text(encoding='utf-8')
    card = make_card(num, filename, title, date_str, papers, teaser, sections)
    # Insert before the first existing issue-card
    archive_html = archive_html.replace(
        '<a\n          class="issue-card fade-up"',
        card + '\n\n        <a\n          class="issue-card fade-up"',
        1
    )
    ARCHIVE.write_text(archive_html, encoding='utf-8')
    print(f"Updated archive.html")

    # Update "Read the latest issue" link on index.html
    index_html = INDEX.read_text(encoding='utf-8')
    index_html = re.sub(
        r'(<a class="path" href=")[^"]+(")',
        lambda m: m.group(1) + filename + m.group(2),
        index_html,
        count=1
    )
    INDEX.write_text(index_html, encoding='utf-8')
    print(f"Updated index.html → latest issue: {filename}")

    # Commit and push
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    msg = f"Issue #{num}: {title} ({format_date_en(dt)}, {papers} papers)"
    run(["git", "add", filename, "archive.html", "index.html"] +
        ([img_name] if img_match and (REPO / img_match.group(1)).exists() else []))
    run(["git", "commit", "-m", msg])
    run(["git", "push"])
    print(f"\nPublished: {msg}")
    print(f"Live at: https://benwwtf.github.io/vienna-research-radar/{filename}")

    # Sync to research.wwtf.at
    import subprocess as _sp
    ssh_key = str(Path.home() / ".ssh/id_github")
    files_to_sync = [str(REPO / f) for f in ["archive.html", "index.html", filename]]
    if img_match and (REPO / img_match.group(1)).exists():
        files_to_sync.append(str(REPO / img_match.group(1)))
    try:
        _sp.run(
            ["rsync", "-az", "-e", f"ssh -i {ssh_key} -o StrictHostKeyChecking=no"]
            + files_to_sync
            + ["wwtfres@research.wwtf.at:public_html/"],
            check=True
        )
        print("Synced issue files → research.wwtf.at")
    except Exception as e:
        print(f"rsync to research.wwtf.at failed (non-fatal): {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
