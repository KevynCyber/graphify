```powershell
Set-Content -Path graphify-out\.graphify_detect.py -Encoding utf8 -Value @'
import json
from graphify.detect import detect
from pathlib import Path
result = detect(Path('INPUT_PATH'))
Path('graphify-out/.graphify_detect.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
'@
& (Get-Content graphify-out\.graphify_python) graphify-out\.graphify_detect.py
Remove-Item graphify-out\.graphify_detect.py -Force -ErrorAction SilentlyContinue
```
