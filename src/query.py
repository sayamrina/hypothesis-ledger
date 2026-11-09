"""Run a SPARQL query file against results/ledger.ttl, e.g. `python src/query.py queries/disagreements.rq`."""
import sys
from pathlib import Path

from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]

g = Graph().parse(ROOT / "results" / "ledger.ttl")
for row in g.query(Path(sys.argv[1]).read_text()):
    print(" | ".join(str(v) for v in row))
