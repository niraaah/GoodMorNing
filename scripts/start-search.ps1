$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$searchPython=Join-Path $projectRoot '.venv-search/Scripts/python.exe'
if(-not(Test-Path -LiteralPath $searchPython)){Write-Output 'Search is not installed. Run scripts/setup-search.ps1.';exit 0}
$keyPath=Join-Path $projectRoot 'data/search-service.key'
if(-not(Test-Path -LiteralPath $keyPath)){
  throw 'Database security setup required. Run scripts/setup-postgres.ps1 first.'
}
$searchKey=(Get-Content -LiteralPath $keyPath -Raw).Trim()
try {
  $health=Invoke-RestMethod http://127.0.0.1:8788/health -Headers @{Authorization="Bearer $searchKey"} -TimeoutSec 2
  if($health.model -eq 'google/embeddinggemma-2'){Write-Output 'Goods search already running.';exit 0}
  throw 'Port 8788 belongs to another service.'
} catch [System.Net.Http.HttpRequestException] {
} catch [System.Threading.Tasks.TaskCanceledException] {
}
Remove-Variable searchKey
$logsPath=Join-Path $projectRoot 'logs'
$searchProcess=Start-Process -FilePath $searchPython -ArgumentList @('-m','uvicorn','server.goods.worker:app','--host','127.0.0.1','--port','8788') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath 'search.out.log') -RedirectStandardError (Join-Path $logsPath 'search.err.log')
$searchProcess.Id | Set-Content -LiteralPath (Join-Path $logsPath 'search.pid')
Write-Output "Goods search PID: $($searchProcess.Id)"
