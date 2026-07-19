```powershell
Set-Content -Path graphify-out\.graphify_semantic_fastpath.py -Encoding utf8 -Value @'
import json
from pathlib import Path
Path('graphify-out/.graphify_semantic.json').write_text(json.dumps({'nodes':[],'edges':[],'hyperedges':[],'input_tokens':0,'output_tokens':0}), encoding='utf-8')
'@
& (Get-Content graphify-out\.graphify_python) graphify-out\.graphify_semantic_fastpath.py
Remove-Item graphify-out\.graphify_semantic_fastpath.py -Force -ErrorAction SilentlyContinue
```
