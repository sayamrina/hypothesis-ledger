"""Hypothesis Ledger Explorer: extract causal claims from an abstract, browse the 144 studies, query the graph."""
import csv
import html
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from pyshacl import validate
from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from build_graph import add_record, new_graph  # noqa: E402
from extract import HYPOTHESES, MODEL, norm  # noqa: E402

MAX_LIVE_RUNS = 5
MAX_CHARS = 3500
VERDICT_COLOR = {"supported": "#5f9b40", "questioned": "#7d5aab", "undecided": "#8f897e", "mixed": "#8f897e"}
QUERIES = {
    "Where the model disagrees with the experts": ROOT / "queries" / "disagreements.rq",
    "Verdicts by study design": ROOT / "queries" / "support_by_design.rq",
    "Claims whose quote could not be verified": ROOT / "queries" / "claims_without_verified_quote.rq",
}

st.set_page_config(page_title="Hypothesis Ledger Explorer", page_icon="📒", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 3.8rem; max-width: 1180px; }
.pf-banner { background: #163a34; color: #e6efe9; padding: 9px 14px; border-radius: 6px; font-size: 0.9rem; margin-bottom: 1rem; }
.pf-banner a { color: #e3ef7a; }
mark.ev { background: #e3ef7a; color: #2c3410; padding: 1px 3px; }
.abstract { font-family: Georgia, serif; font-size: 1.05rem; line-height: 1.65; }
.verdict { display: inline-block; padding: 3px 10px; border-radius: 4px; color: #fff; font-weight: 600; font-size: 0.9rem; margin-right: 6px; }
</style>
<div class="pf-banner">This app was developed by Amrina as part of a portfolio.
<a href="https://sayamrina.github.io/" target="_blank" rel="noopener">View the portfolio</a></div>
""", unsafe_allow_html=True)


@st.cache_data
def load_items():
    with (ROOT / "data" / "items.csv").open() as f:
        return {r["item_id"]: r for r in csv.DictReader(f)}


@st.cache_data
def load_extractions():
    return {json.loads(l)["item_id"]: json.loads(l) for l in (ROOT / "results" / "extractions_claims.jsonl").open()}


@st.cache_resource
def load_graph():
    return Graph().parse(ROOT / "results" / "ledger.ttl")


@st.cache_resource
def load_shapes():
    return Graph().parse(ROOT / "shapes" / "ledger_shapes.ttl")


def badge(label, verdict):
    return f'<span class="verdict" style="background:{VERDICT_COLOR.get(verdict, "#8f897e")}">{label}: {verdict}</span>'


def highlight(abstract, quotes):
    """Mark every verified quote in the abstract (case-insensitive, whitespace-tolerant)."""
    text = html.escape(abstract)
    for q in sorted(set(quotes), key=len, reverse=True):
        words = [re.escape(html.escape(w)) for w in q.split()]
        if words:
            text = re.sub(r"\s+".join(words), lambda m: f'<mark class="ev">{m.group(0)}</mark>', text, count=1, flags=re.I)
    return f'<div class="abstract">{text}</div>'


def record_graph(item, rec):
    g, run = new_graph("app" if item["paper_id"].startswith("user") else "claims")
    add_record(g, item, rec, run)
    conforms, _, report = validate(g, shacl_graph=load_shapes())
    return g, conforms, report


def show_result(item, rec, abstract=None):
    ans = rec["answer"]
    head = badge("Model", ans["verdict"])
    if item.get("gold") and item["gold"] != "user":
        head += badge("Experts", item["gold"])
    st.markdown(head + f' &nbsp; design read as <b>{ans["design"].replace("_", " ")}</b>, '
                       f'uncertainty <b>{ans["uncertainty"]}</b>', unsafe_allow_html=True)
    st.write(ans["rationale"])
    if abstract:
        verified = [c["evidence_quote"] for c in ans["claims"] if c["evidence_quote"] not in rec.get("quotes_missing", [])]
        st.markdown(highlight(abstract, verified), unsafe_allow_html=True)
    rows = [{"cause": c["cause"], "effect": c["effect"], "direction": c["direction"],
             "cause node": c["cause_node"], "effect node": c["effect_node"], "organism": c["organism"],
             "quote verified": c["evidence_quote"] not in rec.get("quotes_missing", []),
             "evidence quote": c["evidence_quote"]} for c in ans["claims"]]
    st.markdown(f"**{len(rows)} causal claims**")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    g, conforms, report = record_graph(item, rec)
    with st.expander(f"RDF for this record ({len(g)} triples), SHACL {'passed' if conforms else 'failed'}"):
        st.code(g.serialize(format="turtle"), language="turtle")
        if not conforms:
            st.text(report)


st.title("Hypothesis Ledger Explorer")
st.write("A language model reads an ecology abstract, extracts each causal claim with the sentence it comes from, "
         "and judges whether the study supports an invasion biology hypothesis. Every claim is stored as RDF with "
         "provenance and checked with SHACL. [Project page](https://sayamrina.github.io/hypothesis-ledger/) · "
         "[Code](https://github.com/sayamrina/hypothesis-ledger)")

tab_live, tab_browse, tab_sparql = st.tabs(["Extract from an abstract", "Browse the 144 studies", "Query the graph"])

with tab_live:
    items, extractions = load_items(), load_extractions()
    mode = st.radio("Source", ["Paste an abstract", "Open a stored result"], horizontal=True)
    if mode == "Open a stored result":
        label = {i: f"{it['title'][:110]} ({it['hypothesis'].replace('_', ' ')})" for i, it in items.items()}
        pick = st.selectbox("Study", list(items), format_func=label.get)
        st.caption("Stored results come from the run reported on the project page. The abstract itself is not "
                   "republished here; follow the DOI to read it.")
        it = items[pick]
        if it["doi"]:
            st.markdown(f"[doi.org/{it['doi']}](https://doi.org/{it['doi']}) · "
                        f"[expert record in ORKG](https://orkg.org/paper/{it['paper_id']})")
        show_result(it, extractions[pick])
    else:
        try:
            key = st.secrets.get("OPENAI_API_KEY")
        except Exception:  # no secrets file in local runs
            key = None
        key = key or os.environ.get("OPENAI_API_KEY")
        hyp = st.selectbox("Hypothesis", list(HYPOTHESES), format_func=lambda h: HYPOTHESES[h])
        title = st.text_input("Title (optional)")
        abstract = st.text_area("Abstract", height=220, max_chars=MAX_CHARS,
                                placeholder="Paste the abstract of an invasion biology study.")
        runs = st.session_state.setdefault("runs", 0)
        if not key:
            st.info("Live extraction is switched off in this deployment. Open a stored result instead.")
        elif runs >= MAX_LIVE_RUNS:
            st.warning(f"This session has used its {MAX_LIVE_RUNS} live extractions. Reload the page to start a new session.")
        elif st.button("Extract claims", type="primary", disabled=len(abstract.split()) < 40):
            os.environ["OPENAI_API_KEY"] = key
            from openai import OpenAI
            from extract import run_one
            with st.spinner(f"Reading the abstract with {MODEL}…"):
                rec = run_one(OpenAI(), {"hypothesis": hyp, "title": title or "untitled", "abstract": abstract}, "claims")
            st.session_state["runs"] = runs + 1
            st.session_state["last"] = (hyp, title, abstract, rec)
        if len(abstract.split()) < 40:
            st.caption("Paste at least 40 words to start.")
        if "last" in st.session_state:
            hyp_l, title_l, abstract_l, rec = st.session_state["last"]
            item = {"paper_id": "user_input", "hypothesis": hyp_l, "title": title_l or "untitled", "doi": "",
                    "gold": "user", "gold_habitat": "unclear"}
            if rec.get("rounds") == 2:
                st.caption("Some quotes were not verbatim at first and were sent back to the model once.")
            show_result(item, rec, abstract_l)

with tab_browse:
    items, extractions = load_items(), load_extractions()
    rows = []
    for i, it in items.items():
        ans = extractions[i]["answer"]
        rows.append({"hypothesis": it["hypothesis"].replace("_", " "), "title": it["title"], "experts": it["gold"],
                     "model": ans["verdict"], "agree": it["gold"] == ans["verdict"], "design (model)": ans["design"],
                     "method (experts)": it["gold_method"], "habitat": it["gold_habitat"], "claims": len(ans["claims"]),
                     "doi": f"https://doi.org/{it['doi']}" if it["doi"] else None})
    df = pd.DataFrame(rows)
    c1, c2, c3 = st.columns(3)
    h = c1.multiselect("Hypothesis", sorted(df.hypothesis.unique()), default=sorted(df.hypothesis.unique()))
    show = c2.radio("Show", ["All", "Agreements", "Disagreements"], horizontal=True)
    d = c3.multiselect("Design read by the model", sorted(df["design (model)"].unique()),
                       default=sorted(df["design (model)"].unique()))
    view = df[df.hypothesis.isin(h) & df["design (model)"].isin(d)]
    if show != "All":
        view = view[view.agree == (show == "Agreements")]
    decided = view[view.experts != "mixed"]
    st.metric("Agreement with experts in this selection",
              f"{decided.agree.mean():.0%}" if len(decided) else "–", help=f"{len(decided)} studies with one expert label")
    st.dataframe(view, hide_index=True, use_container_width=True,
                 column_config={"doi": st.column_config.LinkColumn("doi", display_text="open")})

with tab_sparql:
    g = load_graph()
    st.caption(f"The knowledge graph from the run: {len(g):,} triples. Read-only SELECT queries.")
    name = st.selectbox("Example query", list(QUERIES))
    query = st.text_area("SPARQL", QUERIES[name].read_text(), height=260, key=f"q_{name}")
    if st.button("Run query"):
        if not re.search(r"^\s*(PREFIX[^\n]*\n\s*|#[^\n]*\n\s*)*SELECT\b", query, flags=re.I):
            st.error("Only SELECT queries can run here.")
        else:
            try:
                res = g.query(query)
                out = [{str(v): (str(row[v]).replace("https://sayamrina.github.io/hypothesis-ledger/ns#", "hl:")
                                 if row[v] is not None else "") for v in res.vars} for row in res]
                st.write(f"{len(out)} rows")
                st.dataframe(pd.DataFrame(out), hide_index=True, use_container_width=True)
            except Exception as e:  # malformed query from the text box
                st.error(f"The query could not run: {e}")

st.caption("This app was built by Amrina, with AI as a supporting tool for coding. Expert labels: Hi Knowledge data "
           "in the Open Research Knowledge Graph (TIB), CC BY-SA.")
