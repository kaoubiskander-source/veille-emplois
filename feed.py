# -*- coding: utf-8 -*-
"""Flux dashboard : transforme out/jobs.json en out/feed.jsonl (offres prêtes pour le moteur du dashboard).
Filtre grossier mais strict (famille de poste, exclusions) pour garder un fichier court. Aucune IA."""
import json, os, re, sys, unicodedata, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
def deacc(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))

def norm(s):
    s = deacc(s).lower()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"[^a-z0-9'&+ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", deacc(s or "").lower()).strip("-")

STOP = set("de du des la le les l d et en a au aux pour par sur un une the of and to h f x m w hf fh hfx fhx mfx mf fm cdi poste offre emploi job (h/f) - / senior".split())
GENDER = re.compile(r"\(?\b(h\s*/\s*f(\s*/\s*[xd])?|f\s*/\s*h(\s*/\s*[xd])?|m\s*/\s*f(\s*/\s*[xd])?|f\s*/\s*m(\s*/\s*[xd])?|m\s*/\s*w\s*/\s*d|w\s*/\s*m\s*/\s*d|h\s*-\s*f|f\s*-\s*h)\b\)?", re.I)

def clean_title(t):
    t = (t or "").strip()
    t = GENDER.sub("", t)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\s*[-–|]\s*(cdi|cdd)\s*$", "", t, flags=re.I)
    t = re.sub(r"^\s*(cdi|cdd|emploi|offre d.emploi|job)\s*[-–|:]\s*", "", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–|,;:")
    return t


RULES = [  # (regex sur titre normalisé, fit de base, famille, libellé)
 (r"\bresponsables? (d |des |de l |du )?(l )?offres?\b|\bresponsable offres?\b", 9.5, "offres", "Responsable d'offres"),
 (r"\b(bid|proposal|tender|offer)s? (manager|director|lead|leader|management)\b|\bmanager (des |d )?offres?\b", 9.2, "offres", "Bid / proposal manager"),
 (r"\bhead of (bids?|proposals?|tenders?)\b|\bdirect(eur|rice) (des |d )?offres?\b", 8.8, "offres", "Direction des offres"),
 (r"\b(responsable|chef de projet|chef de projets|manager|directeur|directrice|pilote|coordinat\w+)\b.{0,30}\bappels? d ?offres?\b|\bappels? d ?offres?\b.{0,15}\b(responsable|manager|chef)", 9.0, "offres", "Responsable appels d'offres"),
 (r"\boffer leader\b|\bresponsable (technique )?(des )?propositions?\b|\bproposal\b", 8.5, "offres", "Propositions"),
 (r"\bing(enieure?|\.)? (d |des |de l )?offres?\b|\bcharge(e)? d ?offres?\b|\btender(ing)? (engineer|specialist)\b|\bbid (engineer|specialist)\b", 7.6, "offres", "Ingénieur d'offres"),
 (r"\b(responsable|manager|directeur|lead)\b.{0,20}\bavant[ -]?vente\b|\bpre[ -]?sales? manager\b", 7.6, "offres", "Avant-vente"),
 (r"\bavant[ -]?vente\b|\bpre[ -]?sales?\b|\bsolution (architect|manager)\b|\bclient solution manager\b", 6.8, "offres", "Avant-vente"),
 (r"\b(responsable|manager|chef)\b.{0,20}\b(chiffrage|estimation|devis|etudes de prix|cost)\b|\bestimating manager\b", 6.6, "offres", "Chiffrage / estimation"),
 (r"\bcontracts? manager\b|\bmanager de contrats?\b|\bresponsable (des )?contrats?\b|\bcontract (&|and) commercial\b", 6.6, "offres", "Contract manager"),
 (r"\bkey account\b|\bkam\b|\bglobal account manager\b|\bstrategic account\b|\bgrands? comptes?\b|\bcomptes? cles?\b|\bcomptes? strategiques?\b|\bnational account\b", 8.6, "commercial", "Grands comptes / KAM"),
 (r"\bresponsable commerciale?\b|\bresponsable des ventes\b|\bresponsable (du |de )?developpement commercial\b|\bsales manager\b|\bresponsable commercial et\b|\bcommercial manager\b|\bmanager commercial\b", 8.1, "commercial", "Responsable commercial"),
 (r"\bdirect(eur|rice) (commercial|commerciale|des ventes|du developpement)\b|\bhead of sales\b|\bsales director\b|\bcommercial director\b|\bvp sales\b", 7.6, "commercial", "Direction commerciale"),
 (r"\bbusiness development manager\b|\bresponsable business development\b|\bresponsable (du )?developpement des affaires\b|\bbusiness manager\b", 7.2, "commercial", "Business development manager"),
 (r"\baccount manager\b|\bcharge(e)? de clientele grands\b|\baccount executive\b", 7.0, "commercial", "Account manager"),
 (r"\bing(enieure?)? (d |des )?affaires\b|\bbusiness engineer\b", 7.0, "voisin", "Ingénieur d'affaires"),
 (r"\bresponsable (de )?(zone|secteur|region|regional|export)\b|\bexport manager\b|\barea (sales )?manager\b|\bregional sales\b", 7.0, "commercial", "Responsable de zone / export"),
 (r"\bcharge(e)? d ?affaires\b", 6.6, "voisin", "Chargé d'affaires"),
 (r"\bing(enieure?)? (technico )?commerciale?\b|\btechnico commercial|\bsales engineer\b|\btechnical sales\b|\bingenieur des ventes\b|\bingenieur ventes\b", 6.3, "voisin", "Ingénieur commercial"),
 (r"\bbusiness developer\b|\bdeveloppeur commercial\b|\bdeveloppeuse commerciale\b|\bbusiness development\b", 6.0, "voisin", "Business developer"),
 (r"\b(partnership|partner|partenariats?|channel) manager\b|\bresponsable partenariats?\b", 6.0, "voisin", "Partenariats"),
 (r"\bcustomer (success|service|support) manager\b|\bservices? sales manager\b", 5.8, "voisin", "Services / clients"),
 (r"\bcommercial(e)?\b|\bsales\b|\bventes?\b", 5.5, "voisin", "Commercial"),
]
RULES = [(re.compile(r), f, fam, lab) for r, f, fam, lab in RULES]

REJECT_TITLE = re.compile(r"\b(stagiaire|stage|alternan\w*|apprenti\w*|internship|intern|interim\w*|freelance|v\.?i\.?e\b|junior|debutant\w*|jeune diplome|graduate|"
                          r"assistante?s?|adv\b|administration des ventes|televente|teleconseill\w*|teleprospect\w*|vendeu\w+|caissier|conseill\w+ de vente|"
                          r"sdr\b|bdr\b|sales development rep|inside sales|acheteu\w+|achats?\b|buyer|approvisionn\w+|"
                          r"chef de chantier|conducteur de travaux|technicien\w*|comptable|juriste|recrut\w+|charge\w* de recrutement|rh\b|ressources humaines|"
                          r"marketing manager|chef de produit marketing|community|data analyst|developpeur(?! commercial)|developer(?! business)|devops|"
                          r"ingenieur (d )?(etudes?|conception|r ?& ?d|methodes?|qualite|production|maintenance|essais?|calcul|logiciel|systeme|systemes|cyber)\b|"
                          r"agent commercial independant|mandataire|vrp multicarte|immobilier|assurance|banque|conseiller(e)? (clientele|bancaire|financier)|"
                          r"chauffeur|magasinier|preparateur|operateur|monteur|electricien|plombier|soudeur|mecanicien)\b")
REJECT_CTR = re.compile(r"\b(cdd|interim|stage|alternance|apprentissage|freelance|independant|vie|contrat pro|saisonnier)\b")
ESN = re.compile(r"\b(alten|akkodis|altran|expleo|segula|assystem|capgemini|sopra|inetum|devoteam|wavestone|ausy|aubay|extia|davidson|amaris|modis|"
                 r"accenture|cgi|atos|eviden|bertrandt|akka|ametra|apside|cs group|alteca|scalian|sii\b|groupe sii|onepoint|niji|talan|"
                 r"keyrus|micropole|business et decision|astek|ekium|artelys|altereo|ingeliance|adentis|silkhom|free-work|freework)\b")
SOFTCO = re.compile(r"\b(dassault systemes|sap|oracle|salesforce|microsoft|ibm|servicenow|hubspot|cegid|sage|autodesk|ptc|aveva|esri|everbridge|qwello)\b")
# IT / numérique / ESN : exclus (demande explicite). Testé sur entreprise + intitulé.
IT_EXCL = re.compile(r"\b(sap|informatique|systemes? d.information|numerique|digital|digitale|cyber\w*|cloud|logiciel\w*|saas|erp|ssii|esn|software|data|hpc|intelligence artificielle|ia)\b")
SAAS = re.compile(r"\b(saas|software|logiciel|startup|start-up|scale-up|scaleup|edtech|fintech|proptech|martech|marketplace|application mobile)\b")

BOARD_OK = re.compile(r"^https?://(?:[a-z]{2,3}\.|www\.)?(?:indeed\.com/(?:viewjob|rc/clk)\?|linkedin\.com/jobs/view/|welcometothejungle\.com/fr/companies/|apec\.fr/candidat/|hellowork\.com/fr-fr/emplois/|jooble\.org/desc/|careerjet\.fr/jobad/|adzuna\.fr/(?:details|land/ad)/)", re.I)

def classify(title):
    t = norm(clean_title(title)).replace("'", " ")
    for rx, f, fam, lab in RULES:
        if rx.search(t):
            return f, fam, lab
    return 3.0, "autre", "Hors cible"

def main():
    d = json.load(open(os.path.join(HERE, "out", "jobs.json"), encoding="utf-8"))
    out, seen = [], set()
    for j in d.get("jobs", []):
        title, comp = j.get("title") or "", j.get("company") or ""
        nt = norm(title).replace("'", " ")
        if not title or REJECT_TITLE.search(nt) and not re.search(r"\b(responsable|manager|bid|offres?)\b", nt): continue
        if ESN.search(norm(comp)) or IT_EXCL.search(norm(comp + " " + title)) or SOFTCO.search(norm(comp)): continue
        f, fam, lab = classify(title)
        if fam == "autre" or f < 6.0: continue
        url = j.get("url") or ""
        if not url.startswith("http"): continue
        src = j.get("src") or ""
        k = (norm(comp), nt, norm(j.get("location") or ""))
        if k in seen: continue
        seen.add(k)
        board = src.startswith("Job board")
        out.append({"title": title, "company": comp, "location": j.get("location") or "Île-de-France (lieu non précisé)", "url": url,
                    "source": "officiel" if not board else src.split("(")[-1].rstrip(")").lower(),
                    "published": (j.get("date") or None) or None, "published_text": None, "salary": (j.get("salary") if j.get("salary") not in (None, "NA") else None),
                    "contract": j.get("contract") if j.get("contract") not in (None, "NC") else "?", "ref": j.get("ref"), "seniority": "?", "family": fam,
                    "summary": (j.get("desc") or "")[:200], "fit": round(f), "fit_note": "veille GitHub (%s)" % src,
                    "stab_signals": "", "verified": True if (not board or BOARD_OK.match(url)) else False,
                    "evidence": "lu par %s" % src, "wl": j.get("wl_name"), "list": j.get("list")})
    out.sort(key=lambda o: (-(o["fit"]), o["published"] or ""), reverse=False)
    with open(os.path.join(HERE, "out", "feed.jsonl"), "w", encoding="utf-8") as fh:
        for o in out: fh.write(json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("feed:", len(out), "offres sur", len(d.get("jobs", [])))

if __name__ == "__main__":
    main()
