# -*- coding: utf-8 -*-
"""Sites carrières employeurs (liens directs, sans clé, sans IA).
Pour chaque entreprise de la liste, on sonde les ATS publics (Greenhouse, Lever, SmartRecruiters,
Recruitee, Workable) avec plusieurs variantes de nom, et on lit les offres. Workday : via ats.json.
Résultat des sondes : out/ats_found.json (permet de voir quelles entreprises sont couvertes)."""
import json, os, re, sys, time, urllib.request, urllib.parse, unicodedata
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (veille-emplois)", "Accept": "application/json"}
IDF = re.compile(r"\b(paris|ile de france|idf|nanterre|la defense|courbevoie|puteaux|boulogne|issy|levallois|clichy|saint denis|"
                 r"montreuil|noisy|rueil|colombes|asnieres|gennevilliers|velizy|montigny|saint quentin|guyancourt|massy|palaiseau|"
                 r"orsay|saclay|gif sur yvette|evry|creteil|vitry|ivry|villejuif|fontenay|nogent|rosny|bagnolet|pantin|aubervilliers|"
                 r"le bourget|roissy|cergy|pontoise|versailles|marne la vallee|champs sur marne|melun|meaux|meudon|sevres|suresnes|"
                 r"neuilly|malakoff|montrouge|vanves|chatillon|bagneux|arcueil|gentilly|bobigny|bondy|villepinte|saint ouen|"
                 r"cachan|antony|chatenay|clamart|le plessis|rungis|orly|choisy|alfortville|maisons alfort|charenton|"
                 r"(?:75|77|78|91|92|93|94|95)\d{3})\b")
ROLE = re.compile(r"\b(offre|offres|appel|appels|tender|bid|proposal|chiffrage|key account|kam|grands comptes|commercial\w*|"
                  r"affaires|business manager|account manager|business developer|vente|ventes|sales)\b")
SUFFIX = re.compile(r"\b(sas|sa|sarl|group|groupe|france|holding|international|industries|industrie|technologies|systems|systemes)\b")

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()

def slugs(name):
    n = norm(name)
    base = re.sub(r"\s+", " ", SUFFIX.sub(" ", n)).strip() or n
    out = []
    for x in (base, n):
        w = x.split()
        for s in ("".join(w), "-".join(w), "".join(w[:2]), w[0] if w else ""):
            if len(s) >= 5 and s not in out:
                out.append(s)
    return out[:6]

def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def post(url, body, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=dict(UA, **{"Content-Type": "application/json"}), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

# Chaque lecteur renvoie une liste d'offres normalisées, ou lève une exception / renvoie [] si inconnu.
def greenhouse(s):
    r = get("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % s)
    return [dict(title=j.get("title"), location=(j.get("location") or {}).get("name", ""), url=j.get("absolute_url", ""),
                 date=(j.get("updated_at") or "")[:10], ref="gh%s" % j.get("id"), contract="NC") for j in r.get("jobs", [])]

def lever(s):
    r = get("https://api.lever.co/v0/postings/%s?mode=json" % s)
    return [dict(title=j.get("text"), location=(j.get("categories") or {}).get("location", ""), url=j.get("hostedUrl", ""),
                 date=time.strftime("%Y-%m-%d", time.gmtime((j.get("createdAt") or 0) / 1000)), ref="lv%s" % j.get("id"),
                 contract=(j.get("categories") or {}).get("commitment", "NC")) for j in r] if isinstance(r, list) else []

def smartrecruiters(s):
    out, off = [], 0
    while off < 500:
        r = get("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=100&offset=%d&country=fr" % (s, off))
        c = r.get("content") or []
        for j in c:
            l = j.get("location") or {}
            out.append(dict(title=j.get("name"), location="%s %s" % (l.get("city", ""), l.get("region", "")),
                            url="https://jobs.smartrecruiters.com/%s/%s" % (s, j.get("id")), date=(j.get("releasedDate") or "")[:10],
                            ref="sr%s" % j.get("id"), contract=(j.get("typeOfEmployment") or {}).get("label", "NC")))
        if len(c) < 100: break
        off += 100
    return out

def recruitee(s):
    r = get("https://%s.recruitee.com/api/offers/" % s)
    return [dict(title=j.get("title"), location="%s %s" % (j.get("city", ""), j.get("country", "")), url=j.get("careers_url", ""),
                 date=(j.get("published_at") or "")[:10], ref="rc%s" % j.get("id"), contract=j.get("employment_type_code", "NC")) for j in r.get("offers", [])]

def workable(s):
    r = get("https://apply.workable.com/api/v1/widget/accounts/%s" % s)
    return [dict(title=j.get("title"), location="%s %s" % (j.get("city", ""), j.get("country", "")), url=j.get("url", ""),
                 date=(j.get("published_on") or "")[:10], ref="wk%s" % j.get("shortcode"), contract="NC") for j in r.get("jobs", [])]

def workday(host, tenant, site):
    out, off = [], 0
    while off < 1000:
        r = post("https://%s/wday/cxs/%s/%s/jobs" % (host, tenant, site), {"appliedFacets": {}, "limit": 20, "offset": off, "searchText": ""})
        c = r.get("jobPostings") or []
        for j in c:
            out.append(dict(title=j.get("title"), location=j.get("locationsText", ""), url="https://%s/%s%s" % (host, site, j.get("externalPath", "")),
                            date="", ref="wd%s" % j.get("externalPath"), contract="NC"))
        if len(c) < 20: break
        off += 20
    return out

DEBUG = []

def workday_discover(s):
    """Devine le site Workday public : <s>.wdN.myworkdayjobs.com -> redirection vers /<langue>/<site>."""
    for n in (1, 3, 5, 12, 103, 501, 502):
        host = "%s.wd%d.myworkdayjobs.com" % (s, n)
        try:
            req = urllib.request.Request("https://%s/" % host, headers={"User-Agent": UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=8) as r:
                parts = [p for p in urllib.parse.urlparse(r.geturl()).path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
        except Exception:
            continue
        DEBUG.append("%s -> %s" % (host, "/".join(parts)))
        if parts:
            jobs = workday(host, s, parts[0])
            if jobs:
                return jobs
    return []

def oracle(url):
    """Oracle Recruiting Cloud (HCM CandidateExperience) : API REST publique, sans authentification."""
    m = re.search(r"https://([^/]+)/hcmUI/CandidateExperience/(?:[A-Za-z_-]{2,6}/)?sites/([A-Za-z0-9_]+)", url)
    if not m:
        return []
    host, site, out, off = m.group(1), m.group(2), [], 0
    while off < 1000:
        q = urllib.parse.urlencode({"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                                    "finder": "findReqs;siteNumber=%s,limit=50,offset=%d,sortBy=POSTING_DATES_DESC" % (site, off)})
        r = get("https://%s/hcmRestApi/resources/latest/recruitingCEJobRequisitions?%s" % (host, q), timeout=25)
        items = r.get("items") or []
        c = (items[0].get("requisitionList") if items else None) or []
        for j in c:
            out.append(dict(title=j.get("Title"), location=j.get("PrimaryLocation", ""), date=(j.get("PostedDate") or "")[:10],
                            url="https://%s/hcmUI/CandidateExperience/en/sites/%s/job/%s" % (host, site, j.get("Id")),
                            ref="or%s" % j.get("Id"), contract="NC"))
        if len(c) < 50: break
        off += 50
    return out

READERS = [("greenhouse", greenhouse), ("lever", lever), ("smartrecruiters", smartrecruiters), ("recruitee", recruitee), ("workable", workable), ("workday", workday_discover)]

def probe(c):
    """Teste les ATS pour une entreprise ; renvoie (id, (ats, slug), offres)."""
    for s in slugs(c["name"]):
        for label, fn in READERS:
            try:
                jobs = fn(s)
            except Exception:
                continue
            if jobs:
                return c["id"], (label, s), jobs
    return c["id"], None, []

def relevant(j):
    t = norm(j.get("title"))
    if not ROLE.search(t): return False
    loc = norm(j.get("location"))
    return bool(IDF.search(loc)) or loc in ("", "france")

def run(companies):
    """companies : liste de dicts {id,name,list,flags}. Renvoie (offres brutes, rapport de couverture)."""
    raw, found = [], {}
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(HERE, "ats.json"), encoding="utf-8"))
    except Exception:
        pass
    byid = {c["id"]: c for c in companies}
    def add(c, label, jobs):
        for j in jobs:
            if relevant(j):
                raw.append({"src": "Site carrière (%s)" % label, "title": j["title"], "company": c["name"], "location": j["location"],
                            "contract": j["contract"], "salary": "NA", "date": j["date"], "url": j["url"], "ref": j["ref"], "desc": ""})
    for w in cfg.get("workday", []):
        c = next((x for x in companies if norm(x["name"]) == norm(w["company"])), None)
        try:
            jobs = workday(w["host"], w["tenant"], w["site"])
            if c:
                found[c["id"]] = ["workday", w["tenant"], len(jobs)]
                add(c, "workday", jobs)
        except Exception as e:
            print("workday", w, e, file=sys.stderr)
    # sites découverts automatiquement (cache out/discovery.json)
    try:
        import discover
        cache = discover.run(companies)
    except Exception as e:
        print("découverte : échec", e, file=sys.stderr); cache = {}
    for c in companies:
        d = cache.get(str(c["id"])) or {}
        try:
            if d.get("t") == "workday":
                jobs = workday(d["host"], d["tenant"], d["site"])
            elif d.get("t") == "oracle":
                jobs = oracle(d.get("url", ""))
            elif d.get("t") in ("greenhouse", "lever", "smartrecruiters", "recruitee", "workable"):
                jobs = dict(READERS)[d["t"]](d["slug"])
            else:
                continue
        except Exception as e:
            print("lecture", c["name"], e, file=sys.stderr); continue
        found[c["id"]] = [d["t"], d.get("slug") or d.get("tenant"), len(jobs)]
        add(c, d["t"], jobs)
    # couche 2 : JSON-LD + sitemap pour toutes les entreprises non lues par API
    gdiag = {}
    try:
        import generic
        items = []
        for c in companies:
            d = cache.get(str(c["id"])) or {}
            if c["id"] in found: continue
            pages = [p for p in ([d.get("page")] + (d.get("pages") or [])) if p]
            if pages: items.append((c, pages))
        graw, gdiag = generic.run(items, budget_s=1800)
        raw += graw
        for c, _ in items:
            g = gdiag.get(c["name"]) or {}
            if g.get("jsonld") or g.get("sitemap_urls"):
                found[c["id"]] = ["générique", "", g.get("jsonld", 0) + g.get("lues", 0)]
    except Exception as e:
        print("couche 2 : échec", e, file=sys.stderr)
    # couche 3 : navigateur automatique pour toutes les entreprises encore non lues
    bdiag = {}
    try:
        import browser
        items = []
        for c in companies:
            d = cache.get(str(c["id"])) or {}
            if c["id"] in found: continue
            pages = [p for p in ([d.get("page"), d.get("url")] + (d.get("pages") or [])) if p and p.startswith("http")]
            if pages: items.append((c, pages))
        braw, bdiag = browser.run(items, budget_s=1500)
        raw += braw
        for c, _ in items:
            if (bdiag.get(c["name"]) or {}).get("navigateur"):
                found[c["id"]] = ["navigateur", "", bdiag[c["name"]]["navigateur"]]
    except Exception as e:
        print("couche 3 : échec", e, file=sys.stderr)
    todo = [c for c in companies if c["id"] not in found] if os.environ.get("PROBE") else []
    with ThreadPoolExecutor(max_workers=24) as ex:
        for cid, hit, jobs in ex.map(probe, todo):
            if hit:
                found[cid] = [hit[0], hit[1], len(jobs)]
                add(byid[cid], hit[0], jobs)
    return raw, {"couvertes": len(found), "total": len(companies), "detail": {byid[k]["name"]: v for k, v in found.items()},
                  "debug_workday": DEBUG[:40], "_cache": cache, "generique": gdiag, "navigateur": bdiag, "non_couvertes": [c["name"] for c in companies if c["id"] not in found],
                  "decouverte": {t: sum(1 for v in cache.values() if v.get("t") == t) for t in set(v.get("t") for v in cache.values())}}
