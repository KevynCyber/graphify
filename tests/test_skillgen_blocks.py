"""Tests for the per-block POSIX/PowerShell templating conversion of core.md.

core.md currently has 15 bash-only fenced code blocks that get emitted
verbatim to every rendered platform, including windows (the only platform
with shell = "powershell" in platforms.toml). This file locks in the target
behavior of the planned conversion: each of the 15 blocks becomes an
``@@BLOCK_<NAME>@@`` marker in core.md, resolved via
``tools/skillgen/fragments/blocks/<name-lowercased-dash-separated>-<shell>.md``
(the same pattern ``_read_fragment(f"shell/{platform.shell}.md")`` already
uses for the ``@@INSTALL@@`` slot).

These tests are written before the mechanism exists. Most are RED right now
because fragments/blocks/ and the @@BLOCK_*@@ markers do not exist yet
(gen.py:367 has no block-resolution step, core.md is unconverted). Two are
regression/characterization locks (ADR-0005) that currently PASS by design --
they pin already-correct behavior (the posix render, the CLI guards) so a
future change to gen.py cannot silently break it; see each docstring.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.skillgen import gen  # noqa: E402

# The 15 blocks, in the order they appear in core.md. marker is the
# @@BLOCK_<marker>@@ name; slug is the lowercased, dash-separated fragment
# basename (tools/skillgen/fragments/blocks/<slug>-<shell>.md).
_BLOCKS = [
    ("DETECT", "detect"),
    ("AST_EXTRACT", "ast-extract"),
    ("SEMANTIC_FASTPATH", "semantic-fastpath"),
    ("CACHE_CHECK", "cache-check"),
    ("MERGE_CHUNKS", "merge-chunks"),
    ("SAVE_CACHE", "save-cache"),
    ("MERGE_SEMANTIC", "merge-semantic"),
    ("MERGE_AST_SEMANTIC", "merge-ast-semantic"),
    ("BUILD_GRAPH", "build-graph"),
    ("HEALTH_CHECK", "health-check"),
    ("LABEL_COMMUNITIES", "label-communities"),
    ("EXPORT_OBSIDIAN", "export-obsidian"),
    ("EXPORT_HTML", "export-html"),
    ("STEP9_CLEANUP", "step9-cleanup"),
    ("INTERPRETER_GUARD", "interpreter-guard"),
]

# Commit immediately before this block-conversion work started (worktree
# branch feat/skillgen-posix-powershell-blocks, HEAD at time of writing).
# Pinned so the posix regression baseline below cannot itself drift when
# later commits land on this branch.
_PRE_CONVERSION_SHA = "11ca5ef18ae3d374eff72ec7a9962972c0d02fa9"


def test_core_template_carries_all_15_block_markers():
    """Requirement: each of the 15 bash-only blocks in core.md (Step 2 detect,
    Part A AST extract, Part B fast-path/cache-check/merge/save-cache, Part C
    merge, Step 4 build-graph, Step 4.5 health-check, Step 5 label, Step 6
    obsidian/html, Step 9 cleanup, interpreter guard) must become an
    @@BLOCK_<NAME>@@ slot, so gen.py can resolve a shell-specific fragment for
    any host whose platforms.toml shell != posix, instead of shipping
    bash-only code verbatim to a PowerShell-only host (currently windows).
    """
    template = gen._read_fragment("core/core.md")
    missing = [name for name, _ in _BLOCKS if f"@@BLOCK_{name}@@" not in template]
    assert missing == [], f"core.md is missing block markers: {missing}"


def test_all_15_block_fragments_exist_for_both_shells():
    """Requirement: every @@BLOCK_<NAME>@@ marker must have a resolvable
    fragment for both shells skillgen supports (posix, powershell) under
    tools/skillgen/fragments/blocks/, named <slug>-<shell>.md, so every
    platform in platforms.toml (posix or powershell) can render every block.
    """
    blocks_dir = gen.FRAGMENTS_DIR / "blocks"
    missing = [
        f"{slug}-{shell}.md"
        for _, slug in _BLOCKS
        for shell in ("posix", "powershell")
        if not (blocks_dir / f"{slug}-{shell}.md").exists()
    ]
    assert missing == [], f"missing block fragment files under fragments/blocks/: {missing}"


def test_windows_core_has_no_leftover_bash_fences_after_block_conversion():
    """Requirement: the windows skill body (the only platform with
    shell = "powershell") must not contain bash-only code fences once the 15
    blocks are converted -- a PowerShell-only host cannot execute
    `$(cat ...)`, `mkdir -p`, or POSIX `-c` shell invocations.

    Exactly one ```bash fence is expected to remain: the query-stub
    (fragments/query-stub/default.md, the @@QUERY_STUB@@ slot) prints a bare
    `graphify query "<question>"` CLI invocation, which is shell-agnostic
    prose and is a separate, pre-existing slot mechanism outside the scope of
    this 15-block conversion.
    """
    platforms = gen.load_platforms()
    core = gen.render_all(platforms, only="windows")[0].content
    bash_fence_lines = [line for line in core.splitlines() if line.strip() == "```bash"]
    assert len(bash_fence_lines) == 1, (
        f"expected exactly 1 leftover ```bash fence (the query-stub CLI example), "
        f"found {len(bash_fence_lines)}"
    )


def test_windows_build_graph_uses_new_item_not_mkdir_p():
    """Requirement: Step 4's leading `mkdir -p graphify-out` is POSIX-only
    syntax and must not ship to the PowerShell-only windows host; its
    PowerShell equivalent uses `New-Item`.
    """
    platforms = gen.load_platforms()
    windows_core = gen.render_all(platforms, only="windows")[0].content
    assert "mkdir -p graphify-out" not in windows_core


def test_windows_ast_extract_wraps_extract_call_in_main_guard():
    """Requirement: the PowerShell-rendered AST_EXTRACT block must wrap the
    `extract()` call in `if __name__ == "__main__":` -- Windows'
    ProcessPoolExecutor uses spawn (not fork), which re-imports the `-c`
    script in each worker process; without the guard, extract() re-runs
    inside every worker instead of only the parent, corrupting/duplicating
    the multiprocessing work.
    """
    platforms = gen.load_platforms()
    windows_core = gen.render_all(platforms, only="windows")[0].content
    assert 'if __name__ == "__main__":' in windows_core


def test_posix_core_render_matches_pinned_pre_conversion_baseline():
    """Requirement: converting core.md's 15 blocks to the @@BLOCK_<NAME>@@
    slot mechanism must not change what a POSIX host (shell = "posix", e.g.
    claude, codex) actually receives -- the posix fragment content must be
    byte-identical to the current bash blocks. Pins the exact pre-conversion
    rendered skill body (git blob at the commit immediately before this
    conversion work) as the regression baseline every future posix render
    must still reproduce byte for byte, with one pre-approved exception: the
    stray `rm -f` prose line right after MERGE_SEMANTIC was deliberately
    reworded to platform-neutral prose (it is not itself a 16th marker, so it
    renders identically on both shells) -- that specific wording change was
    part of the original conversion design, not drift. Everything else is
    still a hard characterization lock (ADR-0005).
    """
    platforms = gen.load_platforms()
    old_line = (
        "Clean up temp files: `rm -f graphify-out/.graphify_cached.json "
        "graphify-out/.graphify_uncached.txt graphify-out/.graphify_semantic_new.json`"
    )
    new_line = (
        "Clean up temp files `graphify-out/.graphify_cached.json`, "
        "`graphify-out/.graphify_uncached.txt`, `graphify-out/.graphify_semantic_new.json`."
    )
    for key, artifact_path in (("claude", "graphify/skill.md"), ("codex", "graphify/skill-codex.md")):
        baseline = gen._git_show(f"{_PRE_CONVERSION_SHA}:{artifact_path}")
        assert old_line in baseline, f"[{key}] pinned baseline no longer contains the expected pre-reword line"
        baseline = baseline.replace(old_line, new_line)
        rendered = gen.render_all(platforms, only=key)[0].content
        assert rendered == baseline, f"[{key}] posix render drifted from the pre-conversion baseline"


def test_cli_flags_still_pass_after_conversion():
    """Requirement: skillgen's existing anti-drift CLI flags (--check,
    --audit-coverage, --schema-singleton, --monolith-roundtrip,
    --always-on-roundtrip) must keep passing once the block conversion lands
    -- none of them may be broken by the new @@BLOCK_<NAME>@@ mechanism.
    Currently green by design (nothing has changed yet); this is a
    regression guard for the conversion still to come.
    """
    for flag in (
        "--check",
        "--audit-coverage",
        "--schema-singleton",
        "--monolith-roundtrip",
        "--always-on-roundtrip",
    ):
        assert gen.main([flag]) == 0, f"gen.main([{flag!r}]) did not exit 0"


def test_render_raises_on_unresolved_marker_instead_of_leaking_literal_token(monkeypatch):
    """Requirement: if a @@BLOCK_<NAME>@@ marker is present in core.md but its
    corresponding fragment file is missing, rendering must fail loudly
    (raise) rather than silently emit the literal @@BLOCK_<NAME>@@ token into
    the generated, committed skill body. Simulates the missing-fragment case
    by injecting an unresolvable marker into the core template; this already
    passes today via _render_core's existing generic unfilled-slot check
    (gen.py: `if "@@" in body: raise ValueError(...)`) -- the future
    block-substitution step must route through that same body string rather
    than special-casing missing blocks away.
    """
    platforms = gen.load_platforms()
    original_read_fragment = gen._read_fragment

    def fake_read_fragment(rel):
        text = original_read_fragment(rel)
        if rel == "core/core.md":
            text += "\n@@BLOCK_DOES_NOT_EXIST@@\n"
        return text

    monkeypatch.setattr(gen, "_read_fragment", fake_read_fragment)
    with pytest.raises(ValueError, match="BLOCK_DOES_NOT_EXIST"):
        gen._render_core(platforms["claude"])
