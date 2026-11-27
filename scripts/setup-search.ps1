$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
if(-not(Test-Path -LiteralPath 'data/models/embeddinggemma-2/model.safetensors')){
  if(-not(Test-Path -LiteralPath '.venv-search/Scripts/python.exe')){
    & '.venv/Scripts/python.exe' -m venv .venv-search
    if($LASTEXITCODE -ne 0){throw 'Model download environment creation failed.'}
  }
  & '.venv-search/Scripts/python.exe' -m pip install 'huggingface-hub==2.4.0'
  if($LASTEXITCODE -ne 0){throw 'Model download dependency installation failed.'}
  & '.venv-search/Scripts/python.exe' scripts/setup_search.py
  if($LASTEXITCODE -ne 0){throw 'EmbeddingGemma model download failed.'}
}
if(-not(Test-Path -LiteralPath 'data/search.local.json')){
  Copy-Item -LiteralPath 'server/goods/search.example.json' -Destination 'data/search.local.json'
}
& '.venv/Scripts/python.exe' scripts/search_sandbox.py build
if($LASTEXITCODE -ne 0){throw 'Search container build failed.'}
Write-Output 'Isolated search images ready. Credentials stay in data/search.local.json; run scripts/start-search.ps1.'
