$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
. (Join-Path $PSScriptRoot 'docker-path.ps1')
foreach($image in @('goodmorning-search:local','goodmorning-crawler:local','goodmorning-gateway:local','goodmorning-network-guard:local')){
  docker image inspect $image *> $null
  if($LASTEXITCODE -ne 0){throw 'Search container images missing. Run scripts/setup-search.ps1.'}
}
# Only migrate an old native worker after all replacement images exist.
$legacyPid=Join-Path $projectRoot 'logs/search.pid'
if(Test-Path -LiteralPath $legacyPid){
  $legacyId=[int](Get-Content -LiteralPath $legacyPid)
  if(Get-CimInstance Win32_Process -Filter "ProcessId=$legacyId"){
    & (Join-Path $PSScriptRoot 'stop.ps1') -SearchOnly
  }
  Remove-Item -LiteralPath $legacyPid
}
& '.venv/Scripts/python.exe' scripts/search_sandbox.py start
if($LASTEXITCODE -ne 0){throw 'Isolated search startup failed. No native fallback is allowed.'}
