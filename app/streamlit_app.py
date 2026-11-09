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
from extract import HYPOTHESES, MODEL  # noqa: E402

MAX_LIVE_RUNS = 5
MAX_CHARS = 3500
VERDICT_COLOR = {"supported": "#5f9b40", "questioned": "#7d5aab", "undecided": "#a7a196", "mixed": "#a7a196"}
ARROW = {"increases": ("↑", "raises"), "decreases": ("↓", "lowers"), "no_effect": ("○", "does not change"),
         "unclear": ("?", "has an unclear effect on")}
QUERIES = {
    "Where the model disagrees with the experts": ROOT / "queries" / "disagreements.rq",
    "Verdicts by study design": ROOT / "queries" / "support_by_design.rq",
    "Claims whose quote could not be verified": ROOT / "queries" / "claims_without_verified_quote.rq",
}
# An invented abstract for trying the app. It is not taken from any paper.
EXAMPLE = (
    "Invasive plants are often thought to succeed because they escape their natural enemies. We compared leaf damage "
    "and seed predation on the shrub Lantana camara in five native populations in Central America and five introduced "
    "populations in eastern Australia. Leaf damage by insect herbivores was 64% lower in the introduced range, and the "
    "number of specialist herbivore species recorded on the plant fell from eleven to two. Seed predation did not differ "
    "between ranges. In a common garden experiment, plants protected with insecticide grew 30% taller than unprotected "
    "plants in the native range, but insecticide had no effect on growth in the introduced range. Our results suggest "
    "that release from specialist leaf herbivores, but not from seed predators, contributes to the vigorous growth of "
    "Lantana camara in Australia."
)

st.set_page_config(page_title="Hypothesis Ledger Explorer", page_icon="📒", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400&family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&display=swap');
:root { --deep:#0f2e29; --deep2:#163a34; --line:#2b524a; --on:#e6efe9; --onm:#9fb8ae; --ink:#17262a; --muted:#586862;
        --rule:#d5ddd3; --sheet:#f8faf6; --paper:#eef2ec; --river:#1b6b84; --pollen:#e3ef7a; --pollen-ink:#2c3410;
        --sup:#5f9b40; --que:#7d5aab; --und:#a7a196; }
html, body, .stApp, .stMarkdown, p, li, label, button, input, textarea, select { font-family: "Instrument Sans", system-ui, sans-serif; }
[data-testid="stIconMaterial"], .material-symbols-rounded { font-family: "Material Symbols Rounded" !important; }
.block-container { padding-top: 3.4rem; padding-bottom: 4rem; max-width: 1160px; }
h1, h2, h3 { font-family: "Newsreader", Georgia, serif !important; font-weight: 500 !important; letter-spacing: -0.01em; }
.stTextArea textarea, .stTextInput input { font-family: "Newsreader", Georgia, serif; font-size: 1.02rem; line-height: 1.55; }
.stCode code, pre code { font-family: "JetBrains Mono", ui-monospace, monospace !important; font-size: 0.8rem !important; }

/* banner and hero */
.pf-banner { background: var(--deep2); color: var(--onm); padding: 8px 16px; border-radius: 8px 8px 0 0; font-size: 0.86rem;
             border-bottom: 1px solid var(--line); }
.pf-banner a { color: var(--on); }
.hero { background: var(--deep); color: var(--on); border-radius: 0 0 14px 14px; padding: 34px 34px 28px; margin-bottom: 26px;
        display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 34px; align-items: center; }
.hero h1 { color: var(--on); font-size: clamp(2.2rem, 4.6vw, 3.4rem); line-height: 1; margin: 0 0 14px; padding: 0; }
.hero p { color: var(--on); font-family: "Newsreader", Georgia, serif; font-size: 1.12rem; line-height: 1.5; margin: 0 0 16px; max-width: 34rem; }
.hero .links a { color: var(--on); font-size: 0.92rem; margin-right: 18px; font-weight: 600; }
.figs { display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--line); margin-top: 16px; }
.figs div { padding: 12px 12px 0 0; }
.figs div + div { border-left: 1px solid var(--line); padding-left: 14px; }
.figs b { display: block; font-family: "Newsreader", Georgia, serif; font-weight: 500; font-size: 1.9rem; line-height: 1; color: var(--on); }
.figs span { font-size: 0.8rem; color: var(--onm); line-height: 1.35; display: block; margin-top: 6px; }
.mini { background: var(--deep2); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
.mini .t { font-size: 0.82rem; color: var(--onm); margin-bottom: 10px; display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.mini .t b { color: var(--on); font-weight: 600; }
.marks { display: flex; flex-wrap: wrap; gap: 3px; }
.marks i { width: 9px; height: 22px; display: grid; grid-template-rows: 1fr 1fr; gap: 2px; }
.marks i s, .marks i u { display: block; border-radius: 1.5px; text-decoration: none; }
.marks i u { opacity: 0.75; }
@media (prefers-reduced-motion: no-preference) {
  .marks i { animation: grow .45s cubic-bezier(.2,.7,.2,1) both; animation-delay: calc(var(--i) * 5ms); }
  @keyframes grow { from { opacity: 0; transform: scaleY(.2); } to { opacity: 1; transform: none; } }
}
.key { display: flex; gap: 12px; flex-wrap: wrap; font-size: 0.76rem; color: var(--onm); margin-top: 10px; }
.key span::before { content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 5px; background: var(--c); }
.c-supported { background: var(--sup); } .c-questioned { background: var(--que); } .c-undecided, .c-mixed { background: var(--und); }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--rule); }
.stTabs [data-baseweb="tab"] { font-size: 1rem; font-weight: 600; padding: 10px 14px; }
.stTabs [data-baseweb="tab"] p { font-size: 1rem; }

/* result */
.verdicts { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 4px 0 12px; font-size: 0.9rem; color: var(--muted); }
.chip { display: inline-flex; align-items: center; gap: 7px; padding: 5px 11px; border-radius: 6px; color: #fff; font-weight: 600; font-size: 0.88rem; }
.chip.out { background: transparent; color: var(--ink); border: 1px solid var(--rule); font-weight: 500; }
.why { font-family: "Newsreader", Georgia, serif; font-size: 1.08rem; line-height: 1.55; color: var(--ink); margin: 0 0 18px; max-width: 46rem; }
.abstract { font-family: "Newsreader", Georgia, serif; font-size: 1.08rem; line-height: 1.75; background: var(--sheet); border: 1px solid var(--rule);
            border-radius: 10px; padding: 20px 22px; margin-bottom: 20px; }
mark.ev { background: var(--pollen); color: var(--pollen-ink); padding: 1px 3px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
.claims-h { font-weight: 600; font-size: 1rem; margin: 6px 0 8px; }
.claim { display: grid; grid-template-columns: 2.4rem 1fr; gap: 12px; padding: 14px 0; border-top: 1px solid var(--rule); }
.claim .dir { width: 2.4rem; height: 2.4rem; border-radius: 8px; display: grid; place-items: center; font-size: 1.25rem; font-weight: 700; color: #fff; }
.claim .line { font-size: 1.02rem; line-height: 1.45; }
.claim .line b { font-weight: 600; }
.claim .tags { font-size: 0.8rem; color: var(--muted); margin: 3px 0 6px; }
.claim blockquote { margin: 0; padding: 0 0 0 12px; border-left: 3px solid var(--pollen); font-family: "Newsreader", Georgia, serif; font-size: 0.98rem;
                    line-height: 1.5; color: var(--ink); }
.claim .ok { color: var(--sup); font-weight: 600; font-size: 0.8rem; }
.claim .bad { color: var(--que); font-weight: 600; font-size: 0.8rem; }
.empty { border: 1px dashed var(--rule); border-radius: 10px; padding: 26px; color: var(--muted); font-size: 0.95rem; }
.foot { color: var(--muted); font-size: 0.82rem; margin-top: 40px; border-top: 1px solid var(--rule); padding-top: 14px; }
@media (max-width: 820px) {
  .hero { grid-template-columns: 1fr; padding: 24px 18px; gap: 20px; }
  .figs b { font-size: 1.5rem; }
}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_items():
    with (ROOT / "data" / "items.csv").open() as f:
        return {r["item_id"]: r for r in csv.DictReader(f)}


@st.cache_data
def load_extractions():
    return {json.loads(l)["item_id"]: json.loads(l) for l in (ROOT / "results" / "extractions_claims.jsonl").open()}


@st.cache_data
def load_metrics():
    return json.loads((ROOT / "results" / "metrics.json").read_text())


@st.cache_resource
def load_graph():
    return Graph().parse(ROOT / "results" / "ledger.ttl")


@st.cache_resource
def load_shapes():
    return Graph().parse(ROOT / "shapes" / "ledger_shapes.ttl")


def esc(s):
    return html.escape(str(s))


def marks(pairs):
    """Mini ledger: one mark per study, expert verdict on top, model verdict below."""
    out = "".join(f'<i style="--i:{k}"><s class="c-{e}"></s><u class="c-{m}"></u></i>' for k, (e, m) in enumerate(pairs))
    return f'<div class="marks">{out}</div>'


def hero():
    items, ex, m = load_items(), load_extractions(), load_metrics()
    order = {"supported": 0, "questioned": 1, "undecided": 2, "mixed": 3}
    pairs = sorted(((items[i]["gold"], r["answer"]["verdict"]) for i, r in ex.items()),
                   key=lambda p: (order[p[0]], order[p[1]]))
    agree = sum(e == v for e, v in pairs)
    st.markdown(f"""
<div class="pf-banner">This app was developed by Amrina as part of a portfolio.
<a href="https://sayamrina.github.io/" target="_blank" rel="noopener">View the portfolio</a></div>
<div class="hero">
  <div>
    <h1>Hypothesis Ledger Explorer</h1>
    <p>Give a language model an ecology abstract. It pulls out each causal claim with the sentence it comes from,
       decides whether the study supports an invasion biology hypothesis, and stores the result as a knowledge graph
       that remembers its sources.</p>
    <div class="links"><a href="https://sayamrina.github.io/hypothesis-ledger/" target="_blank" rel="noopener">Project page</a>
      <a href="https://github.com/sayamrina/hypothesis-ledger" target="_blank" rel="noopener">Code and data</a></div>
    <div class="figs">
      <div><b>{m['claims']['accuracy']:.0%}</b><span>verdicts match the experts</span></div>
      <div><b>{m['provenance']['quotes_verbatim_after_check']:.1%}</b><span>quotes verified word for word</span></div>
      <div><b>{m['provenance']['claims']}</b><span>causal claims in the graph</span></div>
    </div>
  </div>
  <div class="mini">
    <div class="t"><b>The 144 studies in the run</b><span>{agree} verdicts agree with the experts</span></div>
    {marks(pairs)}
    <div class="key"><span style="--c:var(--sup)">supported</span><span style="--c:var(--que)">questioned</span>
      <span style="--c:var(--und)">undecided</span><span style="--c:var(--onm)">top: experts, bottom: model</span></div>
  </div>
</div>""", unsafe_allow_html=True)


def highlight(abstract, quotes):
    """Mark every verified quote in the abstract (case-insensitive, whitespace-tolerant)."""
    text = html.escape(abstract)
    for q in sorted(set(quotes), key=len, reverse=True):
        words = [re.escape(html.escape(w)) for w in q.split()]
        if words:
            text = re.sub(r"\s+".join(words), lambda mt: f'<mark class="ev">{mt.group(0)}</mark>', text, count=1, flags=re.I)
    return f'<div class="abstract">{text}</div>'


def record_graph(item, rec):
    g, run = new_graph("app" if item["paper_id"].startswith("user") else "claims")
    add_record(g, item, rec, run)
    conforms, _, report = validate(g, shacl_graph=load_shapes())
    return g, conforms, report


def chip(label, verdict):
    return f'<span class="chip" style="background:{VERDICT_COLOR.get(verdict, "#a7a196")}">{label}: {esc(verdict)}</span>'


def claim_html(c, verified):
    sym, verb = ARROW[c["direction"]]
    color = {"increases": "#1b6b84", "decreases": "#7d5aab", "no_effect": "#a7a196", "unclear": "#a7a196"}[c["direction"]]
    check = '<span class="ok">✓ quote found in the abstract</span>' if verified else \
            '<span class="bad">✗ quote not found in the abstract</span>'
    return f"""<div class="claim"><div class="dir" style="background:{color}" title="{esc(c['direction'])}">{sym}</div>
<div><div class="line"><b>{esc(c['cause'])}</b> {verb} <b>{esc(c['effect'])}</b></div>
<div class="tags">{esc(c['organism'])}, {esc(c['habitat'])} · graph link {esc(c['cause_node'])} → {esc(c['effect_node'])}</div>
<blockquote>{esc(c['evidence_quote'])}</blockquote>{check}</div></div>"""


def show_result(item, rec, abstract=None):
    ans = rec["answer"]
    missing = rec.get("quotes_missing", [])
    head = chip("Model", ans["verdict"])
    if item.get("gold") not in (None, "user"):
        head += chip("Experts", item["gold"])
    head += (f'<span class="chip out">design: {esc(ans["design"].replace("_", " "))}</span>'
             f'<span class="chip out">uncertainty: {esc(ans["uncertainty"])}</span>')
    st.markdown(f'<div class="verdicts">{head}</div><p class="why">{esc(ans["rationale"])}</p>', unsafe_allow_html=True)
    if abstract:
        verified = [c["evidence_quote"] for c in ans["claims"] if c["evidence_quote"] not in missing]
        st.markdown(highlight(abstract, verified), unsafe_allow_html=True)
    claims = "".join(claim_html(c, c["evidence_quote"] not in missing) for c in ans["claims"])
    st.markdown(f'<div class="claims-h">{len(ans["claims"])} causal claims</div>{claims}', unsafe_allow_html=True)
    st.caption("The arrow follows the cause as the model named it. When that cause is phrased as an absence, such as "
               "\"release from enemies\", the link between graph categories can carry the opposite sign; the project page "
               "discusses this.")
    g, conforms, report = record_graph(item, rec)
    with st.expander(f"Knowledge graph for this record: {len(g)} triples, SHACL check {'passed' if conforms else 'failed'}"):
        st.code(g.serialize(format="turtle"), language="turtle")
        if not conforms:
            st.text(report)


hero()
tab_live, tab_browse, tab_sparql = st.tabs(["Extract from an abstract", "Browse the 144 studies", "Query the graph"])

with tab_live:
    items, extractions = load_items(), load_extractions()
    mode = st.radio("Source", ["Paste an abstract", "Open a stored result"], horizontal=True, label_visibility="collapsed")
    if mode == "Open a stored result":
        label = {i: f"{it['title'][:110]} ({it['hypothesis'].replace('_', ' ')})" for i, it in items.items()}
        pick = st.selectbox("Study", list(items), format_func=label.get)
        it = items[pick]
        links = ""
        if it["doi"]:
            links = f'<a href="https://doi.org/{esc(it["doi"])}" target="_blank" rel="noopener">Read the abstract (DOI)</a> &nbsp; '
        links += f'<a href="https://orkg.org/paper/{esc(it["paper_id"])}" target="_blank" rel="noopener">Expert record in ORKG</a>'
        st.markdown(f'<h3 style="margin:10px 0 4px">{esc(it["title"])}</h3><p style="font-size:.9rem">{links}</p>',
                    unsafe_allow_html=True)
        st.caption("From the run reported on the project page. The abstract is not republished here.")
        show_result(it, extractions[pick])
    else:
        try:
            key = st.secrets.get("OPENAI_API_KEY")
        except Exception:  # no secrets file in local runs
            key = None
        key = key or os.environ.get("OPENAI_API_KEY")
        c1, c2 = st.columns([2, 1])
        hyp = c1.selectbox("Hypothesis to test", list(HYPOTHESES), format_func=lambda h: HYPOTHESES[h])
        title = c2.text_input("Title (optional)")
        if st.button("Fill in an invented example"):
            st.session_state["abstract"] = EXAMPLE
        abstract = st.text_area("Abstract", height=210, max_chars=MAX_CHARS, key="abstract",
                                placeholder="Paste the abstract of an invasion biology study, at least 40 words.")
        if st.session_state.get("abstract") == EXAMPLE:
            st.caption("This example was written for testing the app. It does not come from a real study.")
        runs = st.session_state.setdefault("runs", 0)
        if not key:
            st.info("Live extraction is switched off in this deployment. Choose 'Open a stored result' above.")
        elif runs >= MAX_LIVE_RUNS:
            st.warning(f"This session has used its {MAX_LIVE_RUNS} live extractions. Reload the page to start a new session.")
        elif st.button("Extract claims", type="primary", disabled=len(abstract.split()) < 40):
            os.environ["OPENAI_API_KEY"] = key
            from openai import OpenAI
            from extract import run_one
            with st.status("Reading the abstract", expanded=True) as status:
                st.write(f"Extracting causal claims with {MODEL}")
                rec = run_one(OpenAI(), {"hypothesis": hyp, "title": title or "untitled", "abstract": abstract}, "claims")
                st.write("Checking every quote against the abstract"
                         + (" (one correction round was needed)" if rec.get("rounds") == 2 else ""))
                st.write("Writing the record as RDF and validating it with SHACL")
                status.update(label=f"Done: {len(rec['answer']['claims'])} claims, verdict {rec['answer']['verdict']}",
                              state="complete", expanded=False)
            st.session_state["runs"] = runs + 1
            st.session_state["last"] = (hyp, title, abstract, rec)
        if "last" in st.session_state:
            hyp_l, title_l, abstract_l, rec = st.session_state["last"]
            item = {"paper_id": "user_input", "hypothesis": hyp_l, "title": title_l or "untitled", "doi": "",
                    "gold": "user", "gold_habitat": "unclear"}
            show_result(item, rec, abstract_l)
        elif key:
            st.markdown('<div class="empty">The result appears here: the verdict, your abstract with the evidence '
                        'sentences highlighted, every causal claim, and the RDF record.</div>', unsafe_allow_html=True)

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
    rate = f"{decided.agree.mean():.0%}" if len(decided) else "no studies"
    st.markdown(f'<div class="verdicts"><span class="chip out">{len(view)} studies shown</span>'
                f'<span class="chip out">agreement with experts: {rate}</span></div>'
                + marks(list(zip(view.experts, view.model))), unsafe_allow_html=True)
    st.write("")
    st.dataframe(view, hide_index=True, use_container_width=True,
                 column_config={"doi": st.column_config.LinkColumn("doi", display_text="open"),
                                "agree": st.column_config.CheckboxColumn("agree")})

with tab_sparql:
    g = load_graph()
    left, right = st.columns([3, 2])
    with right:
        st.markdown(f"**The graph from the run** has {len(g):,} triples: studies and hypotheses linked to the Open Research "
                    "Knowledge Graph, assessments with model and expert verdicts, and claims with their quote, source "
                    "DOI and extraction run (PROV-O).")
        name = st.radio("Start from an example", list(QUERIES))
    with left:
        query = st.text_area("SPARQL (SELECT only)", QUERIES[name].read_text(), height=300, key=f"q_{name}")
        run = st.button("Run query", type="primary")
    if run:
        if not re.search(r"^\s*(PREFIX[^\n]*\n\s*|#[^\n]*\n\s*)*SELECT\b", query, flags=re.I):
            st.error("Only SELECT queries can run here. Start the query with PREFIX lines or SELECT.")
        else:
            try:
                res = g.query(query)
                out = [{str(v): (str(row[v]).replace("https://sayamrina.github.io/hypothesis-ledger/ns#", "hl:")
                                 if row[v] is not None else "") for v in res.vars} for row in res]
                st.markdown(f'<div class="verdicts"><span class="chip out">{len(out)} rows</span></div>', unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(out), hide_index=True, use_container_width=True)
            except Exception as e:  # malformed query from the text box
                st.error(f"The query could not run: {e}")

st.markdown('<div class="foot">This app was built by Amrina, with AI as a supporting tool for coding. Expert labels: '
            'Hi Knowledge data in the Open Research Knowledge Graph (TIB), CC BY-SA. Example abstract invented for testing.</div>',
            unsafe_allow_html=True)
