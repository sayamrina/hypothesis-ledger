"""Compare LLM verdicts with the expert labels from Hi Knowledge (ORKG) and summarise the evidence graph.

Output: results/metrics.json, results/causal_graph.png, printed tables.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
import networkx as nx
from scipy.stats import binomtest, fisher_exact
from sklearn.metrics import accuracy_score, cohen_kappa_score, confusion_matrix, f1_score

sys.path.insert(0, str(Path(__file__).parent))
from extract import load_items  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
LABELS = ["supported", "questioned", "undecided"]


def load(condition):
    path = RES / f"extractions_{condition}.jsonl"
    return {json.loads(l)["item_id"]: json.loads(l) for l in path.open()} if path.exists() else {}


def verdict_metrics(items, preds):
    ids = [i for i in preds if items[i]["gold"] != "mixed"]
    y = [items[i]["gold"] for i in ids]
    p = [preds[i]["answer"]["verdict"] for i in ids]
    return ids, {
        "n": len(ids),
        "accuracy": round(accuracy_score(y, p), 3),
        "macro_f1": round(f1_score(y, p, labels=LABELS, average="macro", zero_division=0), 3),
        "majority_baseline": round(Counter(y).most_common(1)[0][1] / len(y), 3),
        "confusion (rows=expert, cols=LLM; supported, questioned, undecided)":
            confusion_matrix(y, p, labels=LABELS).tolist(),
    }


def mcnemar(items, a, b, ids):
    """Exact McNemar test on the items both conditions answered."""
    ra = [a[i]["answer"]["verdict"] == items[i]["gold"] for i in ids if i in b]
    rb = [b[i]["answer"]["verdict"] == items[i]["gold"] for i in ids if i in b]
    only_a = sum(x and not y for x, y in zip(ra, rb))
    only_b = sum(y and not x for x, y in zip(ra, rb))
    p = binomtest(only_a, only_a + only_b, 0.5).pvalue if only_a + only_b else 1.0
    return {"only_direct_correct": only_a, "only_claims_correct": only_b, "p_exact": round(p, 3)}


def support_share(rows):
    """Share of studies supporting the hypothesis among those with a supported/questioned verdict."""
    decided = [v for v in rows if v in ("supported", "questioned")]
    return round(sum(v == "supported" for v in decided) / len(decided), 2) if decided else None


def main():
    items = {i["item_id"]: i for i in load_items()}
    direct, claims = load("direct"), load("claims")
    m = {"items": len(items), "gold": dict(Counter(i["gold"] for i in items.values()))}
    ids_c, m["claims"] = verdict_metrics(items, claims)
    if direct:
        ids_d, m["direct"] = verdict_metrics(items, direct)
        m["direct_vs_claims"] = mcnemar(items, direct, claims, ids_d)

    # provenance: are the evidence quotes verbatim spans of the abstract?
    all_claims = [c for r in claims.values() for c in r["answer"]["claims"]]
    missing = sum(len(r.get("quotes_missing", [])) for r in claims.values())
    m["provenance"] = {
        "claims": len(all_claims),
        "claims_per_study": round(len(all_claims) / len(claims), 2),
        "studies_needing_correction_round": sum(r["rounds"] == 2 for r in claims.values()),
        "quotes_verbatim_after_check": round(1 - missing / max(len(all_claims), 1), 3),
    }

    # study design: LLM reading vs Hi Knowledge "Research Method"
    gold_design = {"Experimental": "experimental", "Experiment": "experimental", "Observational or correlational": "observational"}
    pairs = [(gold_design[items[i]["gold_method"]], claims[i]["answer"]["design"]) for i in claims
             if items[i]["gold_method"] in gold_design]
    m["design_agreement"] = {"n": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3)}

    # transportability: does the share of supporting studies differ by habitat or design, and does the
    # LLM synthesis reproduce the expert synthesis?
    by = defaultdict(lambda: {"expert": [], "llm": []})
    for i, r in claims.items():
        it = items[i]
        if it["gold"] == "mixed":
            continue
        for key in (f"{it['hypothesis']} | all", f"{it['hypothesis']} | habitat={it['gold_habitat']}",
                    f"{it['hypothesis']} | method={it['gold_method']}"):
            by[key]["expert"].append(it["gold"])
            by[key]["llm"].append(r["answer"]["verdict"])
    m["support_share"] = {k: {"n": len(v["expert"]), "expert": support_share(v["expert"]),
                              "llm": support_share(v["llm"])} for k, v in sorted(by.items()) if len(v["expert"]) >= 5}

    # design as a causal moderator: experimental vs observational studies (Fisher exact test, decided studies only)
    m["design_effect"] = {}
    for hyp in ("enemy_release", "biotic_resistance"):
        row = {}
        for source in ("expert", "llm"):
            table = []
            for method in ("Experimental", "Observational or correlational"):
                v = by[f"{hyp} | method={method}"][source]
                table.append([v.count("supported"), v.count("questioned")])
            odds, p = fisher_exact(table)
            row[source] = {"experimental [sup, que]": table[0], "observational [sup, que]": table[1],
                           "odds_ratio": round(odds, 2), "p_fisher": round(p, 3)}
        m["design_effect"][hyp] = row

    # LLM-as-a-judge vs real correctness
    jpath = RES / "judge.jsonl"
    if jpath.exists():
        judged = {json.loads(l)["item_id"]: json.loads(l) for l in jpath.open()}
        ids = [i for i in judged if items[i]["gold"] != "mixed"]
        truth = ["yes" if claims[i]["answer"]["verdict"] == items[i]["gold"] else "no" for i in ids]
        judge = [judged[i]["verdict_correct"] for i in ids]
        m["llm_judge"] = {
            "n": len(ids), "judge_says_correct": round(judge.count("yes") / len(ids), 3),
            "actually_correct": round(truth.count("yes") / len(ids), 3),
            "agreement_with_expert_check": round(sum(a == b for a, b in zip(truth, judge)) / len(ids), 3),
            "cohen_kappa": round(cohen_kappa_score(truth, judge), 3),
        }

    # causal evidence graph: category -> category edges, weighted by number of studies, sign by majority
    G = nx.DiGraph()
    edges = defaultdict(Counter)
    for r in claims.values():
        seen = set()
        for c in r["answer"]["claims"]:
            if "other" in (c["cause_node"], c["effect_node"]) or c["cause_node"] == c["effect_node"]:
                continue
            key = (c["cause_node"], c["effect_node"], c["direction"])
            if key not in seen:
                edges[(c["cause_node"], c["effect_node"])][c["direction"]] += 1
                seen.add(key)
    for (u, v), dirs in edges.items():
        n = sum(dirs.values())
        if n >= 3:
            G.add_edge(u, v, n=n, dirs=dict(dirs))
    m["sign_check"] = {
        "enemy_pressure -> invader_performance (hypothesis predicts decreases)":
            edges.get(("enemy_pressure", "invader_performance"), {}),
        "native_diversity -> invader_establishment (hypothesis predicts decreases)":
            edges.get(("native_diversity", "invader_establishment"), {}),
    }
    m["causal_graph_edges"] = {f"{u} -> {v}": d["dirs"] for u, v, d in sorted(G.edges(data=True), key=lambda e: -e[2]["n"])}
    plt.figure(figsize=(9, 6))
    pos = nx.spring_layout(G, seed=3, k=1.6)
    nx.draw_networkx(G, pos, node_color="#e8f1f8", node_size=2600, font_size=8, edge_color="#6b7c8f",
                     width=[0.6 + 0.25 * d["n"] for _, _, d in G.edges(data=True)], arrowsize=16,
                     labels={n: n.replace("_", "\n") for n in G.nodes})
    plt.title("Causal claims extracted from 144 abstracts (edge width = number of studies)", fontsize=9)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(RES / "causal_graph.png", dpi=150)

    (RES / "metrics.json").write_text(json.dumps(m, indent=2))
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
