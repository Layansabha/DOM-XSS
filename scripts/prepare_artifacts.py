from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import joblib
from lightgbm import LGBMClassifier

SOURCE_COMMIT = "a14721a928d492055d02dbb5416318d3de8062b4"
BASE_URL = f"https://raw.githubusercontent.com/Layansabha/Dom-xss-ML/{SOURCE_COMMIT}"
SOURCE_ARTIFACTS = {
    "model": {
        "path": "models/lightgbm_best_model_final.pkl",
        "git_blob_sha": "f325da95bf788bbc20234e9f526f4a95c555aa27",
        "size": 725_044,
    },
    "vocabulary": {
        "path": "preprocessing/vocab_top500_filtered.pkl",
        "git_blob_sha": "6806138426c8db94b67edb15e401e67ee15e53de",
        "size": 6_632,
    },
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(name: str, output_dir: Path, timeout: int = 120) -> Path:
    metadata = SOURCE_ARTIFACTS[name]
    source_path = str(metadata["path"])
    request = urllib.request.Request(
        f"{BASE_URL}/{source_path}",
        headers={"User-Agent": "DOM-XSS-Pipeline artifact builder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"artifact download failed with HTTP {response.status}")
        expected_size = int(metadata["size"])
        data = response.read(expected_size + 1)

    if len(data) != expected_size:
        raise RuntimeError(
            f"size check failed for {source_path}: expected {expected_size}, got {len(data)}"
        )

    actual_sha = git_blob_sha(data)
    expected_sha = str(metadata["git_blob_sha"])
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"integrity check failed for {source_path}: expected {expected_sha}, got {actual_sha}"
        )

    destination = output_dir / Path(source_path).name
    destination.write_bytes(data)
    print(f"verified {source_path} ({len(data)} bytes, blob {actual_sha})")
    return destination


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    output_dir = Path(os.getenv("ARTIFACT_DIR", "/app/artifacts"))
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=output_dir) as temporary:
        staging = Path(temporary)
        source_model = download_verified("model", staging)
        source_vocabulary = download_verified("vocabulary", staging)

        model = joblib.load(source_model)
        vocabulary = joblib.load(source_vocabulary)
        if not isinstance(model, LGBMClassifier):
            raise RuntimeError("source model is not an LGBMClassifier")
        if not isinstance(vocabulary, dict) or len(vocabulary) != 500:
            raise RuntimeError("source vocabulary is not a 500-token mapping")
        if not all(
            isinstance(token, str) and isinstance(index, int) for token, index in vocabulary.items()
        ):
            raise RuntimeError("source vocabulary entries are invalid")
        if sorted(vocabulary.values()) != list(range(len(vocabulary))):
            raise RuntimeError("source vocabulary indexes are not contiguous and unique")
        if int(model.n_features_in_) != len(vocabulary):
            raise RuntimeError("model and vocabulary feature counts do not match")

        native_model = staging / "lightgbm_model.txt"
        native_vocabulary = staging / "vocab_top500_filtered.json"
        model.booster_.save_model(native_model)
        write_json(native_vocabulary, vocabulary)

        source_manifest = {
            "model": {
                **SOURCE_ARTIFACTS["model"],
                "sha256": sha256_file(source_model),
            },
            "vocabulary": {
                **SOURCE_ARTIFACTS["vocabulary"],
                "sha256": sha256_file(source_vocabulary),
            },
        }
        manifest = {
            "source_commit": SOURCE_COMMIT,
            "source_artifacts": source_manifest,
            "runtime_artifacts": {
                native_model.name: {"sha256": sha256_file(native_model)},
                native_vocabulary.name: {"sha256": sha256_file(native_vocabulary)},
            },
        }
        manifest_path = staging / "artifact-manifest.json"
        write_json(manifest_path, manifest)

        for artifact in (native_model, native_vocabulary, manifest_path):
            artifact.replace(output_dir / artifact.name)
            print(f"installed {artifact.name}")


if __name__ == "__main__":
    main()
