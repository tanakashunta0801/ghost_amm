import json

from ghost_amm.cli import main
from ghost_amm.config import load_config


def test_missing_explicit_config_fails_closed(tmp_path) -> None:
    missing = tmp_path / "typo.yaml"

    try:
        load_config(missing)
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("missing explicit config path should fail closed")


def test_none_config_uses_defaults() -> None:
    config = load_config(None)

    assert config.get("pair") == "btc_jpy"
    assert config.get("execution.mode") == "replay"


def test_cli_missing_config_returns_1(capsys, tmp_path) -> None:
    missing = tmp_path / "typo.yaml"

    code = main(["replay", "--events", str(tmp_path / "events.jsonl"), "--config", str(missing), "--out", str(tmp_path / "out")])

    assert code == 1
    error = json.loads(capsys.readouterr().err)
    assert error["path"] == str(missing)
