param([int]$Port=8787)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
$tunnelExe=Join-Path $projectRoot 'tools\cloudflared\cloudflared.exe'
$logsPath=Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logsPath -Force | Out-Null
if(-not(Test-Path -LiteralPath $tunnelExe)){
  New-Item -ItemType Directory -Path (Split-Path $tunnelExe -Parent) -Force | Out-Null
  Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $tunnelExe
}
$health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5
if($health.engine -ne 'sam2-gaussian'){throw 'Goodmorning server is not ready.'}
$pidPath=Join-Path $logsPath 'tunnel.pid'
if(Test-Path -LiteralPath $pidPath){
  $oldId=[int](Get-Content -LiteralPath $pidPath)
  if(Get-Process -Id $oldId -ErrorAction SilentlyContinue){throw 'Tunnel already running. Run scripts\stop.ps1 -TunnelOnly before starting another.'}
}
$errPath=Join-Path $logsPath 'tunnel.err.log'
$process=Start-Process -FilePath $tunnelExe -ArgumentList @('tunnel','--url',"http://127.0.0.1:$Port",'--protocol','http2','--no-autoupdate') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logsPath 'tunnel.out.log') -RedirectStandardError $errPath
$process.Id | Set-Content -LiteralPath $pidPath
for($attempt=0;$attempt -lt 80;$attempt++){
  Start-Sleep -Milliseconds 500
  if($process.HasExited){throw "Tunnel exited. Read $errPath"}
  $log=Get-Content -LiteralPath $errPath -Raw -ErrorAction SilentlyContinue
  if($log -match 'https://[a-z0-9-]+\.trycloudflare\.com'){
    $address=$Matches[0]
    $pagesLink='https://niraaah.github.io/GoodMorNing/'
    $pagesLink | Set-Content -LiteralPath (Join-Path $logsPath 'pages-link.txt')
    $pagesLink | Set-Content -LiteralPath (Join-Path $logsPath 'access-link.txt')
    Write-Output 'Public app connection ready. Administrator credentials are not included in links.'
    & (Join-Path $PSScriptRoot 'publish_connection.ps1') -ServerAddress $address
    exit 0
  }
}
throw "Tunnel did not return a URL yet. Read $errPath"
