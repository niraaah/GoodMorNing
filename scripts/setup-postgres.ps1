# PostgreSQL 17 + pgvector for GoodMorNing in Docker Desktop.
# Data lives in the Docker volume goodmorning-pgdata. The generated password stays in
# data/postgres.key (ignored by Git) and reaches the container as a read-only file.
param([int]$Port = 55432)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
. (Join-Path $PSScriptRoot 'docker-path.ps1')
$image = 'pgvector/pgvector:0.8.7-pg17'
$name = 'goodmorning-postgres'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment missing. Run scripts\setup.ps1 first.' }
docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running. Start it and retry.' }
New-Item -ItemType Directory -Path data -Force | Out-Null
$keyPath = Join-Path $projectRoot 'data\postgres.key'
if (-not (Test-Path -LiteralPath $keyPath)) {
  & $pythonPath -c "import pathlib, secrets; pathlib.Path('data/postgres.key').write_text(secrets.token_urlsafe(32), encoding='utf-8')"
  if ($LASTEXITCODE -ne 0) { throw 'Could not create the database password file.' }
}
$existing = docker ps -a --filter "name=^${name}$" --format '{{.Names}}'
if (-not $existing) {
  docker run -d --name $name --restart unless-stopped -p "127.0.0.1:${Port}:5432" `
    -e POSTGRES_USER=goodmorning -e POSTGRES_DB=goodmorning `
    -e POSTGRES_PASSWORD_FILE=/run/goodmorning/postgres.key `
    -v "${keyPath}:/run/goodmorning/postgres.key:ro" `
    -v goodmorning-pgdata:/var/lib/postgresql/data $image | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL container could not start.' }
} else {
  docker start $name | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL container could not start.' }
}
$ready = $false
for ($i = 0; $i -lt 60 -and -not $ready; $i++) {
  docker exec $name pg_isready -U goodmorning -d goodmorning -h 127.0.0.1 | Out-Null
  $ready = $LASTEXITCODE -eq 0
  if (-not $ready) { Start-Sleep -Seconds 1 }
}
if (-not $ready) { throw 'PostgreSQL did not become ready.' }
$env:GOODMORNING_DATABASE_PORT = "$Port"
& $pythonPath -c 'from server.db import initialize; initialize()'
if ($LASTEXITCODE -ne 0) { throw 'Database tables could not be created.' }
Write-Output "PostgreSQL ready: 127.0.0.1:$Port, container $name, volume goodmorning-pgdata."
if (Test-Path -LiteralPath 'data\goodmorning.sqlite3') {
  Write-Output 'Existing SQLite data found. Stop the servers, then run: .\.venv\Scripts\python.exe scripts\migrate_postgres.py --apply'
}
