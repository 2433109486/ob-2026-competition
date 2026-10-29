<#
.SYNOPSIS
  Start a local seekdb 1.4 server for the SeekBase demo (Windows).
.DESCRIPTION
  seekdb embedded mode is not supported on Windows, so the app uses server
  mode. Point SEEKDB_EXE or -SeekdbExe at a seekdb 1.4 win64 executable, or
  place it under vendor\seekdb\seekdb.exe. The first bootstrap can take 1-2
  minutes; the script waits for the SQL port.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\start-seekdb.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\start-seekdb.ps1 -SeekdbExe C:\seekdb\seekdb.exe
#>
param(
  [string]$SeekdbExe = $env:SEEKDB_EXE,
  [int]$Port = 2881,
  [string]$BaseDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $BaseDir) { $BaseDir = Join-Path $Root "runtime\seekdb-server" }
New-Item -ItemType Directory -Force -Path $BaseDir | Out-Null

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "[seekdb] port $Port is already listening (pid $($existing.OwningProcess))." -ForegroundColor Green
  exit 0
}

if (-not $SeekdbExe) {
  $candidates = @(
    (Join-Path $Root "vendor\seekdb\seekdb.exe"),
    (Join-Path $Root "seekdb\seekdb.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { $SeekdbExe = $candidate; break }
  }
}
if (-not $SeekdbExe) {
  $cmd = Get-Command seekdb.exe -ErrorAction SilentlyContinue
  if ($cmd) { $SeekdbExe = $cmd.Source }
}
if (-not $SeekdbExe -or -not (Test-Path $SeekdbExe)) {
  Write-Host "[seekdb] executable not found." -ForegroundColor Red
  Write-Host "  1. Download seekdb 1.4 win64 from https://github.com/oceanbase/seekdb/releases"
  Write-Host "  2. Unzip it under vendor\seekdb\ or set SEEKDB_EXE."
  Write-Host "  3. Re-run this script."
  exit 1
}

Write-Host "[seekdb] exe: $SeekdbExe"
Write-Host "[seekdb] base-dir: $BaseDir"
Write-Host "[seekdb] starting on 127.0.0.1:$Port (first bootstrap may take 1-2 minutes)..."
$stdout = Join-Path $BaseDir "server.out.log"
$stderr = Join-Path $BaseDir "server.err.log"
$arguments = @(
  "--base-dir=$($BaseDir -replace '\\','/')",
  "--port=$Port",
  "--parameter", "log_disk_size=2G",
  "--parameter", "datafile_size=512M",
  "--parameter", "datafile_maxsize=4G"
)
Start-Process -FilePath $SeekdbExe -ArgumentList $arguments -WorkingDirectory $BaseDir `
  -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null

for ($i = 0; $i -lt 120; $i++) {
  Start-Sleep -Seconds 2
  $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($listening) {
    Write-Host "[seekdb] SQL port $Port is listening (pid $($listening.OwningProcess))." -ForegroundColor Green
    Write-Host "[seekdb] waiting 10s for system package bootstrap..."
    Start-Sleep -Seconds 10
    Write-Host "[seekdb] ready. App defaults: SEEKDB_HOST=127.0.0.1 SEEKDB_PORT=$Port SEEKDB_USER=root SEEKDB_PASSWORD="
    exit 0
  }
}
Write-Host "[seekdb] timed out waiting for port $Port. See $stdout and $stderr." -ForegroundColor Red
exit 1
