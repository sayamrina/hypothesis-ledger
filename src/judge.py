"""LLM-as-a-judge: a second model call rates whether each verdict of the 'claims' condition is correct.

The judge sees the abstract, the hypothesis, the verdict and its rationale, but not the expert label.
Comparing its ratings with the expert labels shows how far an LLM judge can replace expert checking.
Output: results/judge.jsonl
"""
import json
import sys
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))
from extract import HYPOTHESES, MODEL, load_items  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class Judgement(BaseModel):
    verdict_correct: Literal["yes", "no"]
    reason: str


def main():
    client = OpenAI()
    items = {i["item_id"]: i for i in load_items()}
    out_path = ROOT / "results" / "judge.jsonl"
    done = {json.loads(l)["item_id"] for l in out_path.open()} if out_path.exists() else set()
    with out_path.open("a") as f:
        for line in (ROOT / "results" / "extractions_claims.jsonl").open():
            rec = json.loads(line)
            if rec["item_id"] in done:
                continue
            item, ans = items[rec["item_id"]], rec["answer"]
            prompt = (f"Hypothesis: {HYPOTHESES[item['hypothesis']]}\n\nAbstract: {item['abstract']}\n\n"
                      f"An assistant judged that this study's findings make the hypothesis '{ans['verdict']}' "
                      f"(supported = agree, questioned = contradict or no effect, undecided = mixed). "
                      f"Its reason: {ans['rationale']}\n\nIs this verdict correct given the abstract?")
            resp = client.beta.chat.completions.parse(
                model=MODEL, temperature=0, response_format=Judgement,
                messages=[{"role": "system", "content": "You are a careful reviewer of evidence syntheses in ecology."},
                          {"role": "user", "content": prompt}])
            j = resp.choices[0].message.parsed
            f.write(json.dumps({"item_id": rec["item_id"], **j.model_dump()}) + "\n")


if __name__ == "__main__":
    main()
