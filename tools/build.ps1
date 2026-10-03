param(
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Release',
    [ValidateSet('x64', 'Win32')][string]$Platform = 'x64',
    [switch]$Baseline
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$variant = if ($Baseline) { 'baseline' } else { 'automation' }
$stage = Join-Path $env:LOCALAPPDATA ('DisplayHDRAutomationBuild\' + $variant + '-' + $Platform + '-' + $Configuration)
$out = Join-Path $repo ('build-output\' + $variant + '-' + $Platform + '-' + $Configuration)
New-Item -ItemType Directory -Path $stage, $out -Force | Out-Null
if ($Baseline) {
    $archive = Join-Path $stage 'source.zip'
    git -C $repo archive --format=zip --output=$archive 68cda1f04eb14dea882dd9309d50f61803413574
    if ($LASTEXITCODE -ne 0) { throw 'Baseline archive failed.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
} else {
    Get-ChildItem -LiteralPath $repo -File | Copy-Item -Destination $stage -Force
}
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$installation = & $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild -property installationPath
$msbuild = Join-Path $installation 'MSBuild\Current\Bin\MSBuild.exe'
$localOut = Join-Path $stage 'bin\'
$localObj = Join-Path $stage 'obj\'
$log = Join-Path $out 'build.log'
& $msbuild (Join-Path $stage 'DisplayHDRComplianceTests.vcxproj') /m /nologo /v:minimal `
    /p:Configuration=$Configuration /p:Platform=$Platform /p:OutDir=$localOut /p:IntDir=$localObj `
    /p:PostBuildEventUseInBuild=false /p:LanguageStandard=stdcpp17 "/flp:logfile=$log;verbosity=normal"
if ($LASTEXITCODE -ne 0) { throw "Build failed. See $log" }
Get-ChildItem -LiteralPath $localOut -File | Where-Object Extension -In '.exe', '.pdb', '.cso' | Copy-Item -Destination $out -Force
Get-ChildItem -LiteralPath $stage -File -Filter '*.png' | Copy-Item -Destination $out -Force
if (-not $Baseline) {
    foreach ($file in 'displayhdr_api.py', 'displayhdr_server.py', 'displayhdr_supervisor.py', 'StartDisplayHDR.cmd') {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $out -Force
    }
}
Write-Output $out
