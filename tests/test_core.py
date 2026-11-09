import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import extract  # noqa: E402
from extract import CausalClaim, ClaimsAnswer  # noqa: E402


def claim(quote):
    return CausalClaim(cause="enemy damage", effect="invader growth", cause_node="enemy_pressure",
                       effect_node="invader_performance", direction="decreases", organism="plants",
                       habitat="terrestrial", evidence_quote=quote)


def answer(*quotes):
    return ClaimsAnswer(claims=[claim(q) for q in quotes], design="observational", verdict="supported",
                        uncertainty="low", rationale="r")


def test_quote_check_ignores_case_and_punctuation():
    abstract = "Exotic plants had LESS leaf damage (12%) than natives, consistent with enemy release."
    assert extract.missing_quotes(answer("exotic plants had less leaf damage 12% than natives"), abstract) == []


def test_quote_check_flags_invented_quote():
    abstract = "Exotic plants had less leaf damage than natives."
    assert extract.missing_quotes(answer("exotic plants grew twice as tall"), abstract) == ["exotic plants grew twice as tall"]


def test_items_keep_gold_only_when_contributions_agree(tmp_path, monkeypatch):
    rows = [
        {"contribution_id": "C1", "paper_id": "P1", "hypothesis": "enemy_release", "title": "t", "doi": "d",
         "abstract": "a", "fields": {"stand of hypothesis": ["Supported"], "Habitat": ["Terrestrial"]}},
        {"contribution_id": "C2", "paper_id": "P1", "hypothesis": "enemy_release", "title": "t", "doi": "d",
         "abstract": "a", "fields": {"stand of hypothesis": ["Questioned"], "Habitat": ["Terrestrial"]}},
        {"contribution_id": "C3", "paper_id": "P2", "hypothesis": "enemy_release", "title": "t", "doi": "d",
         "abstract": "a", "fields": {"stand of hypothesis": ["Supported"], "Habitat": ["terrestrial"]}},
        {"contribution_id": "C4", "paper_id": "P3", "hypothesis": "enemy_release", "title": "t", "doi": None,
         "abstract": None, "fields": {"stand of hypothesis": ["Supported"]}},
    ]
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "studies.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(extract, "ROOT", tmp_path)
    items = {i["paper_id"]: i for i in extract.load_items()}
    assert set(items) == {"P1", "P2"}
    assert items["P1"]["gold"] == "mixed"
    assert items["P2"]["gold"] == "supported" and items["P2"]["gold_habitat"] == "terrestrial"
