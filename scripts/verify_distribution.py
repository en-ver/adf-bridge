"""Verify built artifacts, including an import from a clean wheel installation."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "dist"
REQUIRED_WHEEL_FILES = {
    "adf_bridge/data/adf-schema.json",
    "adf_bridge/data/schema-provenance.json",
    "adf_bridge/py.typed",
    "adf_bridge/data/THIRD_PARTY_NOTICES.md",
}
REQUIRED_SDIST_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/api.md",
    "docs/diagnostics.md",
    "docs/index.md",
    "docs/schema-and-security.md",
    "docs/support-matrix.md",
}
REQUIRED_WHEEL_METADATA_LINKS = {
    "https://github.com/en-ver/adf-bridge/blob/main/docs/support-matrix.md",
    "https://github.com/en-ver/adf-bridge/blob/main/docs/diagnostics.md",
    "https://github.com/en-ver/adf-bridge/blob/main/CONTRIBUTING.md",
    "https://github.com/en-ver/adf-bridge/blob/main/THIRD_PARTY_NOTICES.md",
}
README_RELATIVE_LINKS = {
    "](docs/support-matrix.md)",
    "](docs/diagnostics.md)",
    "](CONTRIBUTING.md)",
    "](THIRD_PARTY_NOTICES.md)",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    dist = parser.parse_args().dist
    wheels = sorted(dist.glob("adf_bridge-*.whl"))
    sdists = sorted(dist.glob("adf_bridge-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("expected exactly one wheel and one sdist in --dist")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        missing = REQUIRED_WHEEL_FILES - names
        if missing:
            raise SystemExit(f"wheel is missing package files: {sorted(missing)}")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            raise SystemExit("wheel is missing the project MIT license")
        if not any(
            name.endswith(".dist-info/licenses/THIRD_PARTY_NOTICES.md")
            for name in names
        ):
            raise SystemExit("wheel is missing third-party license notices")
        wheel_metadata = next(
            name for name in names if name.endswith(".dist-info/WHEEL")
        )
        wheel_details = archive.read(wheel_metadata).decode("utf-8")
        if (
            "Root-Is-Purelib: true" not in wheel_details
            or "Tag: py3-none-any" not in wheel_details
        ):
            raise SystemExit("wheel is not a pure Python py3-none-any wheel")
        project_metadata = next(
            name for name in names if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(project_metadata).decode("utf-8")
        if "Requires-Python: >=3.11" not in metadata:
            raise SystemExit("wheel metadata does not require Python >=3.11")
        missing_links = {
            link for link in REQUIRED_WHEEL_METADATA_LINKS if link not in metadata
        }
        if missing_links:
            raise SystemExit(
                "wheel metadata is missing absolute documentation links: "
                f"{sorted(missing_links)}"
            )
        relative_links = sorted(
            link for link in README_RELATIVE_LINKS if link in metadata
        )
        if relative_links:
            raise SystemExit(
                f"wheel metadata retains README-relative links: {relative_links}"
            )
    with tarfile.open(sdists[0]) as archive:
        names = set(archive.getnames())
        if not any(
            name.endswith("src/adf_bridge/data/adf-schema.json") for name in names
        ):
            raise SystemExit("sdist is missing the bundled schema")
        missing_docs = sorted(
            required
            for required in REQUIRED_SDIST_FILES
            if not any(name.endswith(f"/{required}") for name in names)
        )
        if missing_docs:
            raise SystemExit(f"sdist is missing required documentation: {missing_docs}")

    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required for the clean-wheel smoke check")
    with tempfile.TemporaryDirectory(prefix="adf-bridge-wheel-") as temporary:
        environment = Path(temporary) / "venv"
        python = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run([uv, "venv", "--python", "3.11", str(environment)], check=True)
        subprocess.run(
            [uv, "pip", "install", "--python", str(python), str(wheel)], check=True
        )
        subprocess.run(
            [
                str(python),
                "-c",
                (
                    "from adf_bridge import validate_adf; "
                    "validate_adf({'type': 'doc', 'version': 1, 'content': []})"
                ),
            ],
            check=True,
            cwd=temporary,
        )


if __name__ == "__main__":
    main()
