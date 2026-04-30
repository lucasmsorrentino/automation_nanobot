# Registra Windows Scheduled Task para rodar o pipeline UFPR 3x/dia.
# 1 task com 3 triggers (08:00, 13:00, 17:00) em vez de 3 tasks separadas.
# Uso: clicar com o botao direito > "Run with PowerShell" OU executar:
#   powershell -ExecutionPolicy Bypass -File scripts\register_pipeline_tasks.ps1
# Sera pedida a senha do usuario Windows uma unica vez (necessaria para
# "run whether user is logged on or not").

$ErrorActionPreference = "Stop"

$projectRoot = "C:\Users\Lucas\Documents\automation\automation_nanobot"
$wrapperPath = Join-Path $projectRoot "scripts\run_scheduled_once.bat"

if (-not (Test-Path $wrapperPath)) {
    Write-Error "Wrapper nao encontrado: $wrapperPath"
    exit 1
}

# Pede senha do usuario Windows (cifrada em memoria, nao salva em disco).
$cred = Get-Credential -UserName $env:USERNAME -Message "Senha do Windows (necessaria para rodar a task com usuario deslogado)"

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

Register-ScheduledTask `
    -TaskName "UFPR_Pipeline" `
    -Description "Pipeline UFPR (perceber -> agir): 08:00, 13:00, 17:00. Wrapper em scripts\run_scheduled_once.bat. Logs em logs\scheduler.log e logs\task_scheduler_wrapper.log." `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -User $env:USERNAME `
    -Password $cred.GetNetworkCredential().Password `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host ""
Write-Host "OK - Task 'UFPR_Pipeline' criada com 3 triggers diarios (08:00, 13:00, 17:00)."
Write-Host ""
Write-Host "Comandos uteis:"
Write-Host "  Listar status:  schtasks /query /tn UFPR_Pipeline /fo LIST"
Write-Host "  Disparar agora: schtasks /run /tn UFPR_Pipeline"
Write-Host "  Atualizar senha (apos trocar senha do Windows):"
Write-Host "                  schtasks /change /tn UFPR_Pipeline /rp <nova_senha>"
Write-Host "  Remover:        schtasks /delete /tn UFPR_Pipeline /f"
