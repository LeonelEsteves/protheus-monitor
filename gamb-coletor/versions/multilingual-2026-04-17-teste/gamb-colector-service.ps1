param(
    [string]$FilterTerm = "TOTVS",
    [string]$OutputFile,
    [string]$ServerName,
    [string]$ServerIp
)

$ErrorActionPreference = "SilentlyContinue"

function Get-IniSectionValue {
    param(
        [string]$Content,
        [string]$SectionName,
        [string]$KeyName
    )
    if ([string]::IsNullOrWhiteSpace($Content)) { return "" }
    $sectionEscaped = [regex]::Escape($SectionName)
    $keyEscaped = [regex]::Escape($KeyName)
    $sectionPattern = '(?ims)^\s*\[{0}\]\s*$([\s\S]*?)(?=^\s*\[.*?\]\s*$|\z)' -f $sectionEscaped
    foreach ($match in [regex]::Matches($Content, $sectionPattern)) {
        $body = $match.Groups[1].Value
        $valueMatch = [regex]::Match($body, "(?im)^\s*$keyEscaped\s*=\s*([^;\r\n#]+)")
        if ($valueMatch.Success) {
            return $valueMatch.Groups[1].Value.Trim()
        }
    }
    return ""
}

function Get-IniAnyValue {
    param(
        [string]$Content,
        [string[]]$KeyNames
    )
    if ([string]::IsNullOrWhiteSpace($Content)) { return "" }
    foreach ($key in $KeyNames) {
        $keyEscaped = [regex]::Escape($key)
        $match = [regex]::Match($Content, "(?im)^\s*$keyEscaped\s*=\s*([^;\r\n#]+)")
        if ($match.Success) {
            return $match.Groups[1].Value.Trim()
        }
    }
    return ""
}

function Resolve-AppServerIniPath {
    param([string]$InstallFolder)
    if ([string]::IsNullOrWhiteSpace($InstallFolder)) { return "" }
    $candidates = @(
        (Join-Path $InstallFolder "appserver.ini"),
        (Join-Path $InstallFolder "bin\appserver.ini"),
        (Join-Path $InstallFolder "conf\appserver.ini")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return ""
}

function Get-AppServerIniPayload {
    param(
        [string]$InstallFolder,
        [string]$DefaultIp
    )
    $result = [ordered]@{
        service_ip = $DefaultIp
        tcp_port = ""
        webapp_port = ""
        rest_port = ""
        console_log = ""
        sourcepath = ""
        rpocustom = ""
    }
    $iniPath = Resolve-AppServerIniPath -InstallFolder $InstallFolder
    if ([string]::IsNullOrWhiteSpace($iniPath)) {
        return $result
    }

    $content = ""
    try {
        $content = Get-Content -Raw -Path $iniPath
    } catch {
        return $result
    }
    if ([string]::IsNullOrWhiteSpace($content)) {
        return $result
    }

    $serviceIp = Get-IniSectionValue -Content $content -SectionName "TCP" -KeyName "Server"
    if (-not $serviceIp) {
        $serviceIp = Get-IniSectionValue -Content $content -SectionName "GENERAL" -KeyName "Server"
    }
    if (-not $serviceIp) {
        $serviceIp = Get-IniAnyValue -Content $content -KeyNames @("server", "ip", "host")
    }
    if ($serviceIp) { $result.service_ip = $serviceIp }

    $result.tcp_port = Get-IniSectionValue -Content $content -SectionName "TCP" -KeyName "Port"
    $result.webapp_port = Get-IniSectionValue -Content $content -SectionName "WEBAPP" -KeyName "Port"
    $result.rest_port = Get-IniSectionValue -Content $content -SectionName "httprest" -KeyName "port"
    $result.console_log = Get-IniAnyValue -Content $content -KeyNames @("consolefile", "console_file", "console file")
    $result.sourcepath = Get-IniAnyValue -Content $content -KeyNames @("sourcepath")
    $result.rpocustom = Get-IniAnyValue -Content $content -KeyNames @("rpocustom")

    return $result
}

function Resolve-ServiceExecutablePath {
    param([string]$ServiceName)

    if ([string]::IsNullOrWhiteSpace($ServiceName)) {
        return ""
    }

    try {
        $serviceDetails = Get-CimInstance Win32_Service -Filter ("Name='{0}'" -f $ServiceName.Replace("'", "''"))
        $pathName = [string]$serviceDetails.PathName
        if (-not [string]::IsNullOrWhiteSpace($pathName)) {
            if ($pathName.StartsWith('"')) {
                $parts = $pathName.Split('"')
                if ($parts.Count -ge 2 -and -not [string]::IsNullOrWhiteSpace($parts[1])) {
                    return $parts[1].Trim()
                }
            }
            $match = [regex]::Match($pathName, '(?i)^\s*([^\r\n]+?\.exe)\b')
            if ($match.Success) {
                return $match.Groups[1].Value.Trim()
            }
            return $pathName.Trim()
        }
    } catch {
    }

    $qcLine = sc.exe qc $ServiceName 2>$null | Where-Object { $_ -match "BINARY_PATH_NAME" } | Select-Object -First 1
    if (-not $qcLine) {
        return ""
    }

    $pathName = (($qcLine -split ":", 2)[1]).Trim()
    if ($pathName.StartsWith('"')) {
        $parts = $pathName.Split('"')
        if ($parts.Count -ge 2 -and -not [string]::IsNullOrWhiteSpace($parts[1])) {
            return $parts[1].Trim()
        }
    }

    $match = [regex]::Match($pathName, '(?i)^\s*([^\r\n]+?\.exe)\b')
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }

    return ""
}

$osVersion = $null
$osBuild = $null
$diskSummary = $null
$diskTotalGb = $null
$diskFreeGb = $null
$pendingUpdatesCount = $null

try {
    $cv = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    if ($cv) {
        $name = $cv.ProductName
        $ver = $cv.DisplayVersion
        if (-not $ver) { $ver = $cv.ReleaseId }
        if (-not $ver) { $ver = $cv.CurrentVersion }
        $osVersion = ("{0} {1}" -f $name, $ver).Trim()
        $osBuild = $cv.CurrentBuild
    }
} catch {
}

try {
    $disks = [System.IO.DriveInfo]::GetDrives() |
        Where-Object { $_.DriveType -eq [System.IO.DriveType]::Fixed -and $_.IsReady } |
        Sort-Object Name
    if ($disks) {
        $diskParts = @()
        $sumSize = 0.0
        $sumFree = 0.0
        foreach ($d in $disks) {
            $sizeGb = [math]::Round(([double]$d.TotalSize / 1GB), 2)
            $freeGb = [math]::Round(([double]$d.AvailableFreeSpace / 1GB), 2)
            $sumSize += $sizeGb
            $sumFree += $freeGb
            $diskParts += ("{0} {1}GB livres de {2}GB" -f $d.Name.TrimEnd("\"), $freeGb, $sizeGb)
        }
        $diskSummary = ($diskParts -join "; ")
        $diskTotalGb = [math]::Round($sumSize, 2)
        $diskFreeGb = [math]::Round($sumFree, 2)
    }
} catch {
}

try {
    $updateSession = New-Object -ComObject "Microsoft.Update.Session"
    $updateSearcher = $updateSession.CreateUpdateSearcher()
    $searchResult = $updateSearcher.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
    if ($searchResult) {
        $pendingUpdatesCount = [int]$searchResult.Updates.Count
    }
} catch {
}

$prev = @{}
if (Test-Path $OutputFile) {
    try {
        $old = Get-Content -Raw -Path $OutputFile | ConvertFrom-Json -ErrorAction Stop
        if ($null -ne $old) {
            if ($old.PSObject.Properties.Name -contains "services") {
                foreach ($x in $old.services) {
                    if ($x.service_name) {
                        $prev[$x.service_name] = [string]$x.status_atual
                    }
                }
            } elseif ($old -is [System.Collections.IEnumerable] -and $old -isnot [string]) {
                foreach ($x in $old) {
                    if ($x.service_name) {
                        $prev[$x.service_name] = [string]$x.status_atual
                    }
                }
            } elseif ($old.service_name) {
                $prev[$old.service_name] = [string]$old.status_atual
            }
        }
    } catch {
    }
}

$outDir = Split-Path -Parent $OutputFile
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$services = Get-Service |
    Where-Object {
        $_.StartType -ne "Disabled" -and
        ( $_.Name -like "*$FilterTerm*" -or $_.DisplayName -like "*$FilterTerm*" )
    } |
    Sort-Object DisplayName, Name

$items = @()
foreach ($svc in $services) {
    $status = ([string]$svc.Status).Trim()
    switch -Regex ($status) {
        "^Running$" { $statusAtual = "RODANDO"; break }
        "^Stopped$" { $statusAtual = "PARADO"; break }
        "^StartPending$" { $statusAtual = "INICIANDO"; break }
        "^StopPending$" { $statusAtual = "PARANDO"; break }
        "^Paused$" { $statusAtual = "PAUSADO"; break }
        "^PausePending$" { $statusAtual = "PAUSANDO"; break }
        "^ContinuePending$" { $statusAtual = "CONTINUANDO"; break }
        default { $statusAtual = $status }
    }

    $statusAnterior = $null
    if ($prev.ContainsKey($svc.Name)) {
        $statusAnterior = $prev[$svc.Name]
    }

    if ([string]::IsNullOrWhiteSpace($statusAnterior)) {
        $evento = "INICIAL"
    } elseif ($statusAtual -eq $statusAnterior) {
        $evento = "SEM_ALTERACAO"
    } else {
        $evento = "ALTERACAO_STATUS"
    }

    $installFolder = $null
    $exe = Resolve-ServiceExecutablePath -ServiceName $svc.Name
    if ($exe) {
        try {
            $installFolder = Split-Path -Path $exe -Parent
        } catch {
        }
    }

    $iniPayload = Get-AppServerIniPayload -InstallFolder $installFolder -DefaultIp $ServerIp

    $items += [ordered]@{
        service_name   = $svc.Name
        display_name   = $svc.DisplayName
        install_folder = $installFolder
        service_ip     = $iniPayload.service_ip
        tcp_port       = [string]$iniPayload.tcp_port
        webapp_port    = [string]$iniPayload.webapp_port
        rest_port      = [string]$iniPayload.rest_port
        console_log    = [string]$iniPayload.console_log
        sourcepath     = [string]$iniPayload.sourcepath
        rpocustom      = [string]$iniPayload.rpocustom
        status_atual   = $statusAtual
        status_anterior= $statusAnterior
        evento         = $evento
        timestamp      = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    }
}

$payload = [ordered]@{
    server = [ordered]@{
        server_name = $ServerName
        server_ip = $ServerIp
        os_version = $osVersion
        os_build = $osBuild
        disk_space = $diskSummary
        disk_total_gb = $diskTotalGb
        disk_free_gb = $diskFreeGb
        windows_updates_pending = $pendingUpdatesCount
        timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    }
    services = @($items)
}

Set-Content -Path $OutputFile -Value ($payload | ConvertTo-Json -Depth 6) -Encoding UTF8
Write-Output $items.Count
