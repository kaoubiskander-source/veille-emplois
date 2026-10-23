#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Veille quotidienne d'offres : France Travail + Adzuna, Île-de-France, CDI.
Aucune IA : requêtes API, filtres, croisement avec la liste des 533 entreprises.
Sortie : out/jobs.json (offres normalisées, triées, avec liste A/B/hors liste).
Clés attendues dans l'environnement :
  FT_CLIENT_ID, FT_CLIENT_SECRET   (France Travail, gratuit)
  ADZUNA_APP_ID, ADZUNA_APP_KEY    (Adzuna, gratuit)
Une source absente est ignorée sans faire échouer le script.
"""
import json, os, re, sys, time, unicodedata, datetime as dt
import urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
IDF = ["75", "77", "78", "91", "92", "93", "94", "95"]
KEYWORDS = [
    "responsable d'offres", "bid manager", "proposal manager", "tender manager", "responsable appels d'offres",
    "chef de projet appels d'offres", "responsable chiffrage", "responsable offres et contrats",
    "key account manager", "responsable grands comptes", "responsable commercial", "ingénieur d'affaires",
    "ingénieur commercial", "directeur commercial", "chargé d'affaires grands comptes",
]

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9&' ]+", " ", s).replace("'", " ").strip()

# Filtres durs (mêmes règles que le moteur du dashboard)
IT_EXCL = re.compile(r"\b(sap|informatique|systemes? d information|numerique|digital|digitale|cyber\w*|cloud|logiciel\w*|saas|erp|ssii|esn|software|data|hpc|intelligence artificielle|ia)\b")
AVV_TECH = re.compile(r"\bingenieur\w*\s+(commercial\s+)?avant[- ]vente\b")
BAD_TITLE = re.compile(r"\b(stage|stagiaire|alternan\w*|apprenti\w*|interim\w*|junior|sdr|bdr|teleprospect\w*|assistant\w*)\b")
ESN = re.compile(r"\b(alten|akkodis|altran|expleo|segula|assystem|capgemini|sopra|inetum|devoteam|wavestone|ausy|aubay|extia|davidson|amaris|modis|accenture|cgi|atos|eviden|bertrandt|akka|ametra|apside|cs group|alteca|scalian|groupe sii|onepoint|niji|talan|keyrus|micropole|astek|ekium)\b")

def http_json(url, data=None, headers=None, method=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

# --------------------------------------------------------------- France Travail
def ft_token():
    cid, sec = os.environ.get("FT_CLIENT_ID"), os.environ.get("FT_CLIENT_SECRET")
    if not (cid and sec):
        return None
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec,
                                   "scope": "api_offresdemploiv2 o2dsoffre"}).encode()
    r = http_json("https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire", data=body,
                  headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    return r.get("access_token")

def ft_search(token):
    out, base = [], "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    for dep in IDF:
        for kw in KEYWORDS:
            q = urllib.parse.urlencode({"motsCles": kw, "departement": dep, "typeContrat": "CDI", "range": "0-149"})
            try:
                r = http_json(base + "?" + q, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
            except Exception as e:  # 204 (aucun résultat) ou erreur : on continue
                print("FT", dep, kw, "->", e, file=sys.stderr); time.sleep(0.4); continue
            for o in r.get("resultats", []) or []:
                out.append({"src": "France Travail", "title": o.get("intitule"), "company": (o.get("entreprise") or {}).get("nom") or "",
                            "location": (o.get("lieuTravail") or {}).get("libelle") or "", "contract": o.get("typeContrat"),
                            "salary": (o.get("salaire") or {}).get("libelle") or "NA", "date": (o.get("dateCreation") or "")[:10],
                            "url": (o.get("origineOffre") or {}).get("urlOrigine") or "", "ref": o.get("id"), "desc": (o.get("description") or "")[:600]})
            time.sleep(0.35)  # limite France Travail : ~3 req/s
    return out

# --------------------------------------------------------------- Adzuna
def adzuna_search():
    aid, akey = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (aid and akey):
        return []
    out = []
    for kw in KEYWORDS:
        for page in (1, 2):
            q = urllib.parse.urlencode({"app_id": aid, "app_key": akey, "results_per_page": 50, "what": kw,
                                        "where": "Île-de-France", "contract_permanent": 1, "sort_by": "date"})
            try:
                r = http_json("https://api.adzuna.com/v1/api/jobs/fr/search/%d?%s" % (page, q))
            except Exception as e:
                print("ADZUNA", kw, page, "->", e, file=sys.stderr); break
            for o in r.get("results", []) or []:
                out.append({"src": "Adzuna", "title": o.get("title"), "company": (o.get("company") or {}).get("display_name") or "",
                            "location": (o.get("location") or {}).get("display_name") or "", "contract": "CDI",
                            "salary": ("%s-%s" % (o.get("salary_min"), o.get("salary_max"))) if (o.get("salary_min") and str(o.get("salary_is_predicted")) in ("0", "False", "false", "None", "")) else "NA",  # estimation Adzuna = NA
                            "date": (o.get("created") or "")[:10], "url": o.get("redirect_url") or "", "ref": o.get("id"),
                            "desc": (o.get("description") or "")[:600]})
            time.sleep(0.3)
    return out

# --------------------------------------------------------------- filtres et croisement
def load_companies():
    d = json.load(open(os.path.join(HERE, "companies.json"), encoding="utf-8"))
    comp = [c for c in d["companies"] if "e" not in (c.get("flags") or "")]
    idx = [(norm(c["name"]), c) for c in comp if len(norm(c["name"])) >= 3]
    idx.sort(key=lambda x: -len(x[0]))  # les noms longs d'abord
    return idx, d.get("alias") or {}

def match_company(name, idx, alias):
    n = " " + norm(name) + " "
    for a, target in (alias.items() if isinstance(alias, dict) else []):
        if " " + norm(a) + " " in n:
            n += norm(target) + " "
    for key, c in idx:
        if " " + key + " " in n:
            return c
    return None

def keep(o):
    t, c = norm(o.get("title")), norm(o.get("company"))
    if not t or BAD_TITLE.search(t) or AVV_TECH.search(t):
        return False
    if IT_EXCL.search(t + " " + c) or ESN.search(c):
        return False
    return True

def main():
    idx, alias = load_companies()
    raw = []
    try:
        tok = ft_token()
        if tok: raw += ft_search(tok)
        else: print("France Travail : clés absentes, source ignorée", file=sys.stderr)
    except Exception as e:
        print("France Travail : échec", e, file=sys.stderr)
    raw += adzuna_search()
    seen, jobs = set(), []
    for o in raw:
        if not keep(o): continue
        k = (norm(o["company"]), norm(o["title"]), norm(o["location"]))
        if k in seen: continue
        seen.add(k)
        c = match_company(o["company"], idx, alias)
        o["wl"] = c["id"] if c else None
        o["wl_name"] = c["name"] if c else None
        o["list"] = ("A" if c["list"] == "A" else "B-liste") if c else "hors-liste"
        jobs.append(o)
    jobs.sort(key=lambda o: (o["date"] or ""), reverse=True)
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    stats = {"date": dt.date.today().isoformat(), "lus": len(raw), "retenus": len(jobs),
             "dans_liste": len([j for j in jobs if j["wl"]]), "hors_liste": len([j for j in jobs if not j["wl"]])}
    json.dump({"stats": stats, "jobs": jobs}, open(os.path.join(HERE, "out", "jobs.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(stats, ensure_ascii=False))

if __name__ == "__main__":
    main()
