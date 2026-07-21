#!/usr/bin/env python3
"""Build and audit graspologic-native from source.

Clones the pinned upstream tag of https://github.com/graspologic-org/graspologic-native,
runs a static-analysis pass over its Rust source flagging common supply-chain red flags
(unsafe blocks, process execution, network access, env var reads, filesystem writes,
embedded binary blobs, raw memory ops, build.rs scripts), builds the wheel with maturin,
and drops the result plus an audit manifest into vendor/graspologic-native/.

A match in the static-analysis report is a triage aid, not an automatic verdict — e.g.
the upstream CLI crate's clap-based `Command::new(...)` legitimately matches the
"process execution" pattern without being one; read the surrounding line before acting
on a hit.

Usage:
    python scripts/build_graspologic_native.py [--ref v1.3.1] [--install]

Requires: git, a Rust toolchain (cargo/rustc) on PATH, and maturin (pip install maturin).

--install additionally pip-installs the built wheel into the current interpreter,
so a subsequent `pip install -e .[leiden]` sees the version constraint already
satisfied by this self-built, self-audited artifact instead of pulling the
prebuilt PyPI wheel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_URL = "https://github.com/graspologic-org/graspologic-native.git"
DEFAULT_REF = "v1.3.1"
OUT_DIR = Path(__file__).resolve().parent.parent / "vendor" / "graspologic-native"

# Patterns worth a human's attention in a supply-chain audit of Rust source.
# A match is not automatically a problem (see module docstring) — this is a
# triage aid, not a hard gate.
AUDIT_PATTERNS = {
    "unsafe block": r"\bunsafe\b",
    "process execution": r"std::process::Command|Command::new",
    "network access": r"std::net::|TcpStream|reqwest|hyper::|curl",
    "env var access": r"std::env::var|env::var_os",
    "filesystem write": r"File::create|OpenOptions::new",
    "embedded binary/string blob": r"include_bytes!|include_str!",
    "raw memory": r"transmute|from_raw|as_ptr\(\)\s*as",
}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def static_analysis(src_root: Path) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {name: [] for name in AUDIT_PATTERNS}
    build_scripts = [p for p in src_root.rglob("build.rs") if "target" not in p.parts]
    if build_scripts:
        findings["build.rs present"] = [str(p.relative_to(src_root)) for p in build_scripts]

    for rs_file in src_root.rglob("*.rs"):
        if "target" in rs_file.parts:
            continue
        text = rs_file.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            for name, pattern in AUDIT_PATTERNS.items():
                if re.search(pattern, line):
                    findings[name].append(f"{rs_file.relative_to(src_root)}:{i}: {line.strip()}")
    return findings


def print_report(findings: dict[str, list[str]]) -> None:
    print("\n=== Static analysis report ===")
    any_hits = False
    for name, hits in findings.items():
        if not hits:
            continue
        any_hits = True
        print(f"\n[{name}] {len(hits)} match(es):")
        for hit in hits:
            print(f"  {hit}")
    if not any_hits:
        print("No matches for any audited pattern.")
    print("=== End report — review matches above before trusting the build ===\n")


def build_wheel(pyo3_dir: Path) -> Path:
    run([sys.executable, "-m", "maturin", "build", "--release", "--strip"], cwd=pyo3_dir)
    wheels_dir = pyo3_dir.parent.parent / "target" / "wheels"
    wheels = sorted(wheels_dir.glob("graspologic_native-*.whl"))
    if not wheels:
        raise SystemExit(f"maturin build produced no wheel in {wheels_dir}")
    return wheels[-1]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default=DEFAULT_REF, help="git tag/commit to build (default: %(default)s)")
    parser.add_argument("--install", action="store_true", help="pip install the resulting wheel into the current interpreter after building")
    args = parser.parse_args()

    for tool in ("git", "cargo"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found on PATH — required to build from source")
    try:
        import maturin  # noqa: F401
    except ImportError:
        raise SystemExit("maturin not installed — run: pip install maturin")

    with tempfile.TemporaryDirectory(prefix="graspologic-native-src-") as tmp:
        src_root = Path(tmp) / "graspologic-native"
        run(["git", "clone", "--depth", "50", REPO_URL, str(src_root)])
        run(["git", "checkout", args.ref], cwd=src_root)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=src_root, check=True, capture_output=True, text=True
        ).stdout.strip()

        findings = static_analysis(src_root)
        print_report(findings)

        pyo3_dir = src_root / "packages" / "pyo3"
        wheel = build_wheel(pyo3_dir)

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        dest = OUT_DIR / wheel.name
        shutil.copy2(wheel, dest)
        digest = sha256_of(dest)

        manifest = {
            "source_repo": REPO_URL,
            "ref": args.ref,
            "commit": commit,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "wheel": wheel.name,
            "sha256": digest,
            "static_analysis_summary": {name: len(hits) for name, hits in findings.items()},
        }
        manifest_path = OUT_DIR / f"{wheel.stem}.manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        print(f"Wheel:    {dest}")
        print(f"sha256:   {digest}")
        print(f"Manifest: {manifest_path}")

        if args.install:
            run([sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", str(dest)])


if __name__ == "__main__":
    main()
