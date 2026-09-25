"""
Tool layer: every function here hits a real, free, no-API-key public
scientific data source. Each function fails soft (returns [] / {} plus a
"degraded" flag) so one flaky API never crashes the whole pipeline -
this is the "API -> validation -> fallback" pattern from the design doc.

Sources used:
  - Open Targets Platform GraphQL API   -> disease -> target associations
  - ChEMBL REST API                      -> target -> known drugs
  - NCBI PubMed E-utilities              -> literature search
  - ClinicalTrials.gov API v2            -> trial search
  - openFDA                              -> adverse event / label search
"""
import requests
import html
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

TIMEOUT = 15


def _safe_get(url, params=None, headers=None):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _safe_post(url, json_body=None):
    try:
        r = requests.post(url, json=json_body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Open Targets: disease -> associated targets (genes/proteins) + pathways
# ---------------------------------------------------------------------------
OPEN_TARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"
_DISEASE_IDS = {}
_DISEASE_OVERVIEW_CACHE = {}

def search_disease_targets(disease_name: str, limit: int = 6):
    """Return top disease-associated targets from Open Targets."""
    search_query = """
    query search($q: String!) {
      search(queryString: $q, entityNames: ["disease"]) {
        hits { id name entity }
      }
    }
    """
    data, err = _safe_post(OPEN_TARGETS_URL, {"query": search_query, "variables": {"q": disease_name}})
    if err or not data:
        return [], f"open_targets_search_error: {err}"

    hits = data.get("data", {}).get("search", {}).get("hits", [])
    disease_hits = [h for h in hits if h.get("entity") == "disease"]
    if not disease_hits:
        return [], "no_disease_match"
    efo_id = disease_hits[0]["id"]
    _DISEASE_IDS[disease_name.strip().lower()] = efo_id

    assoc_query = """
    query assoc($efoId: String!) {
      disease(efoId: $efoId) {
        name
        associatedTargets(page: {index: 0, size: %d}) {
          rows {
            score
            target { id approvedSymbol approvedName }
          }
        }
      }
    }
    """ % limit
    data2, err2 = _safe_post(OPEN_TARGETS_URL, {"query": assoc_query, "variables": {"efoId": efo_id}})
    if err2 or not data2:
        return [], f"open_targets_assoc_error: {err2}"

    rows = data2.get("data", {}).get("disease", {}).get("associatedTargets", {}).get("rows", [])
    targets = [
        {
            "symbol": row["target"]["approvedSymbol"],
            "name": row["target"]["approvedName"],
            "ensembl_id": row["target"]["id"],
            "association_score": round(row.get("score", 0), 3),
        }
        for row in rows
    ]
    return targets, None


def search_disease_description(disease_name: str):
    """Retrieve the ontology description for one disease from Open Targets."""
    efo_id = _DISEASE_IDS.get(disease_name.strip().lower())
    if not efo_id:
        search_query = """
        query search($q: String!) {
          search(queryString: $q, entityNames: ["disease"]) { hits { id name entity } }
        }
        """
        data, err = _safe_post(OPEN_TARGETS_URL, {"query": search_query, "variables": {"q": disease_name}})
        if err or not data:
            return None, f"open_targets_disease_description_search_error: {err}"
        hits = data.get("data", {}).get("search", {}).get("hits", [])
        disease_hit = next((h for h in hits if h.get("entity") == "disease"), None)
        if not disease_hit:
            return None, "no_disease_match"
        efo_id = disease_hit["id"]
        _DISEASE_IDS[disease_name.strip().lower()] = efo_id

    description_query = """
    query diseaseDescription($efoId: String!) {
      disease(efoId: $efoId) { id name description }
    }
    """
    data, err = _safe_post(OPEN_TARGETS_URL, {"query": description_query, "variables": {"efoId": efo_id}})
    if err or not data:
        return None, f"open_targets_disease_description_error: {err}"
    disease = data.get("data", {}).get("disease")
    if not disease:
        return None, "no_disease_description_record"
    description = disease.get("description")
    if not description:
        return {"id": disease.get("id"), "name": disease.get("name"), "description": None,
                "source": "Open Targets Platform", "url": f"https://platform.opentargets.org/disease/{efo_id}"}, None
    return {"id": disease.get("id"), "name": disease.get("name"), "description": description,
            "source": "Open Targets Platform", "url": f"https://platform.opentargets.org/disease/{efo_id}"}, None


def search_disease_health_topic(disease_name: str):
    """Find an exact or close MedlinePlus health topic and return its summary."""
    cache_key = disease_name.strip().lower()
    if cache_key in _DISEASE_OVERVIEW_CACHE:
        return _DISEASE_OVERVIEW_CACHE[cache_key], None
    try:
        response = requests.get(
            "https://wsearch.nlm.nih.gov/ws/query",
            params={"db": "healthTopics", "term": disease_name, "retmax": 10, "rettype": "brief"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:
        return None, f"medlineplus_search_error: {exc}"

    class PlainText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() in {"p", "br", "li", "h1", "h2", "h3"}:
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag.lower() in {"p", "li", "h1", "h2", "h3"}:
                self.parts.append("\n")

        def handle_data(self, data):
            self.parts.append(data)

    def plain_text(value):
        parser = PlainText()
        parser.feed(html.unescape(value or ""))
        return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())

    def normalize(value):
        value = re.sub(r"'s\b", "", plain_text(value).lower())
        return re.sub(r"[^a-z0-9]", "", value)

    query = normalize(disease_name)
    documents = [node for node in root.iter() if node.tag.split("}")[-1] == "document"]
    ranked = []
    for document in documents:
        title_node = next((n for n in document if n.attrib.get("name", "").lower() == "title"), None)
        title = plain_text("".join(title_node.itertext())) if title_node is not None else ""
        aliases = [
            plain_text("".join(node.itertext())) for node in document
            if node.attrib.get("name", "").lower() == "alttitle"
        ]
        title_key = normalize(title)
        alias_keys = [normalize(value) for value in aliases]
        if query == title_key or query in alias_keys:
            score = 3
        elif query and (query in title_key or any(query in alias for alias in alias_keys)):
            score = 2
        else:
            continue
        summary_node = next((n for n in document if n.attrib.get("name", "").lower() == "fullsummary"), None)
        summary = plain_text("".join(summary_node.itertext())) if summary_node is not None else ""
        if summary:
            lines = summary.splitlines()
            if lines and lines[0].rstrip().endswith("?"):
                next_section = next(
                    (i for i, line in enumerate(lines[1:], start=1)
                     if line.rstrip().endswith("?") and len(line.split()) <= 12),
                    len(lines),
                )
                summary = "\n".join(lines[:next_section]).strip()
            elif len(summary.split()) > 180:
                sentences = re.split(r"(?<=[.!?])\s+", summary)
                kept = []
                for sentence in sentences:
                    if len(" ".join(kept + [sentence]).split()) > 160:
                        break
                    kept.append(sentence)
                summary = " ".join(kept).strip()
            ranked.append((score, {
                "title": title,
                "summary": summary,
                "url": document.attrib.get("url"),
                "source": "MedlinePlus, U.S. National Library of Medicine",
                "attribution": next((plain_text("".join(n.itertext())) for n in document
                                     if n.attrib.get("name", "").lower() == "organizationname"), None),
            }))
    if not ranked:
        return None, "no_exact_medlineplus_topic_match"
    ranked.sort(key=lambda item: item[0], reverse=True)
    _DISEASE_OVERVIEW_CACHE[cache_key] = ranked[0][1]
    return ranked[0][1], None


# ---------------------------------------------------------------------------
# ChEMBL: target -> known/investigational drugs acting on it
# ---------------------------------------------------------------------------
def search_drugs_for_target(target_symbol: str, limit: int = 5):
    data, err = _safe_get(
        "https://www.ebi.ac.uk/chembl/api/data/target/search.json",
        params={"q": target_symbol, "limit": 1},
    )
    if err or not data or not data.get("targets"):
        return [], f"chembl_target_lookup_error: {err}"

    chembl_target_id = data["targets"][0]["target_chembl_id"]

    data2, err2 = _safe_get(
        "https://www.ebi.ac.uk/chembl/api/data/mechanism.json",
        params={"target_chembl_id": chembl_target_id, "limit": limit},
    )
    if err2 or not data2:
        return [], f"chembl_mechanism_error: {err2}"

    mechanisms = data2.get("mechanisms", [])
    drugs = []
    for m in mechanisms:
        drugs.append({
            "molecule_chembl_id": m.get("molecule_chembl_id"),
            "action_type": m.get("action_type"),
            "mechanism_of_action": m.get("mechanism_of_action"),
        })
    return drugs, None


def get_drug_name(molecule_chembl_id: str):
    data, err = _safe_get(f"https://www.ebi.ac.uk/chembl/api/data/molecule/{molecule_chembl_id}.json")
    if err or not data:
        return molecule_chembl_id
    return (data.get("pref_name") or molecule_chembl_id).title()


# ---------------------------------------------------------------------------
# PubMed E-utilities: literature search
# ---------------------------------------------------------------------------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def search_pubmed(query: str, max_results: int = 5):
    data, err = _safe_get(
        f"{EUTILS}/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmode": "json", "retmax": max_results, "sort": "relevance"},
    )
    if err or not data:
        return [], f"pubmed_esearch_error: {err}"

    ids = data.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return [], None

    data2, err2 = _safe_get(
        f"{EUTILS}/esummary.fcgi",
        params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
    )
    if err2 or not data2:
        return [], f"pubmed_esummary_error: {err2}"

    result = data2.get("result", {})
    articles = []
    for pmid in ids:
        item = result.get(pmid)
        if not item:
            continue
        articles.append({
            "pmid": pmid,
            "title": item.get("title"),
            "journal": item.get("fulljournalname"),
            "pubdate": item.get("pubdate"),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return articles, None


# ---------------------------------------------------------------------------
# ClinicalTrials.gov API v2
# ---------------------------------------------------------------------------
def search_clinical_trials(query: str, max_results: int = 5):
    data, err = _safe_get(
        "https://clinicaltrials.gov/api/v2/studies",
        params={"query.term": query, "pageSize": max_results},
    )
    if err or not data:
        return [], f"clinicaltrials_error: {err}"

    studies = data.get("studies", [])
    trials = []
    for s in studies:
        proto = s.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        trials.append({
            "nct_id": ident.get("nctId"),
            "title": ident.get("briefTitle"),
            "status": status_mod.get("overallStatus"),
            "url": f"https://clinicaltrials.gov/study/{ident.get('nctId')}" if ident.get("nctId") else None,
        })
    return trials, None


# ---------------------------------------------------------------------------
# openFDA: known adverse events / label warnings for a drug
# ---------------------------------------------------------------------------
def search_drug_safety(drug_name: str, limit: int = 3):
    data, err = _safe_get(
        "https://api.fda.gov/drug/label.json",
        params={"search": f'openfda.brand_name:"{drug_name}"', "limit": limit},
    )
    if err or not data or not data.get("results"):
        # try generic name field as fallback
        data, err = _safe_get(
            "https://api.fda.gov/drug/label.json",
            params={"search": f'openfda.generic_name:"{drug_name}"', "limit": limit},
        )
    if err or not data or not data.get("results"):
        return [], f"openfda_error_or_no_label: {err}"

    notes = []
    for r in data["results"]:
        warnings = r.get("warnings") or r.get("boxed_warning") or r.get("adverse_reactions")
        if warnings:
            snippet = warnings[0][:400]
            notes.append({"source": "FDA label", "note": snippet})
    return notes, None


# Drug Explorer: ChEMBL profile, indications and known mechanisms
def search_drug_profile(query: str):
    """Retrieve a drug profile from ChEMBL; never invent missing facts."""
    data, err = _safe_get(
        "https://www.ebi.ac.uk/chembl/api/data/molecule/search.json",
        params={"q": query, "limit": 5},
    )
    if err or not data or not data.get("molecules"):
        return None, f"chembl_molecule_search_error: {err or 'no matching molecule'}"
    molecules = data["molecules"]
    molecule = next((m for m in molecules if (m.get("pref_name") or "").lower() == query.lower()), molecules[0])
    ident = molecule.get("molecule_chembl_id")
    profile = {
        "chembl_id": ident, "name": molecule.get("pref_name") or query,
        "molecule_type": molecule.get("molecule_type"), "max_phase": molecule.get("max_phase"),
        "indications": [], "mechanisms": [], "targets": [],
    }
    indications, indication_error = _safe_get(
        "https://www.ebi.ac.uk/chembl/api/data/drug_indication.json",
        params={"molecule_chembl_id": ident, "limit": 50},
    )
    if indications:
        profile["indications"] = [
            {"disease": x.get("mesh_heading") or x.get("efo_term"), "max_phase": x.get("max_phase_for_ind"),
             "efo_id": x.get("efo_id")}
            for x in indications.get("drug_indications", []) if x.get("mesh_heading") or x.get("efo_term")
        ]
    mechanisms, mechanism_error = _safe_get(
        "https://www.ebi.ac.uk/chembl/api/data/mechanism.json",
        params={"molecule_chembl_id": ident, "limit": 30},
    )
    if mechanisms:
        for item in mechanisms.get("mechanisms", []):
            target_id = item.get("target_chembl_id")
            target_name = target_id
            if target_id:
                target, _ = _safe_get(f"https://www.ebi.ac.uk/chembl/api/data/target/{target_id}.json")
                if target:
                    target_name = target.get("pref_name") or target_id
            profile["mechanisms"].append({
                "action": item.get("action_type"), "mechanism": item.get("mechanism_of_action"),
                "target_id": target_id, "target": target_name,
            })
            if target_name and target_name not in profile["targets"]:
                profile["targets"].append(target_name)
    profile["gaps"] = []
    if not profile["indications"]:
        profile["gaps"].append("No recorded indications were retrieved from ChEMBL." + (f" API detail: {indication_error}" if indication_error else ""))
    if not profile["mechanisms"]:
        profile["gaps"].append("No mechanism-of-action records were retrieved from ChEMBL." + (f" API detail: {mechanism_error}" if mechanism_error else ""))
    profile["source"] = "ChEMBL"
    profile["url"] = f"https://www.ebi.ac.uk/chembl/explore/compound/{ident}"
    return profile, None


def search_literature_landscape(query: str, max_results: int = 100):
    articles, err = search_pubmed(query, max_results=max_results)
    if err:
        return {"query": query, "articles": [], "total": 0, "error": err}
    categories = {"Mechanistic studies": [], "Cell studies": [], "Animal studies": [], "Clinical studies": [], "Reviews": []}
    for article in articles:
        title = (article.get("title") or "").lower()
        if any(term in title for term in ("review", "meta-analysis", "systematic review")):
            category = "Reviews"
        elif any(term in title for term in ("clinical trial", "randomized", "patients", "phase i", "phase ii", "phase iii", "cohort")):
            category = "Clinical studies"
        elif any(term in title for term in ("mouse", "mice", "murine", "rat ", "animal model", "in vivo")):
            category = "Animal studies"
        elif any(term in title for term in ("cell", "in vitro", "cellular", "culture")):
            category = "Cell studies"
        else:
            category = "Mechanistic studies"
        categories[category].append(article)
    import re
    years = {}
    for article in articles:
        match = re.search(r"(?:19|20)\d{2}", article.get("pubdate") or "")
        if match:
            years[match.group(0)] = years.get(match.group(0), 0) + 1
    return {
        "query": query, "articles": articles, "total": len(articles),
        "categories": {name: len(items) for name, items in categories.items()},
        "timeline": [{"year": year, "count": years[year]} for year in sorted(years)],
        "summary": f"Retrieved {len(articles)} PubMed records for this query. Categories are estimated from article titles and should be treated as triage labels, not a systematic review.",
        "source": "PubMed E-utilities",
    }
