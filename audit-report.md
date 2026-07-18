# Security Audit Report

| Field | Value |
|-------|-------|
| Repository | graphify |
| Date | 2026-07-17 |
| Tech Stack | Python (uv/setuptools), PyPI package `graphifyy` |
| Scope | Prioritized/targeted (744 files; full read of install/hooks/security/llm/detect/CI/skill files, grep sweep of the rest) |
| Files Scanned | 744 tracked |

## Executive Summary

graphify is a Python knowledge-graph tool for AI coding assistants that writes install-time
config (`.claude/settings.json`, `.codebuddy/settings.json`, `.gemini/settings.json`,
`.codex/hooks.json`) and git post-commit/post-checkout hooks, and optionally sends doc/paper/
image content to a user-configured LLM provider. An independent static audit found no malware,
backdoors, obfuscated payloads, or covert data exfiltration. All install/hook writes trace to
narrow, advisory-only, fail-open behavior (PreToolUse hooks call `graphify hook-guard`, which
only prints a nudge and always exits 0; git hooks launch a detached process that calls only
graphify's own rebuild function). The PyPI name "graphifyy" and the safishamsi/Graphify-Labs
homepage mismatch were independently traced to a single author (GitHub `safishamsi` = PyPI
`captainturbo` = founder of `Graphify-Labs`, confirmed via his own `pypi/support#10098` issue
and GitHub profile) — not a supply-chain hijack. LLM egress is strictly opt-in via documented
env vars, sent only to each provider's official endpoint, with no telemetry SDK anywhere in the
codebase. The project ships its own SSRF guard (DNS-rebind-safe), prompt-injection defenses for
its LLM extraction path, and a credential-file exclusion filter in its indexer — well beyond
typical hobby-project security posture.

**Overall Risk Rating: LOW / CLEAN**

## Severity Summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 3 |
| Info | 6 |

## Malware Assessment

**Verdict: CLEAN**

Zero hits across the repo for: base64/hex-decode-then-execute, reverse-shell socket patterns,
crypto-miner/wallet indicators, keyloggers, hidden backdoor routes, time-bomb date checks, or
known-IoC domains (ngrok/pastebin/webhook.site/requestbin/etc). No `shell=True` anywhere; all
subprocess calls use list-form args. No pickle/unsafe-yaml deserialization. No hardcoded
secrets, AWS keys, or PEM blocks found in source.

## OWASP Top 10 Assessment

| ID | Category | Status | Notes |
|----|----------|--------|-------|
| A01 | Broken Access Control | PASS | `security.validate_graph_path()` blocks path traversal on the MCP server |
| A02 | Cryptographic Failures | N/A | no auth/crypto storage; SHA-256 used only for cache keys |
| A03 | Injection | PASS | no `shell=True`; list-form subprocess; `--` separator before untrusted URL args |
| A04 | Insecure Design | N/A | local CLI tool |
| A05 | Security Misconfiguration | PASS | MCP server defaults `127.0.0.1`; warns loudly + supports bearer-token gate before `0.0.0.0` |
| A06 | Vulnerable & Outdated Components | PASS (LOW note) | uv.lock pinned to pypi.org/files.pythonhosted.org only; proactive CVE floor-pins (mcp/starlette >=1.3.1 for CVE-2026-48818/CVE-2026-54283); bandit/pip-audit run in CI but `continue-on-error: true` |
| A07 | Identification & Auth Failures | PASS | optional API-key gate on MCP HTTP transport |
| A08 | Software & Data Integrity Failures | LOW | CI Actions pinned to version tags not commit SHAs; generated HTML viewers load CDN JS (jsdelivr/unpkg/d3js.org) without SRI hashes |
| A09 | Security Logging & Monitoring | N/A | adequate for a local dev tool's threat model |
| A10 | Server-Side Request Forgery | PASS | dedicated `graphify/security.py` SSRF guard: single DNS resolution + validation before connect (no rebind TOCTOU), blocks private/loopback/link-local/CGN ranges and cloud-metadata hosts, re-validates redirects |

## Dependency Analysis

### Vulnerable Packages
None found. All `uv.lock` entries resolve from the official PyPI index (`pypi.org` /
`files.pythonhosted.org`); no git/url/path source overrides (no dependency-confusion vector).

### Suspicious Packages
None found. Package name `graphifyy` (double-y) confirmed benign — see Provenance finding below.

## Behavioral Analysis

### Network Calls
- LLM provider endpoints (`graphify/llm.py:56-140`): all hardcoded to each provider's official
  API (Anthropic, Moonshot/Kimi, Ollama-local, Google Gemini, OpenAI, DeepSeek), each gated
  behind that provider's own env var (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`,
  `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`), overridable only via matching
  `*_BASE_URL` vars. No hidden third-party collector.
- URL ingest (`/graphify add <url>`, Twitter oEmbed, arXiv fetch): all routed through
  `security.safe_fetch()` / `validate_url()` (SSRF-guarded, 50MB/10MB caps, HTTPError on
  non-2xx).
- No network calls at module import time; no telemetry/analytics SDK anywhere (grep for
  posthog/sentry/mixpanel/segment/amplitude: 0 hits).

### File System Access
- `detect.py` explicitly excludes credential-store dirs/files (`.ssh`, `.gnupg`, `.aws`,
  `.gcloud`, `id_rsa*`, `.pem/.key/.p12/.pfx`, `.env`, `.netrc`, `.tfvars`, and
  keyword-matched `secret*/credential*/password*/token*` filenames) from ever entering the
  knowledge graph.
- `os.walk(..., followlinks=False)` used explicitly throughout `detect.py` (no symlink
  traversal).

### Build & Install Hooks
- `.claude/settings.json` / `.codebuddy/settings.json` PreToolUse hooks: register only
  `<exe> hook-guard search|read` (advisory nudge, fail-open, exits 0 always) — traced in
  `graphify/cli.py:306-360`.
- `.codex/hooks.json` PreToolUse hook: `<exe> hook-check`, a documented no-op.
- `.gemini/settings.json` BeforeTool hook: same advisory-nudge pattern, always returns
  `{"decision":"allow"}`.
- Git `post-commit`/`post-checkout` hooks (`graphify/hooks.py`): launch a **detached**
  background process (cross-platform, `start_new_session`/`DETACHED_PROCESS`) that calls only
  `graphify.watch._rebuild_code` — graphify's own function, not arbitrary code. Logs to
  `~/.cache/graphify-rebuild.log`. Skips during rebase/merge/cherry-pick and inside linked
  worktrees. Every install path has a matching, marker-delimited uninstall path.
- No `pull_request_target` in CI; no self-hosted runners; Actions pinned to version tags
  (LOW — not commit SHAs) from trusted publishers (actions/*, astral-sh/setup-uv,
  softprops/action-gh-release).

### Dynamic Execution
No `eval`/`exec` on untrusted input found (`detect.py`'s `_eval` hits are an unrelated
local helper function name). Tree-sitter parses ASTs only — "does not execute code from
source files" per `SECURITY.md`, independently confirmed.

## Secrets & Configuration

| Type | File | Line | Status |
|------|------|------|--------|
| AWS keys / PEM blocks / GitHub tokens | repo-wide grep | — | None found |
| Hardcoded API keys | repo-wide grep | — | None found; all provider keys read from env vars only |

## Provenance Finding (prior-review flag)

PyPI maintainer `captainturbo` == GitHub user `safishamsi` (self-filed
`pypi/support#10098` stating he owns `captainturbo` and accidentally deleted the
`graphify` PyPI name, hence `graphifyy`) == "CEO & Founder of Graphify-Labs" per his
GitHub profile (pinned repo: `Graphify-Labs/graphify`). `safishamsi/graphify` GitHub URL
redirects (repo-transfer redirect) to `Graphify-Labs/graphify`. `safishamsi
<safishamsi98@gmail.com>` is the dominant author in `git log`. **Not a supply-chain
hijack or typosquat** — one continuous author identity across GitHub personal account,
GitHub org, and PyPI account. `pyproject.toml`'s `Homepage`/`Repository` URLs are simply
stale (still point at the pre-transfer path).

## Remediation Priority

1. [LOW] Pin GitHub Actions to commit SHAs instead of version tags in `.github/workflows/*.yml`.
2. [LOW] Add SRI hashes (or vendor) the CDN JS (`mermaid`, `vis-network`, `d3.js`) in
   generated `graph.html`/callflow viewers.
3. [LOW] Remove `continue-on-error: true` from the `security-scan` CI job once the
   pre-existing bandit/pip-audit findings are cleared (already flagged in-repo as a TODO).
4. [INFO] Update `pyproject.toml` `Homepage`/`Repository`/`Issues` URLs to
   `Graphify-Labs/graphify` to remove the (benign but confusing) redirect hop.
5. [INFO / user hygiene] Do not set a cloud LLM provider key when running `/graphify` on
   folders containing sensitive non-code documents — semantic extraction sends doc/paper/
   image content (not code) to whichever provider is configured.

## Methodology & Limitations

- Static analysis via pattern matching + full manual read of install.py, hooks.py, cli.py
  (hook-guard/clone paths), security.py, llm.py, detect.py, skill.md, always_on/*.md, CI
  workflows, and SECURITY.md; grep-based sweep of the remaining 744-file tree for malware/
  OWASP/secrets patterns.
- Dependency analysis via `uv.lock` registry-source inspection (agent-workflow's
  `scan-dependencies.py` did not parse this repo's `pyproject.toml` dependency array —
  manual review substituted).
- Research sources: GitHub (`safishamsi` profile, `safishamsi/graphify` redirect target,
  `pypi/support#10098`), PyPI (`graphifyy` project page), WebSearch for provenance
  corroboration.
- Limitations: no dynamic/runtime analysis was performed (Phase 6 not opted into) — this
  audit does not observe actual network traffic or child processes spawned by
  `graphify install` at runtime; it verifies via source-code trace only. A future opt-in
  hardened-sandbox run of `graphify install` + `git commit` would give empirical
  confirmation of the traced behavior. Obfuscated code could in principle evade pattern
  matching, though the codebase's overall engineering quality and matching `SECURITY.md`
  claims make this unlikely.

## Dynamic Analysis (Phase 6 — opted in by Kev, 2026-07-17)

Ran the hardened-docker-sandbox procedure (3 phases: network-enabled local-source
install, network-none install+commit+extract observation, network-none uninstall
verification) against a throwaway git project inside a de-privileged, non-root,
cap-dropped, --rm container built from a pinned python:3.12-slim digest. Volume and
image fully torn down afterward.

**Result: CONFIRMED — runtime behavior matches the static audit with zero deviations.**

- `.claude/settings.json` after `graphify install --project` contained only the two
  documented hook-guard PreToolUse entries; a full $HOME tree diff showed no writes
  outside `.claude/`, `.git/hooks/`, `CLAUDE.md`, `.gitattributes`, `graphify-out/`,
  and `~/.cache/`.
- Git hook content matched the static source trace byte-for-byte.
- The detached post-commit rebuild spawned exactly one child process running
  `graphify.watch._rebuild_code`'s own launcher body, completed within seconds, wrote
  only to `graphify-out/` and `~/.cache/graphify-rebuild.log`, and left no lingering
  processes.
- `graphify extract .` with `--network none` and no provider API keys set failed
  immediately with a clear "no LLM API key found" error rather than attempting any
  connection — direct empirical proof that LLM egress is key-gated before any network
  call, not merely gated by network availability.
- `graphify hook uninstall` + `graphify uninstall --project` fully removed every
  artifact added (hooks, merge driver, .gitattributes line, skill tree, CLAUDE.md,
  settings.json hook entries), verified via before/after diffs and `graphify hook status`.

No deviations from the Phase 2-5 static findings were observed. Overall verdict
unchanged: **SAFE**, conditions as previously stated.
