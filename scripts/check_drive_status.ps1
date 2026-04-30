# Wrapper PowerShell ao redor de check_drive_freshness.py.
# Funciona em ambos os PCs porque usa caminho relativo a si mesmo:
#   - Project root  = parent do scripts/
#   - venv Python   = <root>/.venv/Scripts/python.exe (fallback: 'python')
#   - check script  = <root>/scripts/check_drive_freshness.py
#
# Usado em 3 contextos:
#   1. SessionStart hook do Claude Code (.claude/settings.json) — output entra no contexto
#   2. Pre-flight manual antes de mexer com RAG/Neo4j
#   3. Acompanhamento de drift entre PCs

$ErrorActionPreference = "Continue"  # nao aborta — queremos imprimir todos os warnings

$root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
$py = if (Test-Path $venvPy) { $venvPy } else { "python" }
$check = Join-Path $root "scripts\check_drive_freshness.py"

if (-not (Test-Path $check)) {
    Write-Host "[ERROR] $check nao encontrado"
    exit 6
}

# --quiet = nao imprime nada quando esta SYNCED (silencio = ok).
# Removendo --quiet para sempre ver o output, util durante calibragem inicial.
& $py $check
exit $LASTEXITCODE
