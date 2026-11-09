"""Harvest gold labels from ORKG (Hi Knowledge comparisons) and abstracts from OpenAlex.

Output: data/studies.jsonl, one line per ORKG contribution with its paper, labels and abstract.
"""
import difflib
import hashlib
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ORKG = "https://orkg.org/api"
COMPARISONS = {
    "enemy_release": "R58002",
    "biotic_resistance": "R57501",
}
session = requests.Session()


def get(url, **kw):
    for attempt in range(8):
        try:
            r = session.get(url, timeout=60, **kw)
            if r.status_code == 200:
                return r.json()
        except requests.ConnectionError:
            pass
        time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"failed: {url} {kw.get('params')}")


def cached(name, fn):
    path = RAW / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    data = fn()
    path.write_text(json.dumps(data))
    return data


def statements(subject=None, obj=None):
    key = f"st_s_{subject}" if subject else f"st_o_{obj}"
    params = {"size": 100}
    if subject:
        params["subject_id"] = subject
    else:
        params["object_id"] = obj
    return cached(key, lambda: get(f"{ORKG}/statements", params=params)["content"])


def comparison_sources(cid):
    data = cached(f"cmp_{cid}", lambda: get(
        f"{ORKG}/comparisons/{cid}", headers={"Accept": "application/vnd.orkg.comparison.v3+json"}))
    return [s["id"] for s in data["sources"]]


def contribution_record(cid):
    fields = {}
    for st in statements(subject=cid):
        label = st["predicate"]["label"].strip()
        fields.setdefault(label, []).append(st["object"].get("label"))
    paper = None
    for st in statements(obj=cid):
        if st["predicate"]["label"] == "contribution" and "Paper" in st["subject"].get("classes", []):
            paper = st["subject"]
    if paper is None:
        papers = [st["subject"] for st in statements(obj=cid) if st["predicate"]["label"] == "contribution"]
        paper = papers[0] if papers else None
    meta = {}
    if paper:
        for st in statements(subject=paper["id"]):
            meta.setdefault(st["predicate"]["label"], st["object"].get("label"))
    return {
        "contribution_id": cid,
        "paper_id": paper["id"] if paper else None,
        "title": paper.get("label") if paper else None,
        "doi": (meta.get("doi") or "").lower().strip() or None,
        "year": meta.get("publication year"),
        "fields": fields,
    }


def abstracts(dois):
    out = {}
    dois = sorted(set(d for d in dois if d))
    for i in range(0, len(dois), 40):
        chunk = dois[i:i + 40]
        def fetch():
            return get("https://api.openalex.org/works", params={
                "filter": "doi:" + "|".join(chunk), "per-page": 50,
                "select": "doi,abstract_inverted_index,open_access,primary_location"})["results"]
        for w in cached(f"oa_{i}", fetch):
            inv = w.get("abstract_inverted_index") or {}
            words = sorted((p, t) for t, ps in inv.items() for p in ps)
            text = " ".join(t for _, t in words)
            out[w["doi"].replace("https://doi.org/", "").lower()] = text or None
        time.sleep(1)
    return out


def resolve_by_title(title):
    """Find the DOI of a paper on Crossref by its title (similarity >= 0.93); also return a Crossref abstract if any."""
    key = "cr_" + hashlib.md5(title.encode()).hexdigest()[:12]
    def fetch():
        return get("https://api.crossref.org/works", params={
            "query.title": title, "rows": 3, "select": "DOI,title,abstract"})["message"]["items"]
    try:
        hits = cached(key, fetch)
    except RuntimeError:
        return None, None
    for w in hits:
        found = (w.get("title") or [""])[0]
        sim = difflib.SequenceMatcher(None, found.lower(), title.lower()).ratio()
        if sim >= 0.93:
            text = re.sub(r"<[^>]+>", " ", w.get("abstract") or "")
            text = re.sub(r"\s+", " ", text).strip()
            text = re.sub(r"^Abstract\s*", "", text)
            return w["DOI"].lower(), text or None
    return None, None


def s2_abstracts(dois):
    """Fallback abstracts from Semantic Scholar for DOIs without an OpenAlex abstract."""
    out = {}
    dois = sorted(set(dois))
    for i in range(0, len(dois), 100):
        chunk = dois[i:i + 100]
        def fetch():
            for attempt in range(6):
                r = session.post("https://api.semanticscholar.org/graph/v1/paper/batch",
                                 params={"fields": "abstract,externalIds"},
                                 json={"ids": [f"DOI:{d}" for d in chunk]}, timeout=60)
                if r.status_code == 200:
                    return r.json()
                time.sleep(5 + 5 * attempt)
            return [None] * len(chunk)
        for d, paper in zip(chunk, cached(f"s2_{i}_{len(chunk)}", fetch)):
            if paper and paper.get("abstract"):
                out[d] = paper["abstract"]
    return out


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    records = []
    for hyp, cid in COMPARISONS.items():
        for contrib in comparison_sources(cid):
            rec = contribution_record(contrib)
            rec["hypothesis"] = hyp
            records.append(rec)
        print(hyp, len(records))
    title_abs = {}
    for r in records:
        if not r["doi"]:
            r["doi"], title_abs[r["contribution_id"]] = resolve_by_title(r["title"])
            r["doi_source"] = "crossref_title" if r["doi"] else None
        else:
            r["doi_source"] = "orkg"
    abs_map = abstracts([r["doi"] for r in records if r["doi_source"] == "orkg"])
    for r in records:
        r["abstract"] = abs_map.get(r["doi"]) if r["doi_source"] == "orkg" else title_abs.get(r["contribution_id"])
        r["abstract_source"] = ("openalex" if r["doi_source"] == "orkg" else "crossref") if r["abstract"] else None
    s2 = s2_abstracts([r["doi"] for r in records if r["doi"] and not r["abstract"]])
    for r in records:
        if not r["abstract"] and r["doi"] in s2:
            r["abstract"], r["abstract_source"] = s2[r["doi"]], "semantic_scholar"
    out = ROOT / "data" / "studies.jsonl"
    with out.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with_abs = sum(1 for r in records if r["abstract"])
    print(f"{len(records)} contributions, {with_abs} with abstract -> {out}")


if __name__ == "__main__":
    main()
