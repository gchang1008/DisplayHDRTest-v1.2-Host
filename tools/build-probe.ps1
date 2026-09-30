param([switch]$Baseline)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$variant = if ($Baseline) { 'baseline' } else { 'automation' }
$sourceStage = Join-Path $env:LOCALAPPDATA ('DisplayHDRAutomationBuild\' + $variant + '-x64-Release')
$probeStage = Join-Path $sourceStage 'behavior-probe'
New-Item -ItemType Directory -Path $probeStage -Force | Out-Null
Get-ChildItem -LiteralPath $sourceStage -File | Copy-Item -Destination $probeStage -Force
if (-not $Baseline) { Get-ChildItem -LiteralPath $repo -File | Copy-Item -Destination $probeStage -Force }
Copy-Item -LiteralPath (Join-Path $repo 'tests\behavior_probe.h'), (Join-Path $repo 'tests\behavior_probe.cpp') -Destination $probeStage -Force
$header = Join-Path $probeStage 'Game.h'
$text = [IO.File]::ReadAllText($header).Replace('class Game :', "struct BehaviorProbe;`r`nclass Game :").Replace('private:', "private:`r`n    friend struct BehaviorProbe;")
[IO.File]::WriteAllText($header, $text)
$encoding = [Text.Encoding]::GetEncoding(1252)
$source = Join-Path $probeStage 'Game.cpp'
$text = $encoding.GetString([IO.File]::ReadAllBytes($source)).Replace('#include "Game.h"', "#include `"Game.h`"`r`n#include `"behavior_probe.h`"")
$needle = "    Render();`r`n}"
if (-not $text.Contains($needle)) { throw 'Tick boundary not found.' }
$text = $text.Replace($needle, "    Render();`r`n    BehaviorProbe::Record(*this);`r`n}")
[IO.File]::WriteAllBytes($source, $encoding.GetBytes($text))
$project = Join-Path $probeStage 'DisplayHDRComplianceTests.vcxproj'
$text = [IO.File]::ReadAllText($project).Replace('<ClCompile Include="Game.cpp" />', '<ClCompile Include="Game.cpp" /><ClCompile Include="behavior_probe.cpp" />')
[IO.File]::WriteAllText($project, $text)
$msbuild = Join-Path (& (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe') -latest -products '*' -property installationPath) 'MSBuild\Current\Bin\MSBuild.exe'
& $msbuild $project /m /nologo /v:quiet /p:Configuration=Release /p:Platform=x64 "/p:OutDir=$probeStage\bin\" "/p:IntDir=$probeStage\obj\" /p:PostBuildEventUseInBuild=false
if ($LASTEXITCODE -ne 0) { throw 'Probe build failed.' }
Get-ChildItem (Join-Path $sourceStage 'bin') -File | Where-Object Extension -In '.cso', '.png' | Copy-Item -Destination (Join-Path $probeStage 'bin') -Force
Write-Output (Join-Path $probeStage 'bin\DisplayHDRComplianceTests.exe')
