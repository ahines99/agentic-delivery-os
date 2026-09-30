# Install or update this repository's current-user login supervisor.
$ErrorActionPreference = 'Stop'
$deliveryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$deliveryScript = Join-Path $deliveryRoot 'scripts/run_local_service.ps1'
$deliveryAction = New-ScheduledTaskAction `
    -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File "' + $deliveryScript + '"') `
    -WorkingDirectory $deliveryRoot
$deliveryPrincipal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
$deliverySettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName AgenticDeliveryOS -Action $deliveryAction `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $deliveryPrincipal.UserId) `
    -Principal $deliveryPrincipal -Settings $deliverySettings `
    -Description 'Local automatic Linear delivery service for Agentic Delivery OS' -Force | Out-Null
Start-ScheduledTask -TaskName AgenticDeliveryOS
Write-Output 'AgenticDeliveryOS login task installed and started. Check http://127.0.0.1:18090/readyz.'
