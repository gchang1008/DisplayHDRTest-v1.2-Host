param([switch]$Baseline, [switch]$Software)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$variant = if ($Baseline) { 'baseline' } else { 'automation' }
$stage = Join-Path $env:LOCALAPPDATA ('DisplayHDRAutomationBuild\' + $variant + '-x64-Release')
if (-not (Test-Path (Join-Path $stage 'Game.cpp'))) { throw 'Run build.ps1 first for this variant.' }
Get-ChildItem -LiteralPath $stage -File -Filter '*.png' | Copy-Item -Destination (Join-Path $stage 'bin') -Force
$probeStage = Join-Path $stage 'harness'
New-Item -ItemType Directory -Path $probeStage -Force | Out-Null
Get-ChildItem -LiteralPath $stage -File | Copy-Item -Destination $probeStage -Force
if (-not $Baseline) { Get-ChildItem -LiteralPath $repo -File | Copy-Item -Destination $probeStage -Force }
$header = Join-Path $probeStage 'Game.h'
$text = [IO.File]::ReadAllText($header)
$text = $text.Replace('class Game :', "struct RenderProbe;`r`nstruct RegressionRunner;`r`nclass Game :")
$text = $text.Replace('private:', "private:`r`n    friend struct RenderProbe;`r`n    friend struct RegressionRunner;")
$text += "`r`nstruct RenderProbe { static void Capture(Game& game); };`r`n"
[IO.File]::WriteAllText($header, $text)
$timerHeader = Join-Path $probeStage 'StepTimer.h'
$timerText = [IO.File]::ReadAllText($timerHeader).Replace('namespace DX', "struct RegressionRunner;`r`nnamespace DX").Replace('    private:', "    private:`r`n        friend struct ::RegressionRunner;")
[IO.File]::WriteAllText($timerHeader, $timerText)
$source = Join-Path $probeStage 'Game.cpp'
$bytes = [IO.File]::ReadAllBytes($source)
$encoding = [Text.Encoding]::GetEncoding(1252)
$text = $encoding.GetString($bytes).Replace('m_deviceResources->Present();', 'RenderProbe::Capture(*this); m_deviceResources->Present();')
[IO.File]::WriteAllBytes($source, $encoding.GetBytes($text))
if ($Software) {
    & python (Join-Path $PSScriptRoot 'prepare_harness.py') $probeStage
    if ($LASTEXITCODE -ne 0) { throw 'Offscreen test preparation failed.' }
}
Copy-Item -LiteralPath (Join-Path $repo 'tests\runtime_harness.cpp') -Destination (Join-Path $probeStage 'Main.cpp') -Force
$project = Join-Path $probeStage 'DisplayHDRComplianceTests.vcxproj'
$text = [IO.File]::ReadAllText($project).Replace('<SubSystem>Windows</SubSystem>', '<SubSystem>Console</SubSystem>').Replace('<TargetName>DisplayHDRComplianceTests</TargetName>', '<TargetName>RuntimeHarness</TargetName>')
[IO.File]::WriteAllText($project, $text)
$msbuild = Join-Path (& (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe') -latest -products '*' -property installationPath) 'MSBuild\Current\Bin\MSBuild.exe'
& $msbuild $project /m /nologo /v:quiet /p:Configuration=Release /p:Platform=x64 `
    "/p:OutDir=$probeStage\bin\" "/p:IntDir=$probeStage\obj\" /p:PostBuildEventUseInBuild=false
if ($LASTEXITCODE -ne 0) { throw 'Harness build failed.' }
Get-ChildItem (Join-Path $stage 'bin') -File | Where-Object Extension -In '.cso', '.png' | Copy-Item -Destination (Join-Path $probeStage 'bin') -Force
Write-Output (Join-Path $probeStage 'bin\RuntimeHarness.exe')
