# Refresh this process's PATH after per-user Docker Desktop installation.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  $dockerCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin'),
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin')
  )
  $dockerBin = $dockerCandidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'docker.exe') } | Select-Object -First 1
  if (-not $dockerBin) { throw 'Docker Desktop is not installed. Install Docker Desktop with the WSL 2 backend first.' }
  $env:PATH = "$dockerBin;$env:PATH"
}
