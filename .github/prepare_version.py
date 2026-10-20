"""Generate the build's VERSION from a release tag, or use a local placeholder."""
import os
from pathlib import Path
import re


def build_version(ref_type: str, ref_name: str) -> str:
    if ref_type != "tag":
        return "0.0.0"
    match = re.fullmatch(r"v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))", ref_name)
    if not match:
        raise ValueError(f"Release tag must use vMAJOR.MINOR.PATCH: {ref_name}")
    version = match[1]
    if any(int(part) > 65535 for part in version.split(".")):
        raise ValueError("Each version component must fit Windows version metadata (0–65535)")
    return version


if __name__ == "__main__":
    version = build_version(os.environ.get("GITHUB_REF_TYPE", ""), os.environ.get("GITHUB_REF_NAME", ""))
    (Path(__file__).resolve().parents[1] / "VERSION").write_text(version + "\n", encoding="utf-8")
    print(f"Build version: {version}")
