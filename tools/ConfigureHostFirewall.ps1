#requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory = $true)]
    [string]$ControllerAddress,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$controllerIp = $null
if (-not [System.Net.IPAddress]::TryParse($ControllerAddress, [ref]$controllerIp)) {
    throw 'ControllerAddress must be the IP address of the controller PC.'
}
$programPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'runtime\python.exe'))
if (-not (Test-Path -LiteralPath $programPath -PathType Leaf)) {
    throw 'Run this script from the complete, unpacked Host package in its permanent installation folder.'
}
$hashProvider = [System.Security.Cryptography.SHA256]::Create()
try {
    $pathHash = $hashProvider.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($programPath.ToLowerInvariant()))
    $ruleSuffix = ([System.BitConverter]::ToString($pathHash)).Replace('-', '').Substring(0, 12)
} finally {
    $hashProvider.Dispose()
}
$ruleName = "DisplayHDR-Host-API-$ruleSuffix"
if ($PSCmdlet.ShouldProcess($programPath, "Allow TCP $Port from $controllerIp on Private and Domain networks")) {
    $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        $existing | Set-NetFirewallRule -Enabled True -Direction Inbound -Action Allow -Profile Private,Domain
        $existing | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program $programPath
        $existing | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $Port
        $existing | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $controllerIp.ToString()
    } else {
        New-NetFirewallRule -Name $ruleName -DisplayName 'DisplayHDR Host API' -Direction Inbound `
            -Action Allow -Enabled True -Program $programPath -Protocol TCP -LocalPort $Port `
            -RemoteAddress $controllerIp.ToString() -Profile Private,Domain | Out-Null
    }
    Write-Host "Configured $ruleName for controller $controllerIp and TCP $Port."
}
