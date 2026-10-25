# -*- coding: utf-8 -*-
"""Découverte automatique du site carrière de chaque entreprise (sans IA).
Recherche web (DuckDuckGo HTML) -> pages candidates -> détection de l'ATS dans le HTML.
Le résultat est mis en cache dans out/jobs.json (clé discovery) et réutilisé chaque jour."""
import json, os, re, sys, time, urllib.request, urllib.parse
from ats import norm, UA

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = re.compile(r"(indeed|linkedin|glassdoor|facebook|twitter|youtube|wikipedia|pagesjaunes|societe\.com|infogreffe|verif\.com|"
                  r"hellowork|apec\.fr|jobijoba|monster|jooble|adzuna|talent\.com|jobteaser|cadremploi|regionsjob|welcometothejungle|"
                  r"francetravail|pole-emploi|meteojob|optioncarriere|neuvoo|jobrapido|emploi-environnement|lesjeudis|kelio|stepstone)")
PATS = [
    ("workday", re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_.-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)")),
]
OTHER = [("taleo", re.compile(r"https?://[a-z0-9.-]*taleo\.net/careersection/[^\s\"'<>]+")),
         ("successfactors", re.compile(r"https?://(?:career\d*\.successfactors\.(?:com|eu)|jobs\.sap\.com)/[^\s\"'<>]*")),
         ("oracle", re.compile(r"https?://[a-z0-9.-]*oraclecloud\.com/hcmUI/CandidateExperience[^\s\"'<>]*")),
         ("eightfold", re.compile(r"https?://[a-z0-9.-]*eightfold\.ai[^\s\"'<>]*")),
         ("icims", re.compile(r"https?://[a-z0-9.-]*icims\.com[^\s\"'<>]*")),
         ("jobaffinity", re.compile(r"https?://[a-z0-9.-]*jobaffinity\.fr[^\s\"'<>]*")),
         ("talentsoft", re.compile(r"https?://[a-z0-9.-]*talent-soft\.com[^\s\"'<>]*"))]

def web(url, data=None, timeout=15):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                                                          "Accept-Language": "fr-FR,fr;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(900000).decode("utf-8", "replace")

def brave(q):
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": q, "country": "fr", "search_lang": "fr", "count": 8})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "X-Subscription-Token": os.environ["BRAVE_API_KEY"]})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read().decode("utf-8", "replace")).get("web", {}).get("results", [])
    urls = []
    for x in res:
        u = x.get("url", "")
        if u.startswith("http") and not SKIP.search(u) and u not in urls:
            urls.append(u)
    time.sleep(1.1)  # limite gratuite : 1 requête / seconde
    return urls[:6]

def search(q):
    if os.environ.get("BRAVE_API_KEY"):
        return brave(q)
    html = web("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": q, "kl": "fr-fr"}).encode())
    urls = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', html):
        u = m.group(1)
        if "uddg=" in u:
            u = urllib.parse.unquote(u.split("uddg=")[1].split("&")[0])
        if u.startswith("//"): u = "https:" + u
        if u.startswith("http") and not SKIP.search(u) and u not in urls:
            urls.append(u)
    return urls[:6]

def plausible(name, key):
    toks = [t for t in norm(name).split() if len(t) >= 4]
    k = norm(key).replace(" ", "")
    return any(t in k or k in t for t in toks) if k else False

def detect(name, html):
    for label, rx in PATS:
        for m in rx.finditer(html):
            g = m.groups()
            if label == "workday":
                if plausible(name, g[0]):
                    return {"t": "workday", "tenant": g[0], "host": "%s.%s.myworkdayjobs.com" % (g[0], g[1]), "site": g[2]}
            elif plausible(name, g[0]):
                return {"t": label, "slug": g[0]}
    for label, rx in OTHER:
        m = rx.search(html)
        if m: return {"t": label, "url": m.group(0)[:200]}
    return None

def discover(name):
    seen = []
    try:
        urls = search("%s offres d'emploi carrières recrutement" % name)
    except Exception as e:
        return {"t": "erreur", "err": str(e)[:80]}
    for u in urls[:4]:
        try:
            html = web(u)
        except Exception:
            continue
        seen.append(u)
        d = detect(name, html)
        if d:
            d["page"] = u
            return d
    return {"t": "inconnu", "pages": seen[:2]}

def _cache_from(text):
    try:
        return json.loads(text).get("discovery") or {}
    except Exception:
        return {}

def load_cache():
    """Cache de découverte : fichier courant + historique git (auto-réparation si un passage a écrasé le cache)."""
    import subprocess
    caches = []
    try:
        caches.append(_cache_from(open(os.path.join(HERE, "out", "jobs.json"), encoding="utf-8").read()))
    except Exception:
        pass
    try:
        subprocess.run(["git", "fetch", "--unshallow", "--quiet"], cwd=HERE, timeout=120)
    except Exception:
        pass
    try:
        shas = subprocess.run(["git", "log", "--format=%H", "-n", "25", "--", "out/jobs.json"], cwd=HERE, capture_output=True, text=True, timeout=60).stdout.split()
        for sha in shas:
            r = subprocess.run(["git", "show", "%s:out/jobs.json" % sha], cwd=HERE, capture_output=True, timeout=60)
            caches.append(_cache_from(r.stdout.decode("utf-8", "replace")))
    except Exception:
        pass
    merged = {}
    for c in caches:                      # du plus récent au plus ancien
        for k, v in c.items():
            if k not in merged or (merged[k].get("t") in ("erreur",) and v.get("t") not in ("erreur",)):
                merged[k] = v
    print("cache découverte : %d entrées, %d utiles" % (len(merged), sum(1 for v in merged.values() if v.get("t") != "erreur")), file=sys.stderr)
    return merged

def save_cache(c):
    pass  # le cache est écrit dans out/jobs.json par fetch_jobs.py (clé "discovery")

def run(companies, budget_s=3300):
    """Découvre les entreprises pas encore traitées (ou en erreur) dans la limite de temps ; sauvegarde au fur et à mesure."""
    cache, t0, n, errs = load_cache(), time.time(), 0, 0
    for c in companies:
        old = cache.get(str(c["id"]))
        if old and old.get("t") != "erreur" and not (old.get("t") == "inconnu" and not old.get("pages")):
            continue
        if time.time() - t0 > budget_s:
            break
        res = dict(discover(c["name"]), name=c["name"])
        n += 1
        if res.get("t") == "erreur":
            errs += 1
            if errs >= 8 and errs == n:      # 8 erreurs d'affilée dès le début : quota ou blocage, on s'arrête
                print("découverte interrompue :", res.get("err"), file=sys.stderr); break
            if old and old.get("t") != "erreur": continue   # ne jamais écraser une bonne entrée par une erreur
        else:
            errs = 0
        cache[str(c["id"])] = res
        if n % 20 == 0: save_cache(cache)
        time.sleep(2.0)
    save_cache(cache)
    return cache
