# -*- coding: utf-8 -*-
"""Couche 3 : navigateur automatique (Playwright/Chromium). Affiche le site carrière comme un vrai visiteur,
capture les réponses JSON que le site charge lui-même (liste d'offres) et lit les liens d'offres de la page.
Aucune IA ; s'installe tout seul sur le serveur GitHub."""
import asyncio, json, os, re, subprocess, sys, time, urllib.parse
import ats

TITLE_KEYS = ("title", "jobTitle", "job_title", "Title", "name", "text", "positionTitle", "label", "intitule")
URL_KEYS = ("url", "absolute_url", "applyUrl", "jobUrl", "hostedUrl", "link", "detailUrl", "externalPath", "canonicalUrl", "href", "slug")
JOBHREF = re.compile(r"(job|offre|emploi|career|carriere|vacanc|position|poste|req|detail|apply|recrut)", re.I)
SKIPJSON = re.compile(r"(analytics|google|facebook|doubleclick|hotjar|cookie|consent|onetrust|tagmanager|sentry|segment|clarity|adobe|linkedin\.com/px)", re.I)
MORE = re.compile(r"(voir plus|afficher plus|charger plus|load more|show more|plus d.offres|suivant|next)", re.I)
REJECT = re.compile(r"(tout refuser|refuser|reject all|decline|continuer sans accepter)", re.I)

def ensure_playwright():
    try:
        import playwright  # noqa
    except Exception:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "playwright"], check=True, timeout=600)
    subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True, timeout=900)

def walk_jobs(obj, out, depth=0):
    if depth > 6: return
    if isinstance(obj, list):
        dicts = [x for x in obj if isinstance(x, dict)]
        if len(dicts) >= 3:
            for d in dicts:
                t = next((d[k] for k in TITLE_KEYS if isinstance(d.get(k), str) and 5 < len(d[k]) < 160), None)
                if not t: continue
                u = next((d[k] for k in URL_KEYS if isinstance(d.get(k), str)), "")
                loc = " ".join(str(v) for k, v in d.items() if re.search(r"(location|city|ville|lieu|region|pays|country)", k, re.I) and isinstance(v, (str, int)))
                if not loc:
                    for k, v in d.items():
                        if re.search(r"location", k, re.I) and isinstance(v, (dict, list)):
                            loc = json.dumps(v, ensure_ascii=False)[:200]
                out.append({"title": t, "url": u, "location": loc, "date": str(d.get("datePosted") or d.get("postedDate") or d.get("date") or "")[:10]})
        for x in obj[:300]: walk_jobs(x, out, depth + 1)
    elif isinstance(obj, dict):
        for v in list(obj.values())[:80]: walk_jobs(v, out, depth + 1)

async def visit(ctx, url, sem):
    async with sem:
        page = await ctx.new_page()
        found, tasks = [], []
        async def on_resp(resp):
            try:
                if "json" not in (resp.headers.get("content-type") or "") or SKIPJSON.search(resp.url): return
                body = await resp.body()
                if len(body) > 4_000_000: return
                walk_jobs(json.loads(body.decode("utf-8", "replace")), found)
            except Exception:
                pass
        page.on("response", lambda r: tasks.append(asyncio.ensure_future(on_resp(r))))
        links = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            try: await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception: pass
            try:
                btn = page.get_by_role("button", name=REJECT).first
                if await btn.count(): await btn.click(timeout=2000)
            except Exception: pass
            for _ in range(6):
                await page.mouse.wheel(0, 4000); await page.wait_for_timeout(700)
                try:
                    more = page.get_by_role("button", name=MORE).first
                    if await more.count(): await more.click(timeout=2000); await page.wait_for_timeout(1200)
                except Exception: pass
            links = await page.eval_on_selector_all("a[href]", "els => els.map(a => ({href: a.href, text: (a.innerText||'').trim()}))")
        except Exception as e:
            return found, [], str(e)[:80]
        finally:
            if tasks: await asyncio.gather(*tasks, return_exceptions=True)
            await page.close()
        base = urllib.parse.urlparse(url)
        dom = []
        for l in links:
            t, h = l.get("text", ""), l.get("href", "")
            if 12 <= len(t) <= 140 and "\n" not in t and JOBHREF.search(h) and h.startswith("http"):
                dom.append({"title": t, "url": h, "location": "", "date": ""})
        return found, dom, ""

async def amain(groups, budget_s, conc=5):
    from playwright.async_api import async_playwright
    t0, res = time.time(), {}
    sem = asyncio.Semaphore(conc)
    async with async_playwright() as p:
        br = await p.chromium.launch()
        ctx = await br.new_context(locale="fr-FR", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                                   viewport={"width": 1366, "height": 900})
        async def one(key, pages):
            if time.time() - t0 > budget_s: res[key] = ([], "skip"); return
            allj, err = [], ""
            for u in pages[:2]:
                f, d, e = await visit(ctx, u, sem)
                allj += f + d; err = e or err
            res[key] = (allj, err)
        tasks = [asyncio.ensure_future(one(k, v)) for k, v in groups.items()]
        done, pending = await asyncio.wait(tasks, timeout=budget_s + 300)
        for t in pending: t.cancel()
        for k in groups:
            res.setdefault(k, ([], "timeout"))
        try: await asyncio.wait_for(br.close(), 30)
        except Exception: pass
    return res

def run(items, budget_s=2400):
    """items : liste de (company dict, [pages]). Regroupe par site, lit chaque site une fois.
    Renvoie (offres brutes, diagnostics par nom d'entreprise)."""
    groups, members = {}, {}
    for c, pages in items:
        host = urllib.parse.urlparse(pages[0]).netloc
        groups.setdefault(host, pages); members.setdefault(host, []).append(c)
    ensure_playwright()
    res = asyncio.run(amain(groups, budget_s))
    raw, diags = [], {}
    for host, (jobs, err) in res.items():
        seen = set()
        for c in members[host]:
            diags[c["name"]] = {"navigateur": len(jobs), "err": err, "site": host}
        c0 = members[host][0]
        for j in jobs:
            k = (ats.norm(j["title"]), j["url"])
            if k in seen or not j.get("title"): continue
            seen.add(k)
            if ats.relevant(j):
                raw.append({"src": "Site carrière (navigateur)", "title": j["title"], "company": c0["name"], "location": j["location"], "contract": "NC",
                            "salary": "NA", "date": j["date"], "url": urllib.parse.urljoin("https://" + host, j["url"]) if j["url"] else "https://" + host,
                            "ref": "br" + (j["url"] or j["title"])[:80], "desc": ""})
    return raw, diags
