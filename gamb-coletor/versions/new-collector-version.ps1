param(
    [string]$SourceVersion,
    [string]$NewVersion,
    [switch]$UseCurrentTimestamp
)

$ErrorActionPreference = "Stop"

$versionsRoot = Split-Path -Parent $PSCommandPath

function Get-LatestCollectorVersion {
    param([string]$RootPath)

    $directories = Get-ChildItem -LiteralPath $RootPath -Directory | Sort-Object Name -Descending
    foreach ($directory in $directories) {
        if (Test-Path -LiteralPath (Join-Path $directory.FullName "gamb-colector-service.bat")) {
            return $directory.Name
        }
    }

    throw "Nenhuma versao do coletor foi encontrada em $RootPath."
}

if ([string]::IsNullOrWhiteSpace($SourceVersion)) {
    $SourceVersion = Get-LatestCollectorVersion -RootPath $versionsRoot
}

if ([string]::IsNullOrWhiteSpace($NewVersion)) {
    $stamp = if ($UseCurrentTimestamp) { Get-Date -Format "yyyy-MM-dd-HHmmss" } else { Get-Date -Format "yyyy-MM-dd" }
    $baseName = "multilingual-$stamp"
    $NewVersion = $baseName
    $counter = 2
    while (Test-Path -LiteralPath (Join-Path $versionsRoot $NewVersion)) {
        $NewVersion = "$baseName-v$counter"
        $counter++
    }
}

$sourceDir = Join-Path $versionsRoot $SourceVersion
if (-not (Test-Path -LiteralPath $sourceDir -PathType Container)) {
    throw "Versao de origem nao encontrada: $SourceVersion"
}

$targetDir = Join-Path $versionsRoot $NewVersion
if (Test-Path -LiteralPath $targetDir) {
    throw "A versao de destino ja existe: $NewVersion"
}

$requiredFiles = @(
    "gamb-colector-service.bat",
    "gamb-colector-service.ps1",
    "README.md"
)

foreach ($fileName in $requiredFiles) {
    $sourceFile = Join-Path $sourceDir $fileName
    if (-not (Test-Path -LiteralPath $sourceFile -PathType Leaf)) {
        throw "Arquivo obrigatorio ausente na origem: $sourceFile"
    }
}

Copy-Item -LiteralPath $sourceDir -Destination $targetDir -Recurse

$readmePath = Join-Path $targetDir "README.md"
$readmeContent = Get-Content -LiteralPath $readmePath -Raw
$readmeContent = $readmeContent -replace [regex]::Escape($SourceVersion), $NewVersion
$readmeContent = $readmeContent -replace "(Data da captura:\s*`?)[^`r`n]+", ('$1`' + (Get-Date -Format "yyyy-MM-dd") + "`'")
Set-Content -LiteralPath $readmePath -Value $readmeContent -Encoding UTF8

Write-Host "Nova versao do coletor criada com sucesso."
Write-Host "Origem : $SourceVersion"
Write-Host "Destino: $NewVersion"
Write-Host "Pasta  : $targetDir"
