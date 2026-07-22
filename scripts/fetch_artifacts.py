from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from pathlib import Path

SOURCE_COMMIT = "a14721a928d492055d02dbb5416318d3de8062b4"
BASE_URL = (
    "https://raw.githubusercontent.com/Layansabha/Dom-xss-ML/"
    f"{SOURCE_COMMIT}"
)

ARTIFACTS = {
    "random_forest_best_model_final.pkl": {
        "source": "models/random_forest_best_model_final.pkl",
        "git_blob_sha": "e2b867b1d39decfd98df5ee2847d15d2da8fe597",
    },
    "vocab_top500_filtered.pkl": {
        "source": "preprocessing/vocab_top500_filtered.pkl",
        "git_blob_sha": "6806138426c8db94b67edb15e401e67ee15e53de",
    },
}


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def download(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DOM-XSS-Pipeline artifact fetcher/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"artifact download failed with HTTP {response.status}")
        return response.read()


def main() -> None:
    output_dir = Path(os.getenv("ARTIFACT_DIR", "/app/artifacts"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for filename, metadata in ARTIFACTS.items():
        url = f"{BASE_URL}/{metadata['source']}"
        data = download(url)
        actual_sha = git_blob_sha(data)
        expected_sha = metadata["git_blob_sha"]

        if actual_sha != expected_sha:
            raise RuntimeError(
                f"integrity check failed for {filename}: "
                f"expected {expected_sha}, got {actual_sha}"
            )

        with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)

        destination = output_dir / filename
        temporary_path.replace(destination)
        print(f"installed {filename} ({len(data)} bytes, blob {actual_sha})")


if __name__ == "__main__":
    main()
