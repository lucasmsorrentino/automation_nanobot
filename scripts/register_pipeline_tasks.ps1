# Registra Windows Scheduled Task para rodar o pipeline UFPR 3x/dia.
# 1 task com 3 triggers (08:00, 13:00, 17:00) em vez de 3 tasks separadas.
#
# Modo padrao: -LogonType Interactive (sem senha; task roda quando usuario
# esta logado). Suficiente para PC pessoal onde voce loga diariamente.
#
# Para "run whether user is logged on or not" (precisa senha):
#   powershell -ExecutionPolicy Bypass -File scripts\register_pipeline_tasks.ps1 -WithPassword

param(
    [switch]$WithPassword
)

$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\Lucas\Documents\automation\automation_nanobot"
$wrapperPath = Join-Path $projectRoot "scripts\run_scheduled_once.bat"

if (-not (Test-Path $wrapperPath)) {
    Write-Error "Wrapper nao encontrado: $wrapperPath"
    exit 1
}

# Username canonico com prefixo da maquina (LogonUser exige isso em algumas
# situacoes; sem prefixo o Register-ScheduledTask pode rejeitar a senha mesmo
# quando ela esta correta).
$qualifiedUser = "$env:COMPUTERNAME\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute $wrapperPath -WorkingDirectory $projectRoot

$triggers = @(
    New-ScheduledTaskTrigger -Daily -At "08:00"
    New-ScheduledTaskTrigger -Daily -At "13:00"
    New-ScheduledTaskTrigger -Daily -At "17:00"
)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew

if ($WithPassword) {
    Write-Host ""
    Write-Host "Senha do Windows do usuario $qualifiedUser"
    Write-Host "  (task vai rodar mesmo com voce deslogado;"
    Write-Host "   nao e salva em disco, fica apenas em memoria)"
    $securePass = Read-Host -Prompt "Senha" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePass)
    $plainPass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

    Register-ScheduledTask `
        -TaskName "UFPR_Pipeline" `
        -Description "Pipeline UFPR (perceber -> agir): 08:00, 13:00, 17:00 (run whether logged on or not)" `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -User $qualifiedUser `
        -Password $plainPass `
        -RunLevel Limited `
        -Force | Out-Null

    Write-Host ""
    Write-Host "OK - Task 'UFPR_Pipeline' criada (run whether logged on or not)."
} else {
    # Interactive logon: roda apenas quando o usuario esta logado. Sem senha.
    $principal = New-ScheduledTaskPrincipal `
        -UserId $qualifiedUser `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName "UFPR_Pipeline" `
        -Description "Pipeline UFPR (perceber -> agir): 08:00, 13:00, 17:00 (only when user is logged in)" `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host ""
    Write-Host "OK - Task 'UFPR_Pipeline' criada (so roda quando voce esta logado)."
    Write-Host "    Para upgrade para 'run whether logged on or not', re-rodar o script com -WithPassword."
}

Write-Host ""
Write-Host "Comandos uteis:"
Write-Host "  Listar status:  schtasks /query /tn UFPR_Pipeline /fo LIST"
Write-Host "  Disparar agora: schtasks /run /tn UFPR_Pipeline"
Write-Host "  Remover:        schtasks /delete /tn UFPR_Pipeline /f"
