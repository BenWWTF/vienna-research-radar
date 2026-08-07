#!/usr/bin/env python3
"""
import-linkedin-issue.py — build a Vienna Research Radar issue page from the
LinkedIn newsletter article.

  python3 scripts/import-linkedin-issue.py                # find newest issue, build draft
  python3 scripts/import-linkedin-issue.py --url <pulse>  # build a specific article
  python3 scripts/import-linkedin-issue.py --publish      # build, then run publish-issue.py

Everything it needs is in the public LinkedIn HTML: article text, cover image,
DOI links (behind LinkedIn's redirect shim), publish date and paper count.
No login. Cover comes back at 1200x675; LinkedIn 403s the larger variants.

It writes issue-NN.html, the cover jpg, the issues.html card, and the Next link
on the previous issue — then stops. Publishing stays a separate, deliberate step
unless you pass --publish.
"""

import argparse, csv, html, json, re, shutil, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NEWSLETTER = "https://www.linkedin.com/newsletters/vienna-research-radar-7459820984167059456/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
MONTHS_EN = {1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
             7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December"}

# LinkedIn tags Vienna institutions in German; the site writes them in English.
INSTITUTIONS = {
    "Austrian Academy of Sciences - Österreichische Akademie der Wissenschaften (ÖAW)":
        "Austrian Academy of Sciences",
    "Umweltbundesamt - Environment Agency Austria": "Environment Agency Austria",
    "Medizinische Universität Wien": "Medical University of Vienna",
    "Technische Universität Wien": "TU Wien",
    "Wirtschaftsuniversität Wien": "WU Vienna",
    "Universität Wien": "University of Vienna",
}

# LinkedIn mention chips drop the article; the newsletter's prose keeps it.
TIDY = [
    (r"\s+([,.;:])", r"\1"),
    (r"\bat (University of Vienna|Medical University of Vienna|TU Wien|WU Vienna|"
     r"Austrian Academy of Sciences|Environment Agency Austria|Complexity Science Hub)\b",
     r"at the \1"),
    (r"\bat the the\b", "at the"),
]

SECTIONS = ["Spotlight", "Radar Scans", "Funding Moves", "WWTF Insight", "Stray Signal"]
SECTION_IDS = {"Spotlight": "spotlight", "Radar Scans": "radar", "Funding Moves": "funding",
               "WWTF Insight": "wwtf-insight", "Stray Signal": "stray"}


# ─── fetching ────────────────────────────────────────────────────────────────

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def newest_linkedin_issue():
    """(number, url) of the highest-numbered article on the newsletter index."""
    idx = fetch(NEWSLETTER)
    found = {}
    for u in re.findall(r'href="(https://www\.linkedin\.com/pulse/[^"?]+)', idx):
        m = re.search(r"/pulse/(\d+)-", u)
        if m:
            found[int(m.group(1))] = u
    if not found:
        sys.exit("No pulse articles found on the newsletter index (layout changed?).")
    n = max(found)
    return n, found[n]


def highest_local_issue():
    nums = [int(re.search(r"issue-(\d+)\.html", p.name).group(1))
            for p in REPO.glob("issue-*.html")]
    return max(nums) if nums else 0


# ─── inline HTML conversion ──────────────────────────────────────────────────

def real_url(href):
    """Unwrap LinkedIn's redirect shim; return None for LinkedIn's own pages."""
    href = html.unescape(href)
    if "linkedin.com/redir/redirect" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "url" in q:
            href = urllib.parse.unquote(q["url"][0]).replace("%2E", ".")
    elif "linkedin.com" in href:
        return None          # profile / company / school mention, not a real source
    # LinkedIn sometimes leaves its tracking params on the target URL
    u = urllib.parse.urlparse(href)
    keep = [(k, v) for k, v in urllib.parse.parse_qsl(u.query)
            if k not in ("trk", "urlhash", "originalSubdomain")]
    return urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(keep)))


def strip_tags(frag):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", frag))).strip()


def inline(frag):
    """LinkedIn paragraph HTML -> the site's inline markup (links + <em> only)."""
    frag = re.sub(r'<span class="italic">(.*?)</span>',
                  lambda m: "\x01" + m.group(1) + "\x02", frag, flags=re.S)

    def link(m):
        url, text = real_url(m.group(1)), strip_tags(m.group(2))
        if not url:
            return text
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'

    frag = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', link, frag, flags=re.S)
    frag = re.sub(r"<(?!/?a\b)[^>]+>", "", frag)
    frag = re.sub(r"\s+", " ", html.unescape(frag)).strip()
    out = frag.replace("\x01", "<em>").replace("\x02", "</em>")
    for de, en in INSTITUTIONS.items():
        out = out.replace(de, en)
    for pat, rep in TIDY:
        out = re.sub(pat, rep, out)
    return out


def citation(frag):
    """A '→ Author et al., Journal, year' line -> the site's single-link cite."""
    url = None
    for href in re.findall(r'href="([^"]+)"', frag):
        url = real_url(href) or url
    body = inline(frag)
    body = re.sub(r"^→\s*", "", body)
    body = re.sub(r'<a[^>]*>(.*?)</a>', r"\1", body)     # site links the whole line
    if not url:
        return body, None
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{body}</a>', url


# ─── article parsing ─────────────────────────────────────────────────────────

def parse_article(page):
    art = re.search(r"<article.*?</article>", page, re.S)
    if not art:
        sys.exit("Could not find the <article> block — LinkedIn layout changed.")
    art = art.group(0)

    title = strip_tags(re.search(r'<h1 class="pulse-title[^"]*"[^>]*>(.*?)</h1>', art, re.S).group(1))
    num = int(re.match(r"#?(\d+)", title).group(1))
    title = re.sub(r"^#?\d+\s*[–-]\s*", "", title)

    dm = re.search(r"Published\s+([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{4})", page)
    month, day, year = MONTHS[dm.group(1)], int(dm.group(2)), int(dm.group(3))

    tag = re.search(r'<img[^>]*data-embed-id="cover-image"[^>]*>', art)
    cover = re.search(r'src="([^"]+)"', tag.group(0)).group(1) if tag else \
        re.search(r'<meta property="og:image" content="([^"]+)"', page).group(1)
    cover = html.unescape(cover)
    cap = re.search(r'<figcaption class="cover-img__caption[^"]*"[^>]*>(.*?)</figcaption>', art, re.S)
    credit = strip_tags(cap.group(1)).replace("(c)", "©") if cap else ""
    for de, en in INSTITUTIONS.items():
        credit = credit.replace(de, en)

    blocks = []
    for m in re.finditer(r'<div class="article-main__content"[^>]*>(.*?)</div>', art, re.S):
        b = m.group(1)
        h = re.search(r"<h[234][^>]*>(.*?)</h[234]>", b, re.S)
        if h:
            blocks.append(("head", strip_tags(h.group(1))))
            continue
        p = re.search(r"<p[^>]*>(.*?)</p>", b, re.S)
        if not p:
            continue
        raw, text = p.group(1), strip_tags(p.group(1))
        if not text:
            continue
        if text.startswith("→"):
            blocks.append(("cite", raw))
        elif re.fullmatch(r'\s*<span class="font-\[700\]">.*?</span>\s*(<!---->)?\s*', raw, re.S):
            blocks.append(("bold", text))
        else:
            blocks.append(("para", raw))

    # everything before the first section heading is the LinkedIn lede
    first = next(i for i, (k, v) in enumerate(blocks) if k == "head" and v in SECTIONS)
    lede = " ".join(b if k == "bold" else strip_tags(b)
                    for k, b in blocks[:first] if k in ("para", "bold"))
    pm = re.search(r"([\d,]+)\s+papers", lede)
    papers = int(pm.group(1).replace(",", "")) if pm else 0

    # split the rest into sections; drop the boilerplate "About …" tail
    sections, cur = {}, None
    for kind, val in blocks[first:]:
        if kind == "head" and val in SECTIONS:
            cur = val
            sections[cur] = []
            continue
        if strip_tags(val).startswith("About Vienna Research Radar"):
            break
        if cur:
            sections[cur].append((kind, val))

    return dict(num=num, title=title, day=day, month=month, year=year, cover=cover,
                credit=credit, lede=lede, papers=papers, sections=sections)


# ─── rendering ───────────────────────────────────────────────────────────────

def render_spotlight(items):
    head = next((v for k, v in items if k in ("bold", "head")), "")
    paras = "\n".join(f"              <p>\n                {inline(v)}\n              </p>"
                      for k, v in items if k == "para")
    cite = next(((citation(v)) for k, v in items if k == "cite"), (None, None))
    cite_html = f'\n            <p class="cite">\n              →\n              {cite[0]}\n            </p>' if cite[0] else ""
    return f'''          <div class="section fade-up" data-od-id="spotlight">
            <p class="section-label"><span class="dot"></span>Spotlight</p>
            <div class="spotlight-pullquote">
              {head}
            </div>
            <div class="spotlight-body">
{paras}
            </div>{cite_html}
          </div>'''


def render_radar(items):
    cards, cur = [], None
    for kind, val in items:
        if kind in ("bold", "head"):
            cur = {"head": val, "paras": [], "cite": None}
            cards.append(cur)
        elif cur and kind == "para":
            cur["paras"].append(inline(val))
        elif cur and kind == "cite":
            cur["cite"] = citation(val)[0]
    out = []
    for i, c in enumerate(cards):
        style = ""
        if len(cards) % 2 == 1 and i == len(cards) - 1:
            style = f' style="grid-column: 1 / -1; transition-delay: {i * 0.08:.2f}s"'
        elif i:
            style = f' style="transition-delay: {i * 0.08:.2f}s"'
        body = "\n".join(f'                <p class="radar-card-body">\n                  {p}\n                </p>'
                         for p in c["paras"])
        cite = (f'\n                <span class="radar-cite"\n                  >→\n                  '
                f'{c["cite"]}</span\n                >') if c["cite"] else ""
        out.append(f'''              <div class="radar-card slide-in"{style}>
                <h3 class="radar-card-head">
                  {c["head"]}
                </h3>
{body}{cite}
              </div>''')
    return f'''          <div class="section fade-up" data-od-id="radar">
            <p class="section-label"><span class="dot"></span>Radar Scans</p>
            <div class="radar-grid">
{chr(10).join(out)}
            </div>
          </div>''', len(cards)


def render_prose(label, sid, items):
    head = next((v for k, v in items if k in ("bold", "head")), None)
    paras = "\n".join(f"              <p>\n                {inline(v)}\n              </p>"
                      for k, v in items if k == "para")
    cite = next(((citation(v)) for k, v in items if k == "cite"), (None, None))
    cite_html = f'\n            <p class="cite">\n              →\n              {cite[0]}\n            </p>' if cite[0] else ""
    if sid == "stray":
        head_html = f'\n            <h2 class="stray-head">{head}</h2>' if head else ""
    else:
        head_html = (f'\n            <div class="spotlight-pullquote" style="font-size: clamp(18px, 2vw, 22px)">'
                     f'\n              {head}\n            </div>') if head else ""
    return f'''          <div class="section fade-up" data-od-id="{sid}">
            <p class="section-label"><span class="dot"></span>{label}</p>{head_html}
            <div class="body-copy">
{paras}
            </div>{cite_html}
          </div>'''


def render_insight(items):
    gap = ' style="margin-top: 16px"'
    paras = "\n".join(
        "              <p%s>\n                %s\n              </p>" % (gap if i else "", inline(v))
        for i, (k, v) in enumerate([b for b in items if b[0] == "para"]))
    return f'''          <div class="section fade-up" data-od-id="wwtf-insight">
            <p class="section-label"><span class="dot"></span>WWTF Insight</p>
            <div class="insight-box">
{paras}
            </div>
          </div>'''


def build_page(d, template):
    s = template.read_text(encoding="utf-8")
    n, prev = d["num"], d["num"] - 1
    date_en = f'{d["day"]} {MONTHS_EN[d["month"]]} {d["year"]}'
    img = re.sub(r"[^a-z0-9]+", "-", d["title"].lower()).strip("-") + ".jpg"

    parts, radar_n = [], 0
    for label in SECTIONS:
        items = d["sections"].get(label)
        if not items:
            continue
        if label == "Spotlight":
            block = render_spotlight(items)
        elif label == "Radar Scans":
            block, radar_n = render_radar(items)
        elif label == "WWTF Insight":
            block = render_insight(items)
        else:
            block = render_prose(label, SECTION_IDS[label], items)
        rule = "─" * max(3, 58 - len(label))
        parts.append(f"          <!-- {label.upper()} {rule} -->\n{block}")

    def swap(pattern, new, flags=re.S):
        nonlocal s
        s2, k = re.subn(pattern, lambda m: new, s, count=1, flags=flags)
        assert k == 1, f"template pattern not found: {pattern[:50]}"
        s = s2

    swap(r"<title>.*?</title>", f"<title>Issue #{n} – {d['title']} · Vienna Research Radar</title>")
    swap(r'background: url\("[^"]+"\)', f'background: url("{img}")')
    swap(r'<p class="hero-label">.*?</p>',
         f'<p class="hero-label">Issue #{n} · {date_en} · {d["papers"]} papers scanned</p>')
    swap(r'<h1 class="hero-title">.*?</h1>', f'<h1 class="hero-title">{d["title"]}</h1>')
    swap(r'<span class="sticky-nav-credit">.*?</span>',
         f'<span class="sticky-nav-credit">Cover: {d["credit"]}</span>')
    swap(r'<span class="sticky-nav-issue">.*?</span>',
         f'<span class="sticky-nav-issue">#{n} · {d["day"]} {MONTHS_EN[d["month"]]} {d["year"]}</span>')

    start = s.index('<main class="content-main" id="main-content">') + len('<main class="content-main" id="main-content">')
    s = s[:start] + "\n\n" + "\n\n".join(parts) + "\n\n        " + s[s.index("</main>", start):]

    toc = "\n".join(f'            <a href="#{SECTION_IDS[l]}"><span class="toc-dot"></span>{l}</a>'
                    for l in SECTIONS if l in d["sections"])
    swap(r'(<p class="sidebar-toc-title">In this issue</p>\n)(?:\s*<a href="#[^"]+">.*?</a>\n)+',
         re.search(r'<p class="sidebar-toc-title">In this issue</p>', s).group(0) + "\n" + toc + "\n")

    swap(r'<a href="issue-\d+\.html">\s*<svg', f'<a href="issue-{prev:02d}.html">\n        <svg')
    swap(r'<span class="issue-nav-counter">.*?</span>',
         f'<span class="issue-nav-counter">Issue {n} of {n}</span>')
    swap(r'<a href="issue-\d+\.html">\s*Next', '<a class="disabled" href="#" aria-disabled="true">\n        Next')
    words = len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", "\n".join(parts))))
    return s, img, radar_n, date_en, words


def card(d, radar_n, date_en, words):
    n = d["num"]
    teaser = re.sub(r"^[\d,]+\s+papers[^.]*\.\s*", "", d["lede"]).strip()
    pills = ["Spotlight", f"{radar_n} Radar Scans"] + [
        l for l in ("Funding Moves", "WWTF Insight", "Stray Signal") if l in d["sections"]]
    pill_html = "\n".join(f'                <span class="card-pill">{p}</span>' for p in pills)
    return f'''<a
          class="issue-card fade-up"
          href="issue-{n:02d}.html"
          aria-label="Issue #{n} – {d["title"]}, {date_en}"
        >
          <span class="card-num">#{n:02d}</span>
          <div>
            <p class="card-title">{d["title"]}</p>
            <p class="card-teaser">
              {teaser}
            </p>
            <div class="card-meta">
              <time datetime="{d["year"]}-{d["month"]:02d}-{d["day"]:02d}">{date_en}</time>
              <span class="meta-sep">/</span>
              <span>{d["papers"]} papers</span>
              <span class="meta-sep">/</span>
              <span>~{max(3, round(words / 200))} min read</span>
              <span class="meta-sep">/</span>
              <div class="card-pills" aria-label="Sections">
{pill_html}
              </div>
            </div>
          </div>
          <span class="card-arrow" aria-hidden="true">→</span>
        </a>

        '''


# ─── validation ──────────────────────────────────────────────────────────────

def crossref_check(doi, page_html, strict=True):
    """Not in the CSV (WWTF Insight papers usually aren't). Ask Crossref instead."""
    ref = doi.rsplit("doi.org/", 1)[-1]
    try:
        req = urllib.request.Request(f"https://api.crossref.org/works/{urllib.parse.quote(ref)}",
                                     headers={"User-Agent": "vienna-research-radar (mailto:benjamin.missbach@wwtf.at)"})
        with urllib.request.urlopen(req, timeout=25) as r:
            m = json.load(r)["message"]
    except Exception:
        return False, f"{doi} could not be resolved at Crossref — check the link by hand"
    journal = ((m.get("container-title") or m.get("institution") or [""])[0]
               if isinstance(m.get("container-title") or m.get("institution") or [""], list) else "")
    if isinstance(journal, dict):
        journal = journal.get("name", "")
    if not strict:
        return True, ""
    ctx = page_html[max(0, page_html.index(doi) - 40):page_html.index(doi) + 400].lower()
    if journal and journal.lower()[:12] not in ctx:
        return False, f"{doi}: Crossref says '{journal}', which is not what the citation claims"
    return True, ""


def validate(page_html, d):
    """Cross-check every DOI against research-data.csv. Returns list of warnings."""
    warn = []
    csv_path = REPO / "research-data.csv"
    if not csv_path.exists():
        return ["research-data.csv missing — DOIs not validated."]
    rows = {r["DOI"].strip().lower(): r for r in csv.DictReader(csv_path.open(encoding="utf-8"))}

    # Author/journal only make sense for the "→ Author, Journal, year" lines. WWTF
    # Insight links sit mid-sentence and name neither, so they only get a resolve check.
    cited = set()
    for block in re.findall(r'class="(?:cite|radar-cite)"[^>]*>.*?</(?:p|span)>', page_html, re.S):
        cited.update(re.findall(r'href="(https://doi\.org/[^"]+)"', block))

    for doi in sorted(set(re.findall(r'href="(https://doi\.org/[^"]+)"', page_html))):
        if doi not in cited:
            ok, note = crossref_check(doi, page_html, strict=False)
            if not ok:
                warn.append(note)
            continue
        row = rows.get(doi.lower())
        if not row:
            ok, note = crossref_check(doi, page_html)
            if not ok:
                warn.append(note)
            continue
        journal = row["Journal"].split(" (")[0].strip()
        first = row["Authors"].split(",")[0].strip()
        ctx = page_html[max(0, page_html.index(doi) - 40):page_html.index(doi) + 400]
        if first and first not in ctx:
            warn.append(f"{doi}: CSV first author '{first}' does not appear near the citation")
        elif journal and journal.lower()[:12] not in ctx.lower():
            warn.append(f"{doi}: CSV journal '{journal}' does not match the cited journal")
    for prev in sorted(REPO.glob("issue-*.html")):
        if prev.name == f"issue-{d['num']:02d}.html":
            continue
        old = set(re.findall(r'href="(https://doi\.org/[^"]+)"', prev.read_text(encoding="utf-8")))
        for doi in old & set(re.findall(r'href="(https://doi\.org/[^"]+)"', page_html)):
            warn.append(f"{doi} already appears in {prev.name}")
    return warn


# ─── main ────────────────────────────────────────────────────────────────────

def mail(subject, body):
    """Config file ~/.radar-smtp: host, port, user, password, to — one key=value per line."""
    import smtplib, ssl
    from email.message import EmailMessage
    cfg_path = Path.home() / ".radar-smtp"
    if not cfg_path.exists():
        print("(--mail: ~/.radar-smtp missing, not sending)")
        return
    cfg = dict(l.split("=", 1) for l in cfg_path.read_text().splitlines()
               if l.strip() and not l.startswith("#"))
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = subject, cfg["user"], cfg["to"]
    m.set_content(body)
    with smtplib.SMTP(cfg["host"], int(cfg.get("port", 587))) as srv:
        srv.ehlo(); srv.starttls(context=ssl.create_default_context())
        srv.login(cfg["user"], cfg["password"])
        srv.send_message(m)
    print(f'(--mail: sent to {cfg["to"]})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="LinkedIn pulse URL (default: newest on the newsletter index)")
    ap.add_argument("--publish", action="store_true", help="run publish-issue.py when clean")
    ap.add_argument("--force", action="store_true", help="rebuild even if the issue already exists")
    ap.add_argument("--out", help="write the page here instead of the repo (dry run)")
    ap.add_argument("--mail", action="store_true",
                    help="email this run's output (config: ~/.radar-smtp). For cron.")
    args = ap.parse_args()

    transcript = []

    def say(*a):                              # tee the console output into the mail body
        line = " ".join(str(x) for x in a)
        print(line)
        transcript.append(line)

    if args.url:
        url = args.url
    else:
        n, url = newest_linkedin_issue()
        if n <= highest_local_issue() and not args.force:
            say(f"Nothing new: LinkedIn is at #{n}, site is at #{highest_local_issue()}.")
            return 0
        say(f"New issue on LinkedIn: #{n}")

    d = parse_article(fetch(url))
    say(f'#{d["num"]} "{d["title"]}" · {d["day"]}.{d["month"]}.{d["year"]} · {d["papers"]} papers')
    missing = [s for s in SECTIONS if s not in d["sections"]]
    if missing:
        say(f"  sections absent from this issue: {', '.join(missing)}")

    template = REPO / f'issue-{d["num"] - 1:02d}.html'
    if not template.exists():
        sys.exit(f"Template {template.name} not found — need the previous issue to copy from.")

    page, img, radar_n, date_en, words = build_page(d, template)

    out = Path(args.out) if args.out else REPO / f'issue-{d["num"]:02d}.html'
    out.write_text(page, encoding="utf-8")
    say(f"Wrote {out.name} ({radar_n} radar cards, ~{round(words / 200)} min read)")

    if not args.out:
        img_path = REPO / img
        if not img_path.exists():
            req = urllib.request.Request(d["cover"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, img_path.open("wb") as f:
                shutil.copyfileobj(r, f)
            say(f"Downloaded cover: {img} ({img_path.stat().st_size // 1024} KB)")

        issues = REPO / "issues.html"
        h = issues.read_text(encoding="utf-8")
        anchor = '<a\n          class="issue-card fade-up"'
        if f'href="issue-{d["num"]:02d}.html"' not in h:
            issues.write_text(h.replace(anchor, card(d, radar_n, date_en, words) + anchor, 1), encoding="utf-8")
            say("Added the card to issues.html")

        prev = REPO / f'issue-{d["num"] - 1:02d}.html'
        ph = prev.read_text(encoding="utf-8")
        if '<a class="disabled" href="#" aria-disabled="true">\n        Next' in ph:
            prev.write_text(ph.replace('<a class="disabled" href="#" aria-disabled="true">\n        Next',
                                       f'<a href="issue-{d["num"]:02d}.html">\n        Next', 1), encoding="utf-8")
            say(f"Linked Next from {prev.name}")

    warnings = validate(page, d)
    say()
    if warnings:
        say(f"{len(warnings)} thing(s) to check before this goes live:")
        for w in warnings:
            say(f"  ! {w}")
    else:
        say("All DOIs match research-data.csv and none are reused from earlier issues.")

    if args.publish and not args.out:
        if warnings:
            say("\nNot publishing while warnings are open. Fix them, then run publish-issue.py.")
            return 1
        subprocess.run([sys.executable, str(REPO / "scripts/publish-issue.py"),
                        f'issue-{d["num"]:02d}.html', d["title"],
                        f'{d["year"]}-{d["month"]:02d}-{d["day"]:02d}', str(d["papers"])], check=True)
    else:
        say(f'\nReview it, then:  python3 scripts/publish-issue.py issue-{d["num"]:02d}.html '
              f'"{d["title"]}" {d["year"]}-{d["month"]:02d}-{d["day"]:02d} {d["papers"]}')

    if args.mail:
        mail(f'Radar issue #{d["num"]} drafted: {d["title"]}', "\n".join(transcript))
    return 0


if __name__ == "__main__":
    sys.exit(main())
