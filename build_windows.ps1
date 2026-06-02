$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[build]"

if (Test-Path "build") { Remove-Item -LiteralPath "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item -LiteralPath "dist" -Recurse -Force }

.\.venv\Scripts\python.exe -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "LiveInTheMoment" `
  --collect-all PIL `
  --collect-all cryptography `
  --paths "src" `
  "gui_launcher.py"

Write-Host "Built: $root\dist\LiveInTheMoment.exe"
