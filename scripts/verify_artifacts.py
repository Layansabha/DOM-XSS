from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

MODEL_NAME = "lightgbm_security_v2.txt"
VOCABULARY_NAME = "vocab_security_v2.json"
METADATA_NAME = "lightgbm_security_v2_metadata.json"
MANIFEST_NAME = "artifact-manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid JSON artifact: {path.name}") from exc


def verify_bundle(artifact_dir: Path) -> dict[str, str]:
    manifest_path = artifact_dir / MANIFEST_NAME
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise RuntimeError("artifact manifest must be a JSON object")

    runtime_artifacts = manifest.get("runtime_artifacts")
    if not isinstance(runtime_artifacts, dict):
        raise RuntimeError("artifact manifest is missing runtime_artifacts")

    verified: dict[str, str] = {}
    for name in (MODEL_NAME, VOCABULARY_NAME, METADATA_NAME):
        path = artifact_dir / name
        if not path.is_file():
            raise RuntimeError(f"required artifact is missing: {name}")
        entry = runtime_artifacts.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            raise RuntimeError(f"manifest hash is missing for: {name}")
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise RuntimeError(f"artifact integrity check failed: {name}")
        verified[name] = actual

    try:
        model_text = (artifact_dir / MODEL_NAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError("LightGBM model is not valid UTF-8 text") from exc
    if "max_feature_idx=4095" not in model_text:
        raise RuntimeError("LightGBM model does not declare exactly 4096 features")

    vocabulary = read_json(artifact_dir / VOCABULARY_NAME)
    if not isinstance(vocabulary, dict) or len(vocabulary) != 4096:
        raise RuntimeError("vocabulary must contain exactly 4096 entries")
    if not all(
        isinstance(token, str) and isinstance(index, int)
        for token, index in vocabulary.items()
    ):
        raise RuntimeError("vocabulary entries are invalid")
    if sorted(vocabulary.values()) != list(range(4096)):
        raise RuntimeError("vocabulary indexes must be contiguous and unique")

    metadata = read_json(artifact_dir / METADATA_NAME)
    if not isinstance(metadata, dict) or metadata.get("artifact_version") != 3:
        raise RuntimeError("model metadata has an unsupported artifact version")
    if metadata.get("feature_contract") != "cmu-ast-bow-security-interactions-v2":
        raise RuntimeError("model metadata has an incompatible feature contract")
    if metadata.get("output_semantics") != "risk_score_not_calibrated_probability":
        raise RuntimeError("model metadata has incompatible score semantics")

    return verified


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the committed model bundle.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path("artifacts"),
        help="directory containing the runtime model artifacts",
    )
    args = parser.parse_args()
    verified = verify_bundle(args.artifact_dir)
    for name, digest in verified.items():
        print(f"verified {name} sha256={digest}")


if __name__ == "__main__":
    main()
