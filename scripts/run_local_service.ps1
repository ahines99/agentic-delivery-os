# Local login supervisor. No credentials are placed on the command line.
$ErrorActionPreference = 'Stop'
$deliveryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$deliveryRuntime = Join-Path $deliveryRoot '.local/runtime'
$deliveryMutex = [Threading.Mutex]::new($false, 'Local\AgenticDeliveryOS')
$deliveryOwnsMutex = $false
$deliveryProcess = $null
try {
    try { $deliveryOwnsMutex = $deliveryMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $deliveryOwnsMutex = $true }
    if (-not $deliveryOwnsMutex) { exit 0 }
    Set-Location -LiteralPath $deliveryRoot
    New-Item -ItemType Directory -Path $deliveryRuntime -Force | Out-Null
    $deliveryUv = Join-Path $env:USERPROFILE '.local/bin/uv.exe'
    $deliveryDocker = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
    if (Get-Command uv -ErrorAction SilentlyContinue) { $deliveryUv = (Get-Command uv).Source }
    if (Get-Command docker -ErrorAction SilentlyContinue) { $deliveryDocker = (Get-Command docker).Source }
    foreach ($deliveryRequired in @($deliveryUv, $deliveryDocker, 'config.local.json', '.local/linear.env', '.local/model.env', '.local/compose.env')) {
        if (-not (Test-Path -LiteralPath $deliveryRequired)) { throw 'Local delivery setup is incomplete' }
    }
    $env:PATH = "$(Split-Path -Parent $deliveryDocker);$env:PATH"
    while ($true) {
        $ErrorActionPreference = 'Continue'
        & $deliveryDocker compose --env-file .local/compose.env up --detach --wait *> (Join-Path $deliveryRuntime 'infrastructure.log')
        $deliveryComposeExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($deliveryComposeExit -eq 0) {
            $deliveryProcess = Start-Process -FilePath $deliveryUv -ArgumentList @(
                'run', '--no-sync', '--env-file', '.local/linear.env', '--env-file', '.local/model.env',
                'python', '-m', 'agentic_delivery.service_cli', 'run', '--config', 'config.local.json'
            ) -WorkingDirectory $deliveryRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $deliveryRuntime 'service-stdout.log') `
                -RedirectStandardError (Join-Path $deliveryRuntime 'service-stderr.log')
            $deliveryProcess.Id | Set-Content -LiteralPath (Join-Path $deliveryRuntime 'launcher.pid')
            $deliveryProcess.WaitForExit()
        }
        Start-Sleep -Seconds 15
    }
} finally {
    if ($null -ne $deliveryProcess -and -not $deliveryProcess.HasExited) { $deliveryProcess.Kill() }
    if ($deliveryOwnsMutex) { $deliveryMutex.ReleaseMutex() }
    $deliveryMutex.Dispose()
}
