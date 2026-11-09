"""Extract causal claims and a verdict on the hypothesis from each abstract with an LLM.

Two conditions:
  direct   - the model only gives a verdict (supported / questioned / undecided)
  claims   - the model first extracts causal claims with verbatim evidence quotes, then gives the verdict;
             quotes that are not found in the abstract are sent back once for correction

Output: results/extractions_<condition>.jsonl (cached per study, so reruns are free)
"""
import json
import re
import sys
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-4o-mini-2024-07-18"
HYPOTHESES = {
    "enemy_release": "Enemy release hypothesis: the absence of enemies in the exotic range is a cause of invasion success.",
    "biotic_resistance": "Biotic resistance hypothesis: an ecosystem with high biodiversity is more resistant against non-native species than an ecosystem with lower biodiversity.",
}
Verdict = Literal["supported", "questioned", "undecided"]


Node = Literal["enemy_pressure", "native_diversity", "native_competitors", "resources_or_environment",
               "invader_establishment", "invader_performance", "invader_abundance_or_spread", "native_community", "other"]


class CausalClaim(BaseModel):
    cause: str = Field(description="the variable or factor that acts, e.g. 'enemy damage in the native range'")
    effect: str = Field(description="the outcome, e.g. 'invader growth'")
    cause_node: Node = Field(description="closest category for the cause")
    effect_node: Node = Field(description="closest category for the effect")
    direction: Literal["increases", "decreases", "no_effect", "unclear"] = Field(
        description="effect of the cause on effect_node itself; e.g. 'diversity increases resistance to the invader' "
                    "is cause_node=native_diversity, effect_node=invader_establishment, direction=decreases")
    organism: str = Field(description="taxon or species the claim is about, or 'unclear'")
    habitat: Literal["terrestrial", "freshwater", "marine", "unclear"]
    evidence_quote: str = Field(description="a verbatim span copied from the abstract that states this claim")


Design = Literal["experimental", "observational", "modelling_or_review", "unclear"]


class ClaimsAnswer(BaseModel):
    claims: list[CausalClaim]
    design: Design = Field(description="experimental = the study manipulated a factor; observational = it compared or correlated")
    verdict: Verdict
    uncertainty: Literal["low", "medium", "high"]
    rationale: str = Field(description="one sentence linking the claims to the verdict")


class DirectAnswer(BaseModel):
    verdict: Verdict
    uncertainty: Literal["low", "medium", "high"]
    rationale: str


SYSTEM = (
    "You assess ecological studies for an evidence synthesis in invasion biology. "
    "Use only the abstract you are given. 'supported' means the study's findings agree with the hypothesis, "
    "'questioned' means they contradict it or find no effect, 'undecided' means mixed or inconclusive results."
)


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def missing_quotes(answer, abstract):
    a = norm(abstract)
    return [c.evidence_quote for c in answer.claims if norm(c.evidence_quote) not in a]


def ask(client, messages, schema):
    resp = client.beta.chat.completions.parse(model=MODEL, messages=messages, response_format=schema, temperature=0)
    return resp.choices[0].message.parsed, resp.usage


def run_one(client, study, condition):
    user = f"Hypothesis: {HYPOTHESES[study['hypothesis']]}\n\nTitle: {study['title']}\n\nAbstract: {study['abstract']}"
    if condition == "direct":
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        answer, usage = ask(client, messages, DirectAnswer)
        return {"answer": answer.model_dump(), "tokens": usage.total_tokens, "rounds": 1}
    messages = [
        {"role": "system", "content": SYSTEM + " First list every causal claim the abstract makes, each with a verbatim "
                                              "evidence quote, then decide the verdict from these claims."},
        {"role": "user", "content": user},
    ]
    answer, usage = ask(client, messages, ClaimsAnswer)
    tokens, rounds = usage.total_tokens, 1
    bad = missing_quotes(answer, study["abstract"])
    if bad:
        messages += [
            {"role": "assistant", "content": answer.model_dump_json()},
            {"role": "user", "content": "These evidence quotes do not appear verbatim in the abstract: "
                                        + json.dumps(bad) + ". Copy exact spans or drop the claim, then answer again."},
        ]
        answer, usage = ask(client, messages, ClaimsAnswer)
        tokens += usage.total_tokens
        rounds = 2
    return {"answer": answer.model_dump(), "tokens": tokens, "rounds": rounds,
            "quotes_missing": missing_quotes(answer, study["abstract"])}


def load_items():
    """One item per paper and hypothesis. ORKG can hold several contributions per paper (e.g. per species);
    the gold verdict is kept only when all of them agree, otherwise it is 'mixed'."""
    groups = {}
    for line in (ROOT / "data" / "studies.jsonl").open():
        st = json.loads(line)
        if st["abstract"] and st["fields"].get("stand of hypothesis"):
            groups.setdefault((st["paper_id"], st["hypothesis"]), []).append(st)
    items = []
    for (paper_id, hyp), contribs in sorted(groups.items()):
        labels = {c["fields"]["stand of hypothesis"][0].strip().lower() for c in contribs}
        habitats = {(c["fields"].get("Habitat") or ["unclear"])[0].strip().lower() for c in contribs}
        methods = {(c["fields"].get("Research Method") or ["unclear"])[0].strip() for c in contribs}
        first = contribs[0]
        items.append({
            "item_id": f"{paper_id}:{hyp}", "paper_id": paper_id, "hypothesis": hyp,
            "title": first["title"], "doi": first["doi"], "abstract": first["abstract"],
            "contribution_ids": [c["contribution_id"] for c in contribs],
            "gold": labels.pop() if len(labels) == 1 else "mixed",
            "gold_habitat": habitats.pop() if len(habitats) == 1 else "mixed",
            "gold_method": methods.pop() if len(methods) == 1 else "mixed",
        })
    return items


def main(condition):
    client = OpenAI()
    studies = load_items()
    out_path = ROOT / "results" / f"extractions_{condition}.jsonl"
    out_path.parent.mkdir(exist_ok=True)
    done = {}
    if out_path.exists():
        done = {json.loads(l)["item_id"]: l for l in out_path.open()}
    with out_path.open("a") as f:
        for i, s in enumerate(studies):
            if s["item_id"] in done:
                continue
            rec = {"item_id": s["item_id"], "model": MODEL, **run_one(client, s, condition)}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if i % 25 == 0:
                print(condition, i, len(studies), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
