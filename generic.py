# -*- coding: utf-8 -*-
"""Couche 2 : lecture générique d'un site carrière sans API : fiches JSON-LD « JobPosting » + plan du site (sitemap.xml).
Aucune IA. Renvoie des offres normalisées avec liens directs, plus un diagnostic de lecture par entreprise."""
import json, re, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import ats

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept-Language": "fr-FR,fr;q=0.9"}
JOBURL = re.compile(r"(job|jobs|offre|offres|emploi|emplois|career|careers|carriere|carrieres|vacanc|position|recrut|poste|stellen)", re.I)
LD = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)

def fetch(url, timeout=15, limit=1500000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(limit)
        if url.endswith(".gz") or raw[:2] == b"\x1f\x8b":
            import gzip; raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")

def jobpostings(html):
    out = []
    def walk(x):
        if isinstance(x, list):
            for y in x: walk(y)
        elif isinstance(x, dict):
            t = x.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                out.append(x)
            for k in ("@graph", "itemListElement", "item", "mainEntity"):
                if k in x: walk(x[k])
    for m in LD.finditer(html):
        try: walk(json.loads(m.group(1).strip()))
        except Exception: pass
    return out

def to_offer(p, url):
    loc = p.get("jobLocation")
    locs = loc if isinstance(loc, list) else [loc] if loc else []
    txt = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, dict):
            txt.append("%s %s %s %s" % (a.get("addressLocality", ""), a.get("addressRegion", ""), a.get("postalCode", ""), a.get("addressCountry", "") if isinstance(a.get("addressCountry"), str) else ""))
    et = p.get("employmentType")
    et = ", ".join(et) if isinstance(et, list) else (et or "NC")
    org = p.get("hiringOrganization")
    return dict(title=p.get("title") or p.get("name"), location=" ".join(txt), url=p.get("url") or url, date=(p.get("datePosted") or "")[:10],
                ref="ld" + (str(p.get("identifier") or url))[:80], contract=et)

def sitemap_urls(origin, maxfiles=10):
    seen, queue, urls = set(), [], []
    try:
        for m in re.finditer(r"(?im)^sitemap:\s*(\S+)", fetch(origin + "/robots.txt", 10)):
            queue.append(m.group(1))
    except Exception:
        pass
    queue += [origin + "/sitemap.xml", origin + "/sitemap_index.xml"]
    while queue and len(seen) < maxfiles:
        u = queue.pop(0)
        if u in seen: continue
        seen.add(u)
        try: xml = fetch(u, 15, 6000000)
        except Exception: continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
        if "<sitemapindex" in xml:
            queue = [x for x in locs if JOBURL.search(x)] + queue
        else:
            urls += [x for x in locs if JOBURL.search(x)]
    return urls

def regdom(u):
    h = urllib.parse.urlparse(u).netloc.lower().split(":")[0].split(".")
    return ".".join(h[-2:]) if len(h) >= 2 else ".".join(h)

DETAIL = re.compile(r"/(job|jobs|offre|offres|offre-emploi|emploi|poste|postes|career|careers|carriere|carrieres|vacancy|vacancies|position|positions|recrutement|stellenangebote)[^/]*/[^/]+", re.I)

def read_company(name, pages):
    """Renvoie (offres, diagnostic)."""
    diag = {"jsonld": 0, "sitemap_urls": 0, "lues": 0, "jobs_sm": 0}
    offers, done = [], set()
    for page in pages[:2]:
        try:
            html = fetch(page)
        except Exception:
            continue
        for p in jobpostings(html):
            diag["jsonld"] += 1; offers.append(to_offer(p, page))
        pu = urllib.parse.urlparse(page)
        origin = "%s://%s" % (pu.scheme, pu.netloc)
        if origin in done: continue
        done.add(origin)
        urls = [u for u in sitemap_urls(origin) if regdom(u) == regdom(page)]
        diag["sitemap_urls"] += len(urls)
        diag["jobs_sm"] += sum(1 for u in urls if DETAIL.search(urllib.parse.urlparse(u).path) and (re.search(r"\d", u.rsplit("/", 1)[-1]) or u.rsplit("/", 1)[-1].count("-") >= 3))
        cand = []
        for u in urls:
            slug = urllib.parse.unquote(u.rstrip("/").split("/")[-1]).replace("-", " ").replace("_", " ")
            if ats.ROLE.search(ats.norm(slug)): cand.append(u)
        for u in cand[:40]:
            try:
                for p in jobpostings(fetch(u, 12)):
                    diag["lues"] += 1; offers.append(to_offer(p, u))
            except Exception:
                continue
    return offers, diag

def run(items, budget_s=2400, workers=16):
    """items : liste de (company dict, [pages]). Renvoie (offres brutes, diagnostics par nom)."""
    t0, raw, diags = time.time(), [], {}
    def one(it):
        c, pages = it
        if time.time() - t0 > budget_s: return c, [], {"skip": True}
        try: return (c,) + read_company(c["name"], pages)
        except Exception as e: return c, [], {"err": str(e)[:60]}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, offers, diag in ex.map(one, items):
            diags[c["name"]] = diag
            for j in offers:
                if ats.relevant(j):
                    raw.append({"src": "Site carrière (générique)", "title": j["title"], "company": c["name"], "location": j["location"], "contract": j["contract"],
                                "salary": "NA", "date": j["date"], "url": j["url"], "ref": j["ref"], "desc": ""})
    return raw, diags
