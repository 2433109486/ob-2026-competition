param(
  [string]$PythonExe = ".venv\Scripts\python.exe",
  [int]$Port = 7860
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path $PythonExe)) {
  $PythonExe = "python"
}

Write-Host "ResearchPulse -> http://127.0.0.1:$Port"
& $PythonExe -m uvicorn app.main:app --host 127.0.0.1 --port $Port
