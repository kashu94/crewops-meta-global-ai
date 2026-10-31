"""Build the Lambda bundle in ``build/lambda``: the code, its dependencies, the console and
the demo data. Dependencies are Linux x86_64 wheels, so it builds the same on Windows, macOS
or Linux, with no Docker.

    uv run python scripts/build_lambda.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "lambda"
# Already in the Lambda Python runtime, and large.
PROVIDED = ("boto3", "botocore", "s3transfer", "jmespath")


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True, cwd=ROOT)


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("uv is not installed")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    requirements = ROOT / "build" / "requirements.txt"
    run(
        uv,
        "export",
        "--frozen",
        "--no-dev",
        "--no-hashes",
        "--no-emit-project",
        "--format",
        "requirements-txt",
        "--output-file",
        str(requirements),
    )
    lines = [
        line
        for line in requirements.read_text().splitlines()
        if line and not line.startswith(("#", " ")) and line.split("==")[0].strip() not in PROVIDED
    ]
    requirements.write_text("\n".join(lines) + "\n")
    run(
        uv,
        "pip",
        "install",
        "--quiet",
        "--requirement",
        str(requirements),
        "--target",
        str(OUT),
        "--python-platform",
        "x86_64-manylinux_2_28",
        "--python-version",
        "3.12",
        "--only-binary",
        ":all:",
    )
    shutil.copytree(ROOT / "src" / "crewops", OUT / "crewops")
    shutil.copytree(ROOT / "web", OUT / "web")
    shutil.copytree(ROOT / "data" / "seed", OUT / "data" / "seed")
    scorecard = ROOT / "docs" / "scorecard.json"
    if scorecard.is_file():
        (OUT / "docs").mkdir()
        shutil.copy(scorecard, OUT / "docs" / "scorecard.json")
    for cache in OUT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"bundle ready: {OUT} ({size:.0f} MB unzipped)")


if __name__ == "__main__":
    main()
