"""Tests for scripts/build_graspologic_native.py, the graspologic-native
source-build + supply-chain-audit helper.

Only the pure static_analysis(src_root) -> dict[str, list[str]] function is
exercised against small fixture Rust source trees written under tmp_path; no
git clone, no network access, and no Rust/maturin toolchain is required, so
this file runs under the default `pytest` invocation. The clone+build path
(main()) is covered by a single integration test gated behind an opt-in env
var, mirroring the "needs external toolchain" carve-out documented in the
script's own docstring.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# scripts/ is not a package (excluded from pytest's norecursedirs) and is not
# on sys.path; put the scripts dir itself on sys.path so
# build_graspologic_native imports as a top-level module, mirroring
# tests/test_graphify_inspect.py's SCRIPTS_DIR insertion.
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_graspologic_native  # noqa: E402

SCRIPT_PATH = SCRIPTS_DIR / "build_graspologic_native.py"

# One deliberately isolated matching line per AUDIT_PATTERNS key: each line
# trips exactly its own pattern and none of the others, so per-pattern tests
# don't get false-positive corroboration from a neighboring pattern.
MATCHING_LINE_BY_PATTERN = {
    "unsafe block": "unsafe { do_thing(); }",
    "process execution": 'let out = Command::new("ls").output().unwrap();',
    "network access": 'let stream = TcpStream::connect("127.0.0.1:80")?;',
    "env var access": 'let home = std::env::var("HOME").unwrap();',
    "filesystem write": 'let f = File::create("out.bin").unwrap();',
    "embedded binary/string blob": 'const DATA: &[u8] = include_bytes!("blob.bin");',
    "raw memory": "let x = value.as_ptr() as *const u8;",
}


def _write_rust_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write {relative_path: contents} under tmp_path, creating parent dirs."""
    for rel_path, contents in files.items():
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(contents, encoding="utf-8")
    return tmp_path


# Requirement: the build script's static_analysis() must flag every one of
# its documented supply-chain red-flag patterns (unsafe blocks, process
# execution, network access, env var reads, filesystem writes, embedded
# binary/string blobs, raw memory ops) when a matching line appears in a .rs
# file, recording the file-relative path, line number, and stripped line text
# so a human reviewer can triage the hit.
class TestStaticAnalysisAuditPatterns:
    @pytest.mark.parametrize("pattern_name", sorted(build_graspologic_native.AUDIT_PATTERNS))
    def test_pattern_triggers_on_matching_line(self, tmp_path, pattern_name):
        line = MATCHING_LINE_BY_PATTERN[pattern_name]
        assert set(MATCHING_LINE_BY_PATTERN) == set(build_graspologic_native.AUDIT_PATTERNS), (
            "fixture map must cover every AUDIT_PATTERNS key"
        )
        src_root = _write_rust_tree(tmp_path, {"src/lib.rs": f"fn f() {{\n    {line}\n}}\n"})

        findings = build_graspologic_native.static_analysis(src_root)

        assert findings[pattern_name] == [f"src{os.sep}lib.rs:2: {line}"]
        # no other audited pattern should have picked up this isolated line
        for other_name, hits in findings.items():
            if other_name in ("build.rs present", pattern_name):
                continue
            assert hits == [], f"unexpected cross-match of {other_name!r} on {line!r}"

    def test_multiple_hits_of_same_pattern_are_all_recorded_in_order(self, tmp_path):
        src_root = _write_rust_tree(
            tmp_path,
            {"src/lib.rs": "unsafe { a(); }\nfn safe() {}\nunsafe { b(); }\n"},
        )

        findings = build_graspologic_native.static_analysis(src_root)

        assert findings["unsafe block"] == [
            f"src{os.sep}lib.rs:1: unsafe {{ a(); }}",
            f"src{os.sep}lib.rs:3: unsafe {{ b(); }}",
        ]


# Requirement: source with none of the audited red-flag patterns must report
# zero hits across the board, so the audit report is quiet (not noisy with
# empty findings) on ordinary, unremarkable Rust code.
class TestStaticAnalysisCleanSource:
    def test_clean_source_produces_no_hits(self, tmp_path):
        src_root = _write_rust_tree(
            tmp_path,
            {
                "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n",
                "src/util.rs": "pub struct Point { pub x: f64, pub y: f64 }\n",
            },
        )

        findings = build_graspologic_native.static_analysis(src_root)

        assert all(hits == [] for hits in findings.values())
        assert set(findings) == set(build_graspologic_native.AUDIT_PATTERNS)


# Requirement: build artifacts under a target/ directory (Cargo's build
# output, which can itself embed vendored/generated .rs files) must never be
# scanned as if they were reviewed source, otherwise the audit could be
# defeated by planting a flagged pattern only in generated output while the
# reviewed source tree looks clean.
class TestStaticAnalysisTargetDirExclusion:
    def test_rs_files_under_target_dir_are_excluded(self, tmp_path):
        src_root = _write_rust_tree(
            tmp_path,
            {
                "src/lib.rs": "pub fn ok() {}\n",
                "target/debug/build/generated.rs": 'let out = Command::new("ls").output().unwrap();\n',
                "target/release/deps/vendored.rs": "unsafe { danger(); }\n",
            },
        )

        findings = build_graspologic_native.static_analysis(src_root)

        assert findings["process execution"] == []
        assert findings["unsafe block"] == []

    def test_nested_target_dir_anywhere_in_path_is_excluded(self, tmp_path):
        src_root = _write_rust_tree(
            tmp_path,
            {
                "packages/pyo3/target/wheels/scratch.rs": "unsafe { danger(); }\n",
                "packages/pyo3/src/lib.rs": "pub fn ok() {}\n",
            },
        )

        findings = build_graspologic_native.static_analysis(src_root)

        assert findings["unsafe block"] == []


# Requirement: presence of a build.rs (a Cargo hook that executes arbitrary
# code at build time, before any dependency audit gate can intervene) must be
# surfaced as its own "build.rs present" finding, so a reviewer sees it even
# though it is synthesized rather than derived from AUDIT_PATTERNS regex scan.
class TestStaticAnalysisBuildScriptDetection:
    def test_top_level_build_rs_is_detected(self, tmp_path):
        src_root = _write_rust_tree(
            tmp_path,
            {
                "build.rs": 'fn main() { println!("cargo:rerun-if-changed=src"); }\n',
                "src/lib.rs": "pub fn ok() {}\n",
            },
        )

        findings = build_graspologic_native.static_analysis(src_root)

        assert findings["build.rs present"] == ["build.rs"]

    def test_no_build_rs_omits_the_key_from_the_default_empty_dict(self, tmp_path):
        src_root = _write_rust_tree(tmp_path, {"src/lib.rs": "pub fn ok() {}\n"})

        findings = build_graspologic_native.static_analysis(src_root)

        # "build.rs present" is only synthesized into findings when at least
        # one build.rs is found; absent that, it is simply not a key.
        assert "build.rs present" not in findings

    def test_build_rs_under_target_dir_is_not_detected(self, tmp_path):
        src_root = _write_rust_tree(
            tmp_path,
            {
                "target/debug/build/foo-abc123/build.rs": 'fn main() {}\n',
                "src/lib.rs": "pub fn ok() {}\n",
            },
        )

        findings = build_graspologic_native.static_analysis(src_root)

        assert "build.rs present" not in findings


# Requirement: the full clone-checkout-audit-build-manifest pipeline (main())
# must produce a wheel and a matching sha256 manifest in vendor/graspologic-native/
# when run against the real pinned upstream tag. This needs git, a Rust
# toolchain, maturin, and network access to GitHub, so it is opt-in only
# (GRAPHIFY_RUN_BUILD_INTEGRATION=1) and skipped by default so default `pytest`
# runs stay hermetic and fast.
class TestBuildIntegration:
    @pytest.mark.skipif(
        os.environ.get("GRAPHIFY_RUN_BUILD_INTEGRATION") != "1",
        reason=(
            "requires git, a Rust toolchain, maturin, and network access to "
            "github.com/graspologic-org/graspologic-native; set "
            "GRAPHIFY_RUN_BUILD_INTEGRATION=1 to opt in"
        ),
    )
    def test_full_clone_and_build_produces_wheel_and_manifest(self):
        out_dir = REPO_ROOT / "vendor" / "graspologic-native"
        before = set(out_dir.glob("*.whl")) if out_dir.exists() else set()

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=1800,
        )

        assert result.returncode == 0, result.stderr
        after = set(out_dir.glob("*.whl"))
        new_wheels = after - before
        assert new_wheels, "expected a new wheel in vendor/graspologic-native/"
        wheel = next(iter(new_wheels))
        manifest = wheel.parent / f"{wheel.stem}.manifest.json"
        assert manifest.exists()
