"""Turn the LLM extractions into an RDF knowledge graph with provenance, validate it with SHACL.

Studies and hypotheses link to their ORKG resources; every claim carries the verbatim quote it was
derived from (prov:value), the source DOI (prov:wasDerivedFrom) and the extraction run (prov:wasGeneratedBy).
Output: results/ledger.ttl
"""
import json
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, PROV

sys.path.insert(0, str(Path(__file__).parent))
from extract import MODEL, load_items  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HL = Namespace("https://sayamrina.github.io/hypothesis-ledger/ns#")
ORKG = Namespace("https://orkg.org/resource/")
HYP_RESOURCE = {"enemy_release": ORKG.R58002, "biotic_resistance": ORKG.R57501}


def new_graph(condition):
    g = Graph()
    g.bind("hl", HL)
    g.bind("orkg", ORKG)
    g.bind("prov", PROV)
    g.bind("dcterms", DCTERMS)
    run = HL[f"run_{condition}"]
    g.add((run, RDF.type, PROV.Activity))
    g.add((run, RDFS.label, Literal(f"LLM extraction ({condition}) with {MODEL}")))
    for hyp, res in HYP_RESOURCE.items():
        g.add((res, RDF.type, HL.Hypothesis))
        g.add((res, RDFS.label, Literal(hyp.replace("_", " ") + " hypothesis")))
    return g, run


def add_record(g, item, rec, run):
    """Add one study, its assessment and its claims. `item` needs paper_id, hypothesis, title, doi,
    gold and gold_habitat; `rec` is one line of an extractions file."""
    ans = rec["answer"]
    paper = ORKG[item["paper_id"]]
    source = URIRef(f"https://doi.org/{item['doi']}") if item["doi"] else paper
    g.add((paper, RDF.type, HL.Study))
    g.add((paper, DCTERMS.title, Literal(item["title"])))
    if item["doi"]:
        g.add((paper, DCTERMS.identifier, Literal(item["doi"])))
    if item["gold_habitat"] not in ("mixed", "unclear"):
        for habitat in item["gold_habitat"].split(" and "):
            g.add((paper, HL.habitat, HL[habitat]))

    assessment = HL[f"assessment_{item['paper_id']}_{item['hypothesis']}"]
    g.add((assessment, RDF.type, HL.Assessment))
    g.add((assessment, HL.study, paper))
    g.add((assessment, HL.hypothesis, HYP_RESOURCE[item["hypothesis"]]))
    g.add((assessment, HL.verdict, HL[ans["verdict"]]))
    g.add((assessment, HL.uncertainty, HL[ans["uncertainty"]]))
    g.add((assessment, HL.design, HL[ans.get("design", "unclear")]))
    g.add((assessment, RDFS.comment, Literal(ans["rationale"])))
    g.add((assessment, PROV.wasGeneratedBy, run))
    if item["gold"] in ("supported", "questioned", "undecided"):
        g.add((assessment, HL.expertVerdict, HL[item["gold"]]))

    for k, c in enumerate(ans.get("claims", [])):
        claim = HL[f"claim_{item['paper_id']}_{item['hypothesis']}_{k}"]
        g.add((claim, RDF.type, HL.CausalClaim))
        g.add((assessment, HL.basedOn, claim))
        g.add((claim, HL.cause, Literal(c["cause"])))
        g.add((claim, HL.effect, Literal(c["effect"])))
        g.add((claim, HL.causeNode, HL[c["cause_node"]]))
        g.add((claim, HL.effectNode, HL[c["effect_node"]]))
        g.add((claim, HL.direction, HL[c["direction"]]))
        g.add((claim, HL.organism, Literal(c["organism"])))
        g.add((claim, HL.habitat, HL[c["habitat"]]))
        g.add((claim, PROV.value, Literal(c["evidence_quote"])))
        g.add((claim, HL.quoteVerified, Literal(c["evidence_quote"] not in rec.get("quotes_missing", []),
                                                datatype=XSD.boolean)))
        g.add((claim, PROV.wasDerivedFrom, source))
        g.add((claim, PROV.wasGeneratedBy, run))


def build(condition="claims"):
    items = {i["item_id"]: i for i in load_items()}
    g, run = new_graph(condition)
    for line in (ROOT / "results" / f"extractions_{condition}.jsonl").open():
        rec = json.loads(line)
        add_record(g, items[rec["item_id"]], rec, run)
    return g


def main():
    g = build()
    out = ROOT / "results" / "ledger.ttl"
    g.serialize(out, format="turtle")
    shapes = Graph().parse(ROOT / "shapes" / "ledger_shapes.ttl")
    conforms, _, report = validate(g, shacl_graph=shapes)
    print(f"{len(g)} triples -> {out}; SHACL conforms: {conforms}")
    if not conforms:
        print(report[:3000])


if __name__ == "__main__":
    main()
