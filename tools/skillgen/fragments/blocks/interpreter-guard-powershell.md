```powershell
if (-not (Test-Path graphify-out\.graphify_python)) {
    $GRAPHIFY_CMD = Get-Command graphify -ErrorAction SilentlyContinue
    if ($GRAPHIFY_CMD) {
        $PYTHON = Join-Path (Split-Path $GRAPHIFY_CMD.Source) "python.exe"
        if (-not (Test-Path $PYTHON)) { $PYTHON = "python" }
    } else {
        $PYTHON = "python"
    }
    New-Item -ItemType Directory -Force -Path graphify-out | Out-Null
    & $PYTHON -c "import sys; open('graphify-out/.graphify_python', 'w', encoding='utf-8').write(sys.executable)"
}
```
