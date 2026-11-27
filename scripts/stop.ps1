param([switch]$TunnelOnly,[switch]$ServerOnly,[switch]$SearchOnly)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
if(([int]$TunnelOnly.IsPresent+[int]$ServerOnly.IsPresent+[int]$SearchOnly.IsPresent) -gt 1){throw 'Choose one stop scope.'}
$names=if($SearchOnly){@('search')}elseif($TunnelOnly){@('tunnel')}elseif($ServerOnly){@('server','search')}else{@('tunnel','server','search')}
foreach($name in $names){
  $pidPath=Join-Path $projectRoot "logs\$name.pid"
  if(-not(Test-Path -LiteralPath $pidPath)){continue}
  $ownedId=[int](Get-Content -LiteralPath $pidPath)
  $process=Get-CimInstance Win32_Process -Filter "ProcessId=$ownedId"
  if(-not $process){continue}
  if(-not $process.CommandLine.Contains($projectRoot)){throw "PID $ownedId no longer belongs to this project."}
  if($name -in @('server','search') -and -not $process.CommandLine.Contains('uvicorn')){throw 'Unexpected server process.'}
  if($name -eq 'tunnel' -and -not $process.CommandLine.Contains('cloudflared')){throw 'Unexpected tunnel process.'}
  # Windows venv python.exe launches a child interpreter. Stop only descendants
  # of the validated project process, so the listener is actually released.
  $snapshot=Get-CimInstance Win32_Process
  $descendants=[System.Collections.Generic.List[int]]::new()
  $parents=@($ownedId)
  while($parents.Count -gt 0){
    $children=@($snapshot | Where-Object {$_.ParentProcessId -in $parents} | ForEach-Object {[int]$_.ProcessId})
    foreach($childId in $children){$descendants.Add($childId)}
    $parents=$children
  }
  for($index=$descendants.Count-1;$index -ge 0;$index--){Stop-Process -Id $descendants[$index] -ErrorAction SilentlyContinue}
  Stop-Process -Id $ownedId -ErrorAction SilentlyContinue
  Write-Output "Stopped $name ($ownedId)"
}

if(-not $TunnelOnly){
  & (Join-Path $projectRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'search_sandbox.py') stop
  if($LASTEXITCODE -ne 0){throw 'Isolated search shutdown failed.'}
}
