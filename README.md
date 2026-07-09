# Vienna Research Radar — publishing runbook

How to publish a new issue of the newsletter. Written for someone comfortable
with the terminal and git.

## How the site is wired (read this once)

- **Primary site:** `research.wwtf.at` — hosted at Brunner.at. Updated by
  **`rsync` from this Mac mini** via the SSH key `~/.ssh/id_github`
  (→ `wwtfres@research.wwtf.at`).
- **Mirror:** `benwwtf.github.io/vienna-research-radar` — the GitHub Pages copy.
- **Repo (source of truth):** `~/vienna-research-radar-site/` on the Mac mini
  (`benjaminmissbach@100.112.136.40`), pushed to GitHub `BenWWTF/vienna-research-radar`.

> ⚠️ **The real site is deployed from the Mac mini, not from GitHub.** Editing a
> file on github.com only changes the *mirror*, not `research.wwtf.at`. Always
> work on the Mac mini and run the publish script there.

## What you need

1. **Tailscale** on your machine, added to the tailnet. The Mac mini is
   `100.112.136.40` and must be powered on.
2. **A login on the Mac mini** with access to `~/vienna-research-radar-site/`.
3. That's it — Python 3, git, the GitHub push auth, the `~/.ssh/id_github`
   deploy key, the repo, and `research-data.csv` are all already on the Mac mini.

Connect: `ssh benjaminmissbach@100.112.136.40` then `cd ~/vienna-research-radar-site`.

## Publish a new issue (say #5)

### 1. Start from the previous issue

```bash
cp issue-04.html issue-05.html
```

Everything (CSS, layout, scripts) is inline in that one file. You only edit content.

### 2. Edit `issue-05.html`

- **`<title>`** — `Issue #5 – <Title> · Vienna Research Radar`
- **Hero** (`.hero-content`):
  - `.hero-label` → `Issue #5 · DD Month YYYY · NNN papers scanned`
  - `.hero-title` → the issue title
  - `.hero-lede` → 2–3 punchy sentences (not the full LinkedIn intro)
- **Hero image:** put the `.jpg` in the repo root, point `.hero-bg { background: url("your-image.jpg") … }` at it.
- **Image credit:** the `<span class="sticky-nav-credit">` in the sticky nav —
  `Cover: “Title” © Name, Lab, Medical University of Vienna`. (Shows centered in
  the grey bar on desktop; hidden on mobile, where the hero image isn't shown.)
- **Sticky nav** `.sticky-nav-issue` → `#5 · DD Month YYYY`
- **Sections** — edit each in place, keep the structure:
  Spotlight → Radar Scans (cards) → Funding Moves → WWTF Insight → Stray Signal → Endnote.
  Update the sidebar TOC only if you add/remove a section.
- **Issue nav** (bottom): Previous → `issue-04.html`, counter → `Issue 5 of 5`.

### 3. Verify EVERY DOI against the dataset — never guess

Wrong links destroy trust. Every `href="https://doi.org/…"` must be checked
against `research-data.csv` (the fortnight's scanned papers, refreshed before
each issue). Example:

```bash
grep -i "methanesulfonic" research-data.csv     # find the paper, copy its DOI
```

Columns are: `Title, Authors, Vienna Researchers, Journal, DOI, …`. Copy the DOI
verbatim. If OpenAlex returned a wrong journal name, add a correction to
`doi-overrides.json` (see that file for the format).

### 4. Point the previous issue's "Next" at the new one

In `issue-04.html`, change the bottom nav from the disabled Next to:
`Issue 4 of 5` + `<a href="issue-05.html">Next …`.

### 5. Run the publish script

```bash
python3 scripts/publish-issue.py issue-05.html "The Title" 2026-07-23 512
```

Args: `<file> "<Title>" <YYYY-MM-DD> <papers>`. It: checks for duplicate DOIs,
applies `doi-overrides.json`, updates `index.html` (latest link) + the archive
redirect, copies the hero image, then **git commits, pushes, and rsyncs to
research.wwtf.at**. (No `--src` needed when the file is already in the repo.)

### 6. Add the archive card to `issues.html` (the script does NOT do this)

Copy the first `<a class="issue-card …>` block, put it at the top, and set:
issue number, href, title, teaser, `<time>`, **paper count**, **`~N min read`**,
and one **`<span class="card-pill">`** per section. Then:

```bash
git add issues.html issue-04.html
git commit -m "Issue #5: archive card + issue-04 next nav"
git push
rsync -az -e "ssh -i ~/.ssh/id_github -o StrictHostKeyChecking=no" \
  issues.html issue-04.html wwtfres@research.wwtf.at:public_html/
```

### 7. Verify live

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://research.wwtf.at/issue-05.html
```

Then eyeball: `https://research.wwtf.at/issue-05.html`, the card on
`https://research.wwtf.at/issues.html`, and the "Read the latest issue" link on
the homepage (it auto-updates from the archive).

## Gotchas

| Problem | Fix |
| --- | --- |
| SSH to the server fails from your laptop | Go via the Mac mini — port 22 is blocked elsewhere. |
| Tailscale not responding | Turn Tailscale on; Mac mini is `100.112.136.40`. |
| `git push` rejected | `git pull --rebase && git push`. |
| rsync auth fails | The key is `~/.ssh/id_github` **on the Mac mini** (not your laptop). |
| Wrong journal name from OpenAlex | Add it to `doi-overrides.json`. |
| Edited on github.com but research.wwtf.at didn't change | Expected — GitHub is only the mirror. Publish from the Mac mini. |
