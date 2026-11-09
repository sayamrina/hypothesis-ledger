"""Write docs/studies.json for the project page: one record per study with both verdicts and one quote."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import ROOT, load_items  # noqa: E402

items = {i["item_id"]: i for i in load_items()}
claims = {json.loads(l)["item_id"]: json.loads(l) for l in (ROOT / "results" / "extractions_claims.jsonl").open()}
rows = []
for item_id, rec in claims.items():
    it, ans = items[item_id], rec["answer"]
    quote = next((c["evidence_quote"] for c in ans["claims"] if c["evidence_quote"] not in rec.get("quotes_missing", [])), None)
    rows.append({
        "h": it["hypothesis"], "t": it["title"], "doi": it["doi"], "orkg": it["paper_id"],
        "expert": it["gold"], "llm": ans["verdict"], "design": ans["design"],
        "q": quote, "why": ans["rationale"], "n": len(ans["claims"]),
    })
(ROOT / "docs" / "studies.json").write_text(json.dumps(rows, ensure_ascii=False))
print(len(rows))

# summary numbers and graph edges for the charts on the page
m = json.loads((ROOT / "results" / "metrics.json").read_text())
design = {h: {src: {"experimental": v["experimental [sup, que]"], "observational": v["observational [sup, que]"],
                    "p": v["p_fisher"]} for src, v in row.items()} for h, row in m["design_effect"].items()}
edges = [{"from": k.split(" -> ")[0], "to": k.split(" -> ")[1], "n": sum(v.values()), "dirs": v}
         for k, v in m["causal_graph_edges"].items()]
page = {
    "accuracy": {"claims": m["claims"]["accuracy"], "direct": m["direct"]["accuracy"],
                 "majority": m["claims"]["majority_baseline"], "n": m["claims"]["n"],
                 "macro_f1": {"claims": m["claims"]["macro_f1"], "direct": m["direct"]["macro_f1"]}},
    "provenance": m["provenance"], "design_agreement": m["design_agreement"],
    "judge": m["llm_judge"], "design_effect": design, "edges": edges,
}
(ROOT / "docs" / "metrics.json").write_text(json.dumps(page, indent=1))
