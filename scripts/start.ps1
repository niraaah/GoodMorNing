param([int]$Port = 8787, [switch]$Foreground)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment missing.' }
if (-not (Test-Path -LiteralPath 'app\build\web\index.html')) { Write-Output 'Starting API only. Use the GitHub Pages frontend, or run scripts\build.ps1 for local UI.' }
$logsPath = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logsPath -Force | Out-Null
# Both servers use PostgreSQL in Docker (scripts\setup-postgres.ps1).
. (Join-Path $PSScriptRoot 'docker-path.ps1')
docker start goodmorning-postgres | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL is not available. Start Docker Desktop, then run scripts\setup-postgres.ps1.' }
& (Join-Path $PSScriptRoot 'start-search.ps1')
if ($Foreground) {
  & $pythonPath -m uvicorn server.app:app --host 127.0.0.1 --port $Port
  exit $LASTEXITCODE
}
try {
  $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
  if ($health.engine -eq 'sam2-gaussian') { Write-Output "Already running: http://127.0.0.1:$Port"; exit 0 }
  throw "Port $Port is occupied by another service."
} catch [System.Net.Http.HttpRequestException] {
} catch [System.Threading.Tasks.TaskCanceledException] {
}
$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','server.app:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath 'server.out.log') -RedirectStandardError (Join-Path $logsPath 'server.err.log')
$serverProcess.Id | Set-Content -LiteralPath (Join-Path $logsPath 'server.pid')
Write-Output "Server PID: $($serverProcess.Id)"
Write-Output "http://127.0.0.1:$Port"
