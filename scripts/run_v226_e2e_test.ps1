# V2.26 新增 CLI 命令生产环境实测脚本
$ErrorActionPreference = "Continue"
$Account = "qingnan.xie@xtalpi.com"
$Password = "<password>"
$Ts = Get-Date -Format "yyyyMMdd_HHmmss"
$EvidenceDir = Join-Path (Resolve-Path "..").Path "evidence\v226_e2e_$Ts"
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

function Save-Run {
    param(
        [string]$Name,
        [string[]]$Command
    )
    $stdoutFile = Join-Path $EvidenceDir "$Name.stdout.txt"
    $stderrFile = Join-Path $EvidenceDir "$Name.stderr.txt"
    $metaFile = Join-Path $EvidenceDir "$Name.meta.json"
    $cmdLine = ($Command -join " ")
    Write-Host ">>> $cmdLine"
    & $Command[0] $Command[1..($Command.Length-1)] 1> $stdoutFile 2> $stderrFile
    $exitCode = $LASTEXITCODE
    @{
        name = $Name
        command = $cmdLine
        exit_code = $exitCode
        stdout_file = $stdoutFile
        stderr_file = $stderrFile
    } | ConvertTo-Json | Set-Content -Path $metaFile -Encoding UTF8
    return $exitCode
}

$Auth = @("--account", $Account, "--password", $Password)

Save-Run "01_help_root" @("patsight-cli", "--help")
Save-Run "02_help_shared_folder" @("patsight-cli", "shared-folder", "--help")
Save-Run "03_help_patent" @("patsight-cli", "patent", "--help")

Save-Run "10_shared_folder_list_view0" @("patsight-cli", "shared-folder", "list", "--view", "0") + $Auth
Save-Run "11_shared_folder_list_view1" @("patsight-cli", "shared-folder", "list", "--view", "1") + $Auth

$TestFolderName = "cli-e2e-$Ts"
Save-Run "20_shared_folder_create" @("patsight-cli", "shared-folder", "create", "--name", $TestFolderName) + $Auth

$createStdout = Get-Content (Join-Path $EvidenceDir "20_shared_folder_create.stdout.txt") -Raw
$folderId = $null
if ($createStdout -match '"folder_id"\s*:\s*(\d+)') {
    $folderId = [int]$Matches[1]
}
if (-not $folderId -and ($createStdout -match '"id"\s*:\s*(\d+)')) {
    $folderId = [int]$Matches[1]
}

if ($folderId) {
    Save-Run "21_shared_folder_list_after_create" @("patsight-cli", "shared-folder", "list") + $Auth
    Save-Run "22_shared_folder_rename" @("patsight-cli", "shared-folder", "rename", "--folder-id", "$folderId", "--name", "$TestFolderName-renamed") + $Auth
    Save-Run "23_shared_folder_members_list" @("patsight-cli", "shared-folder", "members", "list", "--folder-id", "$folderId") + $Auth
    Save-Run "24_shared_folder_members_add" @("patsight-cli", "shared-folder", "members", "add", "--folder-id", "$folderId", "--email", "qingnan.xie@xtalpi.com", "--role", "admin") + $Auth
    Save-Run "25_shared_folder_patents_list" @("patsight-cli", "shared-folder", "patents", "list", "--folder-id", "$folderId") + $Auth
}

Save-Run "30_patent_list_default" @("patsight-cli", "patent", "list", "--page", "1", "--per-page", "5") + $Auth
Save-Run "31_patent_list_with_folder" @("patsight-cli", "patent", "list", "--page", "1", "--per-page", "5", "--status", "done") + $Auth

$patentStdout = Get-Content (Join-Path $EvidenceDir "30_patent_list_default.stdout.txt") -Raw
$taskId = $null
if ($patentStdout -match '"id"\s*:\s*(\d+)') {
    $taskId = [int]$Matches[1]
}

if ($taskId) {
    Save-Run "32_patent_detail" @("patsight-cli", "patent", "detail", "--task-id", "$taskId") + $Auth
    Save-Run "33_patent_editors" @("patsight-cli", "patent", "editors", "--task-id", "$taskId") + $Auth
    if ($folderId) {
        Save-Run "34_shared_folder_patents_add" @("patsight-cli", "shared-folder", "patents", "add", "--folder-id", "$folderId", "--task-id", "$taskId") + $Auth
        Save-Run "35_shared_folder_patents_list_after_add" @("patsight-cli", "shared-folder", "patents", "list", "--folder-id", "$folderId") + $Auth
        Save-Run "36_shared_folder_patents_remove" @("patsight-cli", "shared-folder", "patents", "remove", "--folder-id", "$folderId", "--task-id", "$taskId") + $Auth
    }
}

Save-Run "40_submit_conflict" @("patsight-cli", "submit", "--pdf-path", "WO2010111432A1.pdf", "--folder-id", "0", "--shared-folder-id", "27463") + $Auth

$pdfPath = Join-Path (Resolve-Path "..").Path "WO2010111432A1.pdf"
if ((Test-Path $pdfPath) -and $folderId) {
    Save-Run "41_submit_shared_folder" @("patsight-cli", "submit", "--pdf-path", $pdfPath, "--shared-folder-id", "$folderId", "--pages", "1-2") + $Auth
}

if ($folderId) {
    Save-Run "90_shared_folder_delete" @("patsight-cli", "shared-folder", "delete", "--folder-id", "$folderId") + $Auth
}

@{
    evidence_dir = $EvidenceDir
    test_folder_name = $TestFolderName
    folder_id = $folderId
    task_id = $taskId
    account = $Account
    finished_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -Path (Join-Path $EvidenceDir "summary.json") -Encoding UTF8

Write-Host "Evidence saved to $EvidenceDir"
Write-Host "folder_id=$folderId task_id=$taskId"
