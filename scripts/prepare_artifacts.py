from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

SOURCE_COMMIT = "f3eff79a4b695ea9c36edf810917889c3b05e9a7"
BASE_URL = f"https://raw.githubusercontent.com/Layansabha/Dom-xss-ML/{SOURCE_COMMIT}"
SOURCE_ARTIFACTS = {
    "model": {
        "path": "models/lightgbm_grouped_model.txt",
        "git_blob_sha": "a721cd648fcee6467c3864b94f98841f595f51ff",
        "size": 1_016_695,
    },
    "vocabulary": {
        "path": "preprocessing/vocab_top500_grouped.json",
        "git_blob_sha": "d54e409b236c982762ed19b1a6ec72857812fc1e",
        "size": 9_239,
    },
    "metadata": {
        "path": "models/lightgbm_grouped_metadata.json",
        "git_blob_sha": "6457f73d5cd2fab8c179d62b2d5634a9fcd4af33",
        "size": 3_319,
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
        source_metadata = download_verified("metadata", staging)

        model_text = source_model.read_text(encoding="utf-8")
        vocabulary = json.loads(source_vocabulary.read_text(encoding="utf-8"))
        metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
        if "max_feature_idx=499" not in model_text:
            raise RuntimeError("source model does not declare 500 features")
        if not isinstance(vocabulary, dict) or len(vocabulary) != 500:
            raise RuntimeError("source vocabulary is not a 500-token mapping")
        if not all(
            isinstance(token, str) and isinstance(index, int) for token, index in vocabulary.items()
        ):
            raise RuntimeError("source vocabulary entries are invalid")
        if sorted(vocabulary.values()) != list(range(len(vocabulary))):
            raise RuntimeError("source vocabulary indexes are not contiguous and unique")
        if not isinstance(metadata, dict) or metadata.get("artifact_version") != 2:
            raise RuntimeError("source metadata is invalid")
        if metadata.get("output_semantics") != "risk_score_not_calibrated_probability":
            raise RuntimeError("source score semantics are missing")

        native_model = staging / "lightgbm_grouped_model.txt"
        native_vocabulary = staging / "vocab_top500_grouped.json"
        native_metadata = staging / "lightgbm_grouped_metadata.json"
        source_model.replace(native_model)
        write_json(native_vocabulary, vocabulary)
        write_json(native_metadata, metadata)

        source_manifest = {
            "model": {
                **SOURCE_ARTIFACTS["model"],
                "sha256": sha256_file(native_model),
            },
            "vocabulary": {
                **SOURCE_ARTIFACTS["vocabulary"],
                "sha256": sha256_file(source_vocabulary),
            },
            "metadata": {
                **SOURCE_ARTIFACTS["metadata"],
                "sha256": sha256_file(source_metadata),
            },
        }
        manifest = {
            "source_commit": SOURCE_COMMIT,
            "source_artifacts": source_manifest,
            "runtime_artifacts": {
                native_model.name: {"sha256": sha256_file(native_model)},
                native_vocabulary.name: {"sha256": sha256_file(native_vocabulary)},
                native_metadata.name: {"sha256": sha256_file(native_metadata)},
            },
        }
        manifest_path = staging / "artifact-manifest.json"
        write_json(manifest_path, manifest)

        for artifact in (native_model, native_vocabulary, native_metadata, manifest_path):
            artifact.replace(output_dir / artifact.name)
            print(f"installed {artifact.name}")


if __name__ == "__main__":
    main()
