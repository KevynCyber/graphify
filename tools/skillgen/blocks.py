"""Per-platform resolution of ``@@BLOCK_<NAME>@@`` markers in core.md.

Mirrors the existing ``@@INSTALL@@`` mechanism (``_read_fragment(f"shell/
{platform.shell}.md")`` in gen.py): each ``@@BLOCK_<NAME>@@`` token resolves to
``fragments/blocks/<name-lowercased-dash-separated>-<shell>.md``. Split into its
own module (rather than added to gen.py) solely because gen.py is already at
its grandfathered file-structure-check line budget.
"""
from __future__ import annotations

import re

_BLOCK_MARKER_RE = re.compile(r"@@BLOCK_(\w+)@@")


def resolve_blocks(template: str, shell: str) -> str:
    """Substitute every ``@@BLOCK_<NAME>@@`` marker with its shell-specific fragment.

    A marker whose fragment is missing for this shell is left as the literal
    token, so gen.py's generic ``"@@" in body`` backstop raises loudly instead of
    a bash-only block silently shipping to a non-posix host.
    """
    # Local import: gen.py imports this module at load time, so importing gen
    # here at module scope would be circular. By the time resolve_blocks() is
    # actually called (from gen._render_core), gen is fully loaded.
    from tools.skillgen import gen

    def _sub(match: re.Match[str]) -> str:
        slug = match.group(1).lower().replace("_", "-")
        rel = f"blocks/{slug}-{shell}.md"
        if not (gen.FRAGMENTS_DIR / rel).exists():
            return match.group(0)
        return gen._read_fragment(rel).rstrip("\n")

    return _BLOCK_MARKER_RE.sub(_sub, template)
