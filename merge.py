# -*- coding: utf-8 -*-
import json, glob, os, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(HERE, "out")
shards = []
for p in sorted(glob.glob(os.path.join(out, "shard-*.json"))):
    try: shards.append(json.load(open(p, encoding="utf-8")))
    except Exception as e: print("shard illisible", p, e)
if not shards: raise SystemExit("aucun shard")
jobs, seen = [], set()
ats = {"couvertes": 0, "total": 0, "detail": {}, "debug_workday": [], "generique": {}, "navigateur": {}, "non_couvertes": [], "decouverte": {}}
disc, lus = {}, 0
for s in shards:
    lus += s["stats"]["lus"]
    for j in s["jobs"]:
        k = (j.get("company"), j.get("title"), j.get("location"))
        if k in seen: continue
        seen.add(k); jobs.append(j)
    a = s.get("ats") or {}
    ats["couvertes"] += a.get("couvertes", 0); ats["total"] += a.get("total", 0)
    for key in ("detail", "generique", "navigateur"): ats[key].update(a.get(key) or {})
    ats.setdefault("raison", {}).update(a.get("raison") or {})
    ats["non_couvertes"] += a.get("non_couvertes", [])
    ats["debug_workday"] += (a.get("debug_workday") or [])[:5]
    for t, n in (a.get("decouverte") or {}).items(): ats["decouverte"][t] = max(ats["decouverte"].get(t, 0), n)
    for k, v in (s.get("discovery") or {}).items():
        if k not in disc or (v.get("t") not in (None, "erreur", "inconnu") and disc[k].get("t") in (None, "erreur", "inconnu")): disc[k] = v
jobs.sort(key=lambda o: (o.get("date") or ""), reverse=True)
prev = {}
try: prev = json.load(open(os.path.join(out, "jobs.json"), encoding="utf-8"))
except Exception: pass
if not jobs and prev.get("jobs"):
    print("fusion vide : on garde l'ancien fichier"); raise SystemExit(0)
stats = {"date": dt.date.today().isoformat(), "lus": lus, "retenus": len(jobs),
         "dans_liste": len([j for j in jobs if j.get("wl")]), "hors_liste": len([j for j in jobs if not j.get("wl")]), "shards": len(shards)}
json.dump({"stats": stats, "ats": ats, "discovery": disc, "jobs": jobs}, open(os.path.join(out, "jobs.json"), "w", encoding="utf-8"), ensure_ascii=False)
for p in glob.glob(os.path.join(out, "shard-*.json")): os.remove(p)
print(json.dumps(stats, ensure_ascii=False), "couvertes", ats["couvertes"], "/", ats["total"])
