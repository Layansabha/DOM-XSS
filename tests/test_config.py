from pathlib import Path

from app.config import Settings


def test_legacy_artifact_paths_are_migrated() -> None:
    settings = Settings(
        _env_file=None,
        ml_model_path="/app/artifacts/lightgbm_model.txt",
        ml_vocab_path="/app/artifacts/vocab_top500_filtered.json",
    )

    assert settings.ml_model_path == Path(
        "/app/artifacts/lightgbm_security_v2.txt"
    )
    assert settings.ml_vocab_path == Path(
        "/app/artifacts/vocab_security_v2.json"
    )


def test_grouped_artifact_paths_are_migrated() -> None:
    settings = Settings(
        _env_file=None,
        ml_model_path="/app/artifacts/lightgbm_grouped_model.txt",
        ml_vocab_path="/app/artifacts/vocab_top500_grouped.json",
    )

    assert settings.ml_model_path == Path("/app/artifacts/lightgbm_security_v2.txt")
    assert settings.ml_vocab_path == Path("/app/artifacts/vocab_security_v2.json")


def test_custom_artifact_paths_are_preserved() -> None:
    settings = Settings(
        _env_file=None,
        ml_model_path="/models/custom.txt",
        ml_vocab_path="/models/custom.json",
    )

    assert settings.ml_model_path == Path("/models/custom.txt")
    assert settings.ml_vocab_path == Path("/models/custom.json")
