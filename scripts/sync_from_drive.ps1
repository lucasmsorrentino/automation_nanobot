# Sincroniza RAG store G: -> local, re-seeda Neo4j a partir do RAG novo,
# regenera MANIFEST.json local e compara com o do G: para detectar drift.
#
# Use ao retomar trabalho num PC quando o outro PC modificou o RAG/Neo4j
# (ou quando voce nao tem certeza de qual e o estado atual aqui).

$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\Lucas\Documents\automation\automation_nanobot"
$venvPython  = Join-Path $projectRoot ".venv\Scripts\python.exe"
$gDriveStore = "G:\Meu Drive\ufpr_rag\store"

if (-not (Test-Path "G:\")) {
    Write-Error "Drive G: nao montado. Verifique se Google Drive Desktop esta rodando."
    exit 1
}

$dotEnv = Join-Path $projectRoot "ufpr_automation\.env"
$ragStoreDir = (Get-Content $dotEnv | Where-Object { $_ -match "^RAG_STORE_DIR=" } | Select-Object -First 1) -replace "^RAG_STORE_DIR=", ""
$ragStoreDir = $ragStoreDir.Trim().TrimEnd("/").Replace("/", "\")

if (-not (Test-Path $ragStoreDir)) {
    Write-Host "Criando RAG_STORE_DIR local: $ragStoreDir"
    New-Item -ItemType Directory -Path $ragStoreDir -Force | Out-Null
}

$localLance     = Join-Path $ragStoreDir "ufpr.lance"
$remoteLance    = Join-Path $gDriveStore "ufpr.lance"
$localManifest  = Join-Path $ragStoreDir "MANIFEST.json"
$remoteManifest = Join-Path $gDriveStore "MANIFEST.json"

# 1. Mostra info do manifest remoto (se existir)
if (Test-Path $remoteManifest) {
    $remoteInfo = Get-Content $remoteManifest -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "==> Manifest remoto (G:):"
    Write-Host "    machine:    $($remoteInfo.machine)"
    Write-Host "    timestamp:  $($remoteInfo.timestamp)"
    Write-Host "    git_sha:    $($remoteInfo.git_sha)"
    Write-Host "    lancedb:    $($remoteInfo.lancedb.total_chunks) chunks ($($remoteInfo.lancedb.store_size_mb) MB)"
    Write-Host "    neo4j:      $($remoteInfo.neo4j.total_nodes) nos / $($remoteInfo.neo4j.total_relationships) relacoes"
} else {
    Write-Host "==> Sem MANIFEST.json remoto. Sync sera 'best effort'."
}

# 2. robocopy G: -> local
Write-Host ""
Write-Host "==> Espelhando $remoteLance -> $localLance"
robocopy $remoteLance $localLance /MIR /COPY:DAT /R:3 /W:5 /NFL /NDL /NP | Select-Object -Last 8
$rcExit = $LASTEXITCODE
if ($rcExit -ge 8) {
    Write-Error "robocopy falhou (exit=$rcExit)"
    exit 1
}

# 3. re-seed Neo4j a partir do RAG novo
Write-Host ""
Write-Host "==> Re-seedando Neo4j (--clear)"
& $venvPython -m ufpr_automation.graphrag.seed --clear
if ($LASTEXITCODE -ne 0) { Write-Error "seed falhou"; exit 1 }

Write-Host ""
Write-Host "==> Enrich (extraindo normas do RAG -> Neo4j)"
& $venvPython -m ufpr_automation.graphrag.enrich
if ($LASTEXITCODE -ne 0) { Write-Error "enrich falhou"; exit 1 }

# 4. Gera manifest local
Write-Host ""
Write-Host "==> Gerando MANIFEST.json local"
& $venvPython (Join-Path $projectRoot "scripts\generate_manifest.py") --output $localManifest

# 5. Compara com remoto
if (Test-Path $remoteManifest) {
    $remoteInfo = Get-Content $remoteManifest -Raw | ConvertFrom-Json
    $localInfo  = Get-Content $localManifest  -Raw | ConvertFrom-Json

    Write-Host ""
    Write-Host "==> Comparacao remoto vs local apos sync:"
    $remoteChunks = $remoteInfo.lancedb.total_chunks
    $localChunks  = $localInfo.lancedb.total_chunks
    $remoteNodes  = $remoteInfo.neo4j.total_nodes
    $localNodes   = $localInfo.neo4j.total_nodes
    $remoteRels   = $remoteInfo.neo4j.total_relationships
    $localRels    = $localInfo.neo4j.total_relationships

    $chunksMatch = $remoteChunks -eq $localChunks
    $nodesMatch  = $remoteNodes  -eq $localNodes
    $relsMatch   = $remoteRels   -eq $localRels

    function Mark($ok) { if ($ok) { "OK" } else { "DIFF" } }

    Write-Host ("    LanceDB chunks:  remoto={0,7}  local={1,7}  [{2}]" -f $remoteChunks, $localChunks, (Mark $chunksMatch))
    Write-Host ("    Neo4j nos:       remoto={0,7}  local={1,7}  [{2}]" -f $remoteNodes,  $localNodes,  (Mark $nodesMatch))
    Write-Host ("    Neo4j rels:      remoto={0,7}  local={1,7}  [{2}]" -f $remoteRels,   $localRels,   (Mark $relsMatch))

    if ($chunksMatch -and $nodesMatch -and $relsMatch) {
        Write-Host ""
        Write-Host "PARIDADE OK - este PC esta sincronizado com a versao do G:."
    } else {
        Write-Host ""
        Write-Host "ATENCAO - drift detectado. Conferir se:"
        Write-Host "  - PROCEDURES.md / SOUL.md / seed.py mudaram desde o ultimo manifest"
        Write-Host "  - Neo4j foi modificado manualmente"
        Write-Host "  - Embeddings divergem (improvavel mas possivel entre versoes diferentes do sentence-transformers)"
    }
}

Write-Host ""
Write-Host "OK - sync G: -> local concluido."
