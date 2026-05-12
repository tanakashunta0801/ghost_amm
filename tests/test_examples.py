import json
from pathlib import Path

from ghost_amm.config import Config
from ghost_amm.replay.engine import ReplayEngine


def test_sell_shock_example_replay_matches_expected_summary(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[1]
    example_dir = repo / "examples" / "sell_shock"
    out_dir = tmp_path / "sell_shock_report"

    ReplayEngine(Config()).run_files([example_dir / "input.jsonl"], out_dir)

    actual = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    expected = json.loads((example_dir / "expected_summary.json").read_text(encoding="utf-8"))
    assert actual == expected
