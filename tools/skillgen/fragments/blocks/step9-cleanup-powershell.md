```powershell
Set-Content -Path graphify-out\.graphify_step9_cleanup.py -Encoding utf8 -Value @'
import json
from pathlib import Path
from datetime import datetime, timezone
from graphify.detect import save_manifest

# Save manifest for --update
detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding="utf-8"))
# In --update mode, 'all_files' carries the full corpus; 'files' is the changed
# subset. Full-rebuild mode populates only 'files', so the fallback handles that.
# root= relativizes the manifest keys to the scan root (same base as the build),
# so the on-disk manifest is portable across clones/machines and a later --update
# matches cached files instead of missing every one (#1417).
save_manifest(detect.get('all_files') or detect['files'], root='INPUT_PATH')

# Update cumulative cost tracker
extract = json.loads(Path('graphify-out/.graphify_extract.json').read_text(encoding="utf-8"))
input_tok = extract.get('input_tokens', 0)
output_tok = extract.get('output_tokens', 0)

cost_path = Path('graphify-out/cost.json')
if cost_path.exists():
    cost = json.loads(cost_path.read_text(encoding="utf-8"))
else:
    cost = {'runs': [], 'total_input_tokens': 0, 'total_output_tokens': 0}

cost['runs'].append({
    'date': datetime.now(timezone.utc).isoformat(),
    'input_tokens': input_tok,
    'output_tokens': output_tok,
    'files': detect.get('total_files', 0),
})
cost['total_input_tokens'] += input_tok
cost['total_output_tokens'] += output_tok
cost_path.write_text(json.dumps(cost, indent=2, ensure_ascii=False), encoding="utf-8")

print(f'This run: {input_tok:,} input tokens, {output_tok:,} output tokens')
print(f'All time: {cost["total_input_tokens"]:,} input, {cost["total_output_tokens"]:,} output ({len(cost["runs"])} runs)')
'@
& (Get-Content graphify-out\.graphify_python) graphify-out\.graphify_step9_cleanup.py
Remove-Item graphify-out\.graphify_step9_cleanup.py -Force -ErrorAction SilentlyContinue
Remove-Item graphify-out\.graphify_detect.json, graphify-out\.graphify_extract.json, graphify-out\.graphify_ast.json, graphify-out\.graphify_semantic.json, graphify-out\.graphify_analysis.json -Force -ErrorAction SilentlyContinue
Get-ChildItem graphify-out -Filter '.graphify_chunk_*.json' | Remove-Item -Force
Remove-Item graphify-out\.needs_update -Force -ErrorAction SilentlyContinue
```
