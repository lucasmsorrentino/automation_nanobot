# Sincroniza RAG store local -> G: e grava MANIFEST.json no G: para o
# outro PC saber que ha versao nova.
#
# Use depois de qualquer operacao que modifica o RAG/Neo4j (re-ingest,
# re-seed, enrich, ingest --ocr-only, etc.) -- protocolo do CLAUDE.md.

$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\Lucas\Documents\automation\automation_nanobot"
$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$gDriveStore = "G:\Meu Drive\ufpr_rag\store"

# Le RAG_STORE_DIR do .env (mesmo modo que ufpr_automation usa)
$dotEnv = Join-Path $projectRoot "ufpr_automation\.env"
$ragStoreDir = (Get-Content $dotEnv | Where-Object { $_ -match "^RAG_STORE_DIR=" } | Select-Object -First 1) -replace "^RAG_STORE_DIR=", ""
$ragStoreDir = $ragStoreDir.Trim().TrimEnd("/").Replace("/", "\")

if (-not (Test-Path $ragStoreDir)) {
    Write-Error "RAG_STORE_DIR nao existe: $ragStoreDir"
    exit 1
}
if (-not (Test-Path "G:\")) {
    Write-Error "Drive G: nao montado. Verifique se Google Drive Desktop esta rodando."
    exit 1
}

$localLance = Join-Path $ragStoreDir "ufpr.lance"
$remoteLance = Join-Path $gDriveStore "ufpr.lance"

Write-Host ""
Write-Host "==> Espelhando $localLance -> $remoteLance"
robocopy $localLance $remoteLance /MIR /COPY:DAT /R:3 /W:5 /NFL /NDL /NP | Select-Object -Last 8
$rcExit = $LASTEXITCODE
# robocopy: 0..7 = sucesso (com variantes); >=8 = erro real
if ($rcExit -ge 8) {
    Write-Error "robocopy falhou (exit=$rcExit)"
    exit 1
}

Write-Host ""
Write-Host "==> Gerando MANIFEST.json local + remoto"
$localManifest  = Join-Path $ragStoreDir "MANIFEST.json"
$remoteManifest = Join-Path $gDriveStore "MANIFEST.json"

& $venvPython (Join-Path $projectRoot "scripts\generate_manifest.py") --output $localManifest
Copy-Item $localManifest $remoteManifest -Force

Write-Host ""
Write-Host "OK - sync local -> G: concluido."
Write-Host "    Manifest local:  $localManifest"
Write-Host "    Manifest remoto: $remoteManifest"
