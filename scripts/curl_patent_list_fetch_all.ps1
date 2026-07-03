# 复现 patsight-cli patent list --fetch-all 对应的 HTTP 请求。
# 等价接口：GET {PATSIGHT_URL}/patent/api/v2/extractor/tasks

param(
    [int]$Page = 1,
    [int]$PerPage = 100,
    [switch]$FetchAll,
    [int]$FolderId = 0,
    [int]$View = -1,
    [string]$PatsightUrl = $env:PATSIGHT_URL,
    [string]$OpsUrl = $env:OPS_URL,
    [string]$Account = $env:PATSIGHT_OPS_ACCOUNT,
    [string]$Password = $env:PATSIGHT_OPS_PASSWORD,
    [string]$Token = $env:PATSIGHT_TOKEN,
    [switch]$PrintCurlOnly
)

$ErrorActionPreference = "Stop"

function Load-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) { return }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ([string]::IsNullOrWhiteSpace($name)) { return }
        $existing = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($existing)) {
            Set-Item -Path "env:$name" -Value $value
        }
    }
}

function Get-CachedToken {
    param([string]$ClientKey = "patsight:default")
    $dbCandidates = @(
        $env:PATSIGHT_CLI_CLIENT_DB,
        $env:XCLI_CLIENT_DB,
        $env:PATSIGHT_CLIENT_DB,
        (Join-Path $env:USERPROFILE ".local\share\patsight-cli\tasks.db")
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($dbPath in $dbCandidates) {
        $expanded = [Environment]::ExpandEnvironmentVariables($dbPath)
        if (-not (Test-Path $expanded)) { continue }
        $tokenValue = python -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); r=c.execute('SELECT token FROM credentials WHERE client_key=? LIMIT 1',(sys.argv[2],)).fetchone(); print(r[0] if r and r[0] else '')" $expanded $ClientKey 2>$null
        if (-not [string]::IsNullOrWhiteSpace($tokenValue)) {
            return $tokenValue.Trim()
        }
    }
    return $null
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Load-DotEnv (Join-Path $repoRoot ".env")

if ([string]::IsNullOrWhiteSpace($PatsightUrl)) { $PatsightUrl = $env:PATSIGHT_URL }
if ([string]::IsNullOrWhiteSpace($OpsUrl)) { $OpsUrl = $env:OPS_URL }
if ([string]::IsNullOrWhiteSpace($Account)) { $Account = $env:PATSIGHT_OPS_ACCOUNT }
if ([string]::IsNullOrWhiteSpace($Account)) { $Account = $env:PATSIGHT_ACCOUNT }
if ([string]::IsNullOrWhiteSpace($Password)) { $Password = $env:PATSIGHT_OPS_PASSWORD }
if ([string]::IsNullOrWhiteSpace($Password)) { $Password = $env:PATSIGHT_PASSWORD }
if ([string]::IsNullOrWhiteSpace($Token)) { $Token = $env:PATSIGHT_TOKEN }
if ([string]::IsNullOrWhiteSpace($Token)) { $Token = Get-CachedToken }

if ([string]::IsNullOrWhiteSpace($PatsightUrl)) { $PatsightUrl = "https://patent.xinsight-ai.com" }
if ([string]::IsNullOrWhiteSpace($OpsUrl)) { $OpsUrl = "https://xops.xtalpi.com" }

function Get-OpsToken {
    param(
        [string]$AccountValue,
        [string]$PasswordValue,
        [string]$OpsOrigin
    )
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($PasswordValue)
    $credential = [Convert]::ToBase64String($bytes)
    $tokenUrl = "$OpsOrigin/api/v2/public/token"
    $body = @{
        account = $AccountValue
        credential = $credential
    } | ConvertTo-Json -Compress

    Write-Host "== OPS Login =="
    Write-Host "POST $tokenUrl"
    Write-Host ""

    $response = Invoke-RestMethod -Method Post -Uri $tokenUrl -ContentType "application/json" -Body $body
    $tokenValue = $response.data.token
    if ([string]::IsNullOrWhiteSpace($tokenValue)) {
        throw "OPS token not found in response."
    }
    return $tokenValue
}

function Build-TasksUrl {
    param(
        [string]$Origin,
        [hashtable]$Query
    )
    $base = "{0}/patent/api/v2/extractor/tasks" -f $Origin.TrimEnd("/")
    $pairs = @()
    foreach ($key in ($Query.Keys | Sort-Object)) {
        $value = $Query[$key]
        if ($null -ne $value -and "$value" -ne "") {
            $pairs += ("{0}={1}" -f [uri]::EscapeDataString($key), [uri]::EscapeDataString("$value"))
        }
    }
    if ($pairs.Count -eq 0) { return $base }
    return $base + "?" + ($pairs -join "&")
}

function Invoke-TasksRequest {
    param(
        [string]$RequestUrl,
        [string]$AuthToken,
        [switch]$AsCurl
    )

    Write-Host "== Request =="
    Write-Host "GET $RequestUrl"
    Write-Host ""
    Write-Host "== Equivalent curl =="
    Write-Host "curl.exe -sS -X GET `"$RequestUrl`" -H `"Accept: application/json`" -H `"Authorization: <token>`""
    Write-Host ""

    if ($AsCurl) { return }

    $response = curl.exe -sS -X GET $RequestUrl `
        -H "Accept: application/json" `
        -H "User-Agent: patsight-cli/0.1 (patsight)" `
        -H "Authorization: $AuthToken" `
        -w "`nHTTP_STATUS:%{http_code}`n"

    Write-Host "== Response =="
    Write-Host $response
    Write-Host ""
    return $response
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    if ([string]::IsNullOrWhiteSpace($Account) -or [string]::IsNullOrWhiteSpace($Password)) {
        throw @"
Missing auth.
- Put PATSIGHT_OPS_ACCOUNT / PATSIGHT_OPS_PASSWORD in .env, or
- Set PATSIGHT_TOKEN, or
- Run `patsight-cli login` once so token is cached in ~/.local/share/patsight-cli/tasks.db
"@
    }
    $Token = Get-OpsToken -AccountValue $Account -PasswordValue $Password -OpsOrigin $OpsUrl
} else {
    Write-Host "== Auth =="
    Write-Host "Using cached token from env or SQLite."
    Write-Host ""
}

Write-Host "== CLI Mapping =="
Write-Host "patsight-cli patent list --fetch-all"
Write-Host "-> GET $PatsightUrl/patent/api/v2/extractor/tasks"
Write-Host "-> default query when no extra flags: page=1..N, per_page=100"
Write-Host "-> stops when a page returns empty task_info"
Write-Host ""

$allRows = @()
$currentPage = $Page
$maxPages = 500

do {
    $query = @{
        page = $currentPage
        per_page = $PerPage
    }
    if ($FolderId -gt 0) { $query.folder_id = $FolderId }
    if ($View -ge 0) { $query.view = $View }

    $requestUrl = Build-TasksUrl -Origin $PatsightUrl.TrimEnd("/") -Query $query
    $raw = Invoke-TasksRequest -RequestUrl $requestUrl -AuthToken $Token -AsCurl:$PrintCurlOnly
    if ($PrintCurlOnly) { break }

    $statusMatch = [regex]::Match($raw, "HTTP_STATUS:(\d+)")
    $status = if ($statusMatch.Success) { $statusMatch.Groups[1].Value } else { "unknown" }
    $body = [regex]::Replace($raw, "\s*HTTP_STATUS:\d+\s*$", "").Trim()
    Write-Host "HTTP status: $status"

    if ($status -ne "200") { break }

    try {
        $json = $body | ConvertFrom-Json
    } catch {
        Write-Host "Response is not JSON."
        break
    }

    $rows = @()
    if ($json.data.task_info) {
        $rows = @($json.data.task_info)
    } elseif ($json.data.data) {
        $rows = @($json.data.data)
    }

    Write-Host "page=$currentPage row_count=$($rows.Count) api_count=$($json.data.count)"
    $allRows += $rows

    if (-not $FetchAll) { break }
    if ($rows.Count -eq 0) { break }

    $currentPage += 1
} while ($currentPage -lt ($Page + $maxPages))

if ($FetchAll -and -not $PrintCurlOnly) {
    Write-Host "== Fetch-all summary =="
    Write-Host "total_rows=$($allRows.Count)"
}
