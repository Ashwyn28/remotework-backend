"""Build the two Lambda packages into .local/build/.

    python infra/package.py

- sync.zip: the `jobfeed` package (standard library only; boto3 comes with the Lambda runtime)
- api.zip:  the `jobapi` package plus google-auth and requests, built for Python 3.12 on arm64
- agent.zip: the `jobagent` package plus the Anthropic SDK, built the same way

Zips are reproducible: the same code gives byte-identical files, so Terraform only updates a
function when its code really changed.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".local" / "build"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
SKIP_DIRS = {"tests", "__pycache__"}
SKIP_FILES = {"devserver.py", "__main__.py"}
API_DEPENDENCIES = ["google-auth==2.62.2", "requests==2.32.5"]
AGENT_DEPENDENCIES = ["anthropic==1.17.0"]


def add_tree(archive: zipfile.ZipFile, folder: Path, base: Path) -> None:
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(base)
        if path.is_dir() or SKIP_DIRS & set(relative.parts) or path.name in SKIP_FILES or path.suffix == ".pyc":
            continue
        info = zipfile.ZipInfo(relative.as_posix(), FIXED_TIME)
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, path.read_bytes())


def build_sync() -> Path:
    target = BUILD / "sync.zip"
    with zipfile.ZipFile(target, "w") as archive:
        add_tree(archive, ROOT / "jobfeed", ROOT)
    return target


def install_for_lambda(name: str, requirements: list[str]) -> Path:
    """Wheels for Python 3.12 on arm64, the Lambda runtime, whatever this machine runs."""
    deps = BUILD / f"{name}-deps"
    shutil.rmtree(deps, ignore_errors=True)
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install", "--quiet", "--target", str(deps),
            "--platform", "manylinux2014_aarch64", "--python-version", "3.12",
            "--implementation", "cp", "--only-binary=:all:", *requirements,
        ],
        check=True,
    )
    return deps


def build_with_deps(name: str, package: str, requirements: list[str]) -> Path:
    deps = install_for_lambda(name, requirements)
    target = BUILD / f"{name}.zip"
    with zipfile.ZipFile(target, "w") as archive:
        add_tree(archive, ROOT / package, ROOT)
        add_tree(archive, deps, deps)
    return target


def build_api() -> Path:
    return build_with_deps("api", "jobapi", API_DEPENDENCIES)


def build_agent() -> Path:
    return build_with_deps("agent", "jobagent", AGENT_DEPENDENCIES)


if __name__ == "__main__":
    BUILD.mkdir(parents=True, exist_ok=True)
    for built in (build_sync(), build_api(), build_agent()):
        print(f"{built.relative_to(ROOT)}  {built.stat().st_size // 1024} KB")
