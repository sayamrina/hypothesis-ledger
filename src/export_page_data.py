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
