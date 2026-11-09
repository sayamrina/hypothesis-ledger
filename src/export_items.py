"""Write data/items.csv: the evaluation items without abstracts (abstracts stay local; harvest.py refetches them)."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import ROOT, load_items  # noqa: E402

FIELDS = ["item_id", "paper_id", "hypothesis", "title", "doi", "gold", "gold_habitat", "gold_method", "contribution_ids"]

with (ROOT / "data" / "items.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for item in load_items():
        w.writerow({**item, "contribution_ids": " ".join(item["contribution_ids"])})
