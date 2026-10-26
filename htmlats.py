# -*- coding: utf-8 -*-
"""Lecteurs des ATS à pages HTML : SuccessFactors, TalentSoft, iCIMS, Jobaffinity (Taleo -> navigateur/boards).
Lecture par pagination HTTP simple, sans clé. Renvoie [] si rien de lisible (les autres filets prennent le relais)."""
import re, html, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept-Language": "fr-FR,fr;q=0.9"}
A = re.compile(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.geturl()

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()

def collect(page_html, base, pat, seen, out):
    n = 0
    for href, inner in A.findall(page_html):
        if not re.search(pat, href, re.I): continue
        t = clean(inner)
        if not (6 <= len(t) <= 160): continue
        u = urllib.parse.urljoin(base, html.unescape(href))
        if u in seen: continue
        seen.add(u); n += 1
        out.append(dict(title=t, location="", url=u, date="", ref="ht" + u[-60:], contract="NC"))
    return n

def successfactors(url):
    p = urllib.parse.urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    out, seen = [], set()
    if "successfactors" in p.netloc or "jobs.sap.com" in p.netloc:
        starts = [url]
    else:
        starts = [base + "/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=%d"]
    for k in range(0, 600, 25):
        u = (starts[0] % k) if "%d" in starts[0] else starts[0] + ("&" if "?" in starts[0] else "?") + "startrow=%d" % k
        try: h, _ = fetch(u)
        except Exception: break
        if collect(h, base, r"/job/|jobId=|career_job_req_id", seen, out) == 0: break
    return out

def talentsoft(url):
    p = urllib.parse.urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    out, seen = [], set()
    for pg in range(1, 25):
        u = base + "/offre-de-emploi/liste-offres.aspx?page=%d" % pg
        try: h, _ = fetch(u)
        except Exception: break
        if collect(h, base, r"/offre-de-emploi/emploi-|detail-offre|offre-emploi", seen, out) == 0: break
    return out

def icims(url):
    p = urllib.parse.urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    out, seen = [], set()
    for pg in range(0, 20):
        u = base + "/jobs/search?ss=1&in_iframe=1&pr=%d" % pg
        try: h, _ = fetch(u)
        except Exception: break
        if collect(h, base, r"/jobs/\d+/", seen, out) == 0: break
    return out

def jobaffinity(url):
    out, seen = [], set()
    try: h, final = fetch(url)
    except Exception: return []
    collect(h, final, r"offre|job|emploi|poste", seen, out)
    return out

READ = {"successfactors": successfactors, "talentsoft": talentsoft, "icims": icims, "jobaffinity": jobaffinity}

def read(t, url):
    fn = READ.get(t)
    if not fn or not url: return []
    try: return fn(url)
    except Exception: return []
