# -*- coding: utf-8 -*-
"""Filet 2 : les job boards, interrogés NOM D'ENTREPRISE PAR NOM D'ENTREPRISE.
Sources : Jooble, CareerJet, Adzuna (APIs avec clé), Indeed (JobSpy), Brave (site: sur WTTJ/Apec/Hellowork/Indeed).
Pour chaque entreprise : combien d'annonces de CETTE entreprise chaque source a vues (preuve de lecture),
et les offres pertinentes (rôle + Île-de-France). Aucune IA."""
import json, os, re, sys, time, threading, urllib.request, urllib.parse, urllib.error, base64
from concurrent.futures import ThreadPoolExecutor
import ats

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

def base_name(name):
    n = ats.norm(name)
    b = re.sub(r"\s+", " ", ats.SUFFIX.sub(" ", n)).strip()
    return b if len(b) >= 3 else n

def same_company(found, name):
    f, b = ats.norm(found), base_name(name)
    if not f or not b: return False
    return (" " + b + " ") in (" " + f + " ") or (" " + f + " ") in (" " + b + " ") and len(f) >= 4

def _req(url, data=None, headers=None, method=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "application/json"}; h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try: body = e.read().decode("utf-8", "replace")[:90].replace("\n", " ")
        except Exception: body = ""
        raise RuntimeError("HTTP %s %s" % (e.code, body))

def jooble(name, key):
    out = []
    for kw in (name, name + " commercial offres"):
        r = _req("https://jooble.org/api/" + key, json.dumps({"keywords": kw, "location": "Île-de-France", "page": "1"}).encode(),
                 {"Content-Type": "application/json"}, "POST")
        for j in r.get("jobs", []) or []:
            if same_company(j.get("company"), name):
                out.append(dict(title=re.sub(r"<[^>]+>", "", j.get("title") or ""), company=j.get("company"), location=j.get("location") or "",
                                url=j.get("link") or "", date=(j.get("updated") or "")[:10], ref="jb%s" % j.get("id"), contract=j.get("type") or "NC"))
        time.sleep(0.3)
    return out

_DEAD = {}

def careerjet(name, key):
    if _DEAD.get("careerjet"): raise RuntimeError(_DEAD["careerjet"])
    out = []
    auth = base64.b64encode((key + ":").encode()).decode()
    for kw in (name, name + " commercial offres"):
        q = urllib.parse.urlencode({"locale_code": "fr_FR", "keywords": kw, "location": "Île-de-France", "user_ip": "81.250.10.10",
                                    "user_agent": UA, "page_size": 50, "page": 1, "sort": "date"})
        try:
            r = _req("https://search.api.careerjet.net/v4/query?" + q, headers={"Authorization": "Basic " + auth})
        except RuntimeError as e:
            if "HTTP 403" in str(e) or "HTTP 401" in str(e): _DEAD["careerjet"] = str(e)
            raise
        for j in r.get("jobs", []) or []:
            if same_company(j.get("company"), name):
                out.append(dict(title=re.sub(r"<[^>]+>", "", j.get("title") or ""), company=j.get("company"), location=j.get("locations") or "",
                                url=j.get("url") or "", date=(j.get("date") or "")[:10], ref="cj%s" % (j.get("url") or "")[-60:], contract="NC"))
        time.sleep(0.3)
    return out

def adzuna(name, aid, akey):
    out = []
    for kw in (name, name + " commercial"):
        q = urllib.parse.urlencode({"app_id": aid, "app_key": akey, "results_per_page": 50, "what": kw, "where": "Île-de-France", "sort_by": "date"})
        r = _req("https://api.adzuna.com/v1/api/jobs/fr/search/1?" + q)
        for j in r.get("results", []) or []:
            if same_company((j.get("company") or {}).get("display_name"), name):
                out.append(dict(title=j.get("title") or "", company=(j.get("company") or {}).get("display_name"), location=(j.get("location") or {}).get("display_name") or "",
                                url=j.get("redirect_url") or "", date=(j.get("created") or "")[:10], ref="az%s" % j.get("id"), contract="NC"))
        time.sleep(0.3)
    return out

_JS = {"lib": None}
_jlock = threading.Lock()

def indeed(name):
    if _JS["lib"] is None:
        try:
            import jobspy; _JS["lib"] = jobspy
        except Exception:
            try:
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "python-jobspy"], check=True, timeout=300)
                import jobspy; _JS["lib"] = jobspy
            except Exception as e:
                _JS["lib"] = False; raise RuntimeError("jobspy indisponible: %s" % str(e)[:60])
    if _JS["lib"] is False: raise RuntimeError("jobspy indisponible")
    out = []
    with _jlock:  # une requête à la fois (anti-blocage)
        df = _JS["lib"].scrape_jobs(site_name=["indeed"], search_term=name, location="Île-de-France, France", country_indeed="France",
                                    results_wanted=60, distance=50, verbose=0)
        time.sleep(1.5)
    for _, j in df.iterrows():
        if same_company(str(j.get("company") or ""), name):
            out.append(dict(title=str(j.get("title") or ""), company=str(j.get("company")), location=str(j.get("location") or ""),
                            url=str(j.get("job_url") or ""), date=str(j.get("date_posted") or "")[:10], ref="in%s" % str(j.get("job_url") or "")[-60:], contract="NC"))
    return out

def brave(name, key):
    if _DEAD.get("brave"): raise RuntimeError(_DEAD["brave"])
    q = '"%s" offre emploi (site:welcometothejungle.com OR site:apec.fr OR site:hellowork.com OR site:fr.indeed.com OR site:linkedin.com/jobs)' % name
    try:
        r = _req("https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": q, "count": 20, "country": "fr"}),
                 headers={"X-Subscription-Token": key})
    except RuntimeError as e:
        if "HTTP 402" in str(e) or "HTTP 401" in str(e) or "HTTP 403" in str(e): _DEAD["brave"] = "Brave indisponible (quota/clé): " + str(e)[:50]
        raise
    out = []
    for w in (r.get("web") or {}).get("results", []) or []:
        t = re.sub(r"<[^>]+>", "", w.get("title") or "")
        if same_company(t, name) or (" " + base_name(name) + " ") in (" " + ats.norm(w.get("url")) + " ") or base_name(name) in ats.norm(t):
            out.append(dict(title=t, company=name, location="", url=w.get("url") or "", date="", ref="br%s" % (w.get("url") or "")[-60:], contract="NC"))
    time.sleep(1.1)
    return out

def role_search(which, keywords):
    """Recherche par métier (offres HORS liste d'entreprises). which = 'jooble' | 'careerjet' | 'indeed'."""
    out = []
    for kw in keywords:
        try:
            if which == "jooble" and os.environ.get("JOOBLE_API_KEY"):
                for pg in ("1", "2"):
                    r = _req("https://jooble.org/api/" + os.environ["JOOBLE_API_KEY"], json.dumps({"keywords": kw, "location": "Île-de-France", "page": pg}).encode(),
                             {"Content-Type": "application/json"}, "POST")
                    for j in r.get("jobs", []) or []:
                        out.append(dict(src="Job board (jooble)", title=re.sub(r"<[^>]+>", "", j.get("title") or ""), company=j.get("company") or "", location=j.get("location") or "",
                                        contract=j.get("type") or "NC", salary=j.get("salary") or "NA", date=(j.get("updated") or "")[:10], url=j.get("link") or "", ref="jb%s" % j.get("id"), desc=(j.get("snippet") or "")[:600]))
            elif which == "careerjet" and os.environ.get("CAREERJET_API_KEY"):
                auth = base64.b64encode((os.environ["CAREERJET_API_KEY"] + ":").encode()).decode()
                for pg in (1, 2):
                    q = urllib.parse.urlencode({"locale_code": "fr_FR", "keywords": kw, "location": "Île-de-France", "user_ip": "81.250.10.10", "user_agent": UA,
                                                "page_size": 50, "page": pg, "sort": "date", "contract_type": "p"})
                    r = _req("https://search.api.careerjet.net/v4/query?" + q, headers={"Authorization": "Basic " + auth})
                    for j in r.get("jobs", []) or []:
                        out.append(dict(src="Job board (careerjet)", title=re.sub(r"<[^>]+>", "", j.get("title") or ""), company=j.get("company") or "", location=j.get("locations") or "",
                                        contract="NC", salary=j.get("salary") or "NA", date=(j.get("date") or "")[:10], url=j.get("url") or "", ref="cj%s" % (j.get("url") or "")[-60:], desc=re.sub(r"<[^>]+>", "", j.get("description") or "")[:600]))
            elif which == "indeed":
                if _JS["lib"] is None:
                    try: import jobspy; _JS["lib"] = jobspy
                    except Exception:
                        import subprocess
                        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "python-jobspy"], check=True, timeout=300)
                        import jobspy; _JS["lib"] = jobspy
                df = _JS["lib"].scrape_jobs(site_name=["indeed"], search_term=kw, location="Île-de-France, France", country_indeed="France", results_wanted=80, distance=50, job_type="fulltime", verbose=0)
                for _, j in df.iterrows():
                    out.append(dict(src="Job board (indeed)", title=str(j.get("title") or ""), company=str(j.get("company") or ""), location=str(j.get("location") or ""), contract="CDI",
                                    salary="NA", date=str(j.get("date_posted") or "")[:10], url=str(j.get("job_url") or ""), ref="in%s" % str(j.get("job_url") or "")[-60:], desc=str(j.get("description") or "")[:600]))
        except Exception as e:
            print("role_search", which, kw, e, file=sys.stderr)
        time.sleep(1.0)
    return out

def run(companies, budget_s=900):
    keys = {k: os.environ.get(k) for k in ("JOOBLE_API_KEY", "CAREERJET_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "BRAVE_API_KEY")}
    t0 = time.time()
    raw, diag = [], {}
    lock = threading.Lock()

    def one(c):
        name = c["name"]
        d = {"ok": [], "n": {}, "err": {}}
        allj = []
        steps = []
        if keys["JOOBLE_API_KEY"]: steps.append(("jooble", lambda: jooble(name, keys["JOOBLE_API_KEY"])))
        if keys["CAREERJET_API_KEY"]: steps.append(("careerjet", lambda: careerjet(name, keys["CAREERJET_API_KEY"])))
        if keys["ADZUNA_APP_ID"] and keys["ADZUNA_APP_KEY"]: steps.append(("adzuna", lambda: adzuna(name, keys["ADZUNA_APP_ID"], keys["ADZUNA_APP_KEY"])))
        steps.append(("indeed", lambda: indeed(name)))
        for label, fn in steps:
            if time.time() - t0 > budget_s: d["err"][label] = "budget"; continue
            try:
                js = fn(); d["ok"].append(label); d["n"][label] = len(js)
                for j in js: j["_src"] = label
                allj += js
            except Exception as e:
                d["err"][label] = str(e)[:70]
        if not allj and keys["BRAVE_API_KEY"] and time.time() - t0 < budget_s:
            try:
                js = brave(name, keys["BRAVE_API_KEY"]); d["ok"].append("brave"); d["n"]["brave"] = len(js)
                for j in js: j["_src"] = "brave"
                allj += js
            except Exception as e:
                d["err"]["brave"] = str(e)[:70]
        with lock:
            diag[name] = d
            seen = set()
            for j in allj:
                if not j["title"] or (ats.norm(j["title"]), j["url"]) in seen: continue
                seen.add((ats.norm(j["title"]), j["url"]))
                if j["_src"] != "brave" and ats.relevant(j):  # brave = simple preuve de présence, pas une offre
                    raw.append({"src": "Job board (%s)" % j["_src"], "title": j["title"], "company": name, "location": j["location"], "contract": j["contract"],
                                "salary": "NA", "date": j["date"], "url": j["url"], "ref": j["ref"], "desc": ""})
    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(one, companies))
    return raw, diag
