<#
.SYNOPSIS
  生成「给同学的整文件夹 zip」：保留源码/留痕/测试/readme/plans/规格/dist/运行时 .env，
  剔除依赖与运行产物（.venv / node_modules / *.db / __pycache__ / 测试临时目录）。

.DESCRIPTION
  从工作文件夹（本脚本上两级）整体复制到临时目录再压缩，避免把
  backend/.venv、frontend/node_modules、*.db、__pycache__、.tmp-* 等打进包。
  按 2026-11-11 用户拍板：backend/.env 属于「有意分发」的运行时配置
  （同学需要 Key 才能连模型），**保留在同学包内**；比赛交付包仍由
  tests/security/pack_delivery.py 生成且不含 .env，两者用途不同。
  压缩后做二次开包自检：依赖/数据库/缓存命中必须为 0；backend/.env 恰 1 个；
  frontend/dist/index.html 必须在包内。

.PARAMETER SourceRoot
  工作文件夹根（默认 = 本脚本上两级，即含 campus-task-agent/ 与两份规格 md 的目录）。

.PARAMETER OutZip
  输出 zip 路径（默认放在工作文件夹根下 campus-task-agent-release.zip）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make_release_zip.ps1
#>
param(
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$OutZip = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($OutZip)) {
    $OutZip = Join-Path $SourceRoot 'campus-task-agent-release.zip'
}

Write-Host "[1/4] 源目录: $SourceRoot"
if (-not (Test-Path (Join-Path $SourceRoot 'campus-task-agent'))) {
    throw "未找到 campus-task-agent/，请从工作文件夹根运行本脚本。"
}

# 1) 复制到临时目录：目录排除 + 文件排除
#    注意：这里**不**排除 .env —— 同学包按用户拍板保留 backend/.env（真实 Key 由本人决策接受）
$stage = Join-Path $env:TEMP ("cta-release-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
robocopy $SourceRoot $stage /E `
    /XD '.venv' 'node_modules' '__pycache__' '.pytest_cache' `
    /XF '*.db' '*.db-journal' '*.db-wal' '*.db-shm' '*.sqlite' '*.sqlite3' '*.pyc' '~$*' 'campus-task-agent-release.zip' `
    /NFL /NDL /NJH /NJS /NP | Out-Null
# robocopy 成功码为 0~7，8 以上才是失败
if ($LASTEXITCODE -ge 8) { throw "robocopy 失败，退出码 $LASTEXITCODE" }

# 2) 清理测试临时目录（若上一轮遗留）
Get-ChildItem -Path $stage -Recurse -Directory -Filter '.tmp-*' -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -Recurse -Force $_.FullName }

# 3) 压缩（-Force 覆盖旧包）
if (Test-Path $OutZip) { Remove-Item -Force $OutZip }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($stage, $OutZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

# 4) 二次开包自检
$zip = [System.IO.Compression.ZipFile]::OpenRead($OutZip)
try {
    $entries = $zip.Entries
    # 依赖 / 数据库 / 缓存：必须 0 命中（.env 不在此列，见上方说明）
    $bad = $entries | Where-Object {
        $n = $_.FullName.Replace('\', '/')
        ($n -match '\.db(-journal|-wal|-shm)?$') -or
        ($n -match '/node_modules/') -or
        ($n -match '/\.venv/') -or
        ($n -match '/__pycache__/')
    }
    $envCount = ($entries | Where-Object {
        $_.FullName.Replace('\', '/') -match '(^|/)backend/\.env$'
    }).Count
    $distIndex = ($entries | Where-Object { $_.FullName.Replace('\', '/') -match 'frontend/dist/index\.html$' }).Count
    $distCount = ($entries | Where-Object { $_.FullName.Replace('\', '/') -match 'frontend/dist/' }).Count
    $gitEntries = $entries | Where-Object { $_.FullName.Replace('\', '/') -match '/\.git/' }
    $hasGit = $gitEntries.Count -gt 0
    $gitBytes = ($gitEntries | Measure-Object -Property CompressedLength -Sum).Sum
    if ($null -eq $gitBytes) { $gitBytes = 0 }
    $gitMb = [math]::Round($gitBytes / 1MB, 2)
    $hasPlans = ($entries | Where-Object { $_.FullName.Replace('\', '/') -match '\.codeartsdoer/plans/.*plan\.md$' }).Count
    $hasSpec = ($entries | Where-Object { $_.FullName -match '校园任务协同AI-Agent-(开发方案|应用介绍)\.md$' }).Count
    $entryCount = $entries.Count
} finally {
    $zip.Dispose()
}
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue

$sizeMb = [math]::Round((Get-Item $OutZip).Length / 1MB, 2)
Write-Host "[2/4] ZIP = $OutZip"
Write-Host "[3/4] ENTRIES=$entryCount  SIZE_MB=$sizeMb"
Write-Host "[4/4] BAD=$($bad.Count)  ENV_IN_PKG=$envCount  DIST_INDEX=$distIndex  DIST_FILES=$distCount  GIT=$hasGit(${gitMb}MB)  PLANS=$hasPlans  SPEC=$hasSpec"

if ($bad.Count -ne 0 -or $envCount -ne 1 -or $distIndex -lt 1) {
    Write-Error "自检失败：依赖/数据库/缓存命中 $($bad.Count) 个（必须 0）；backend/.env 命中 $envCount 个（预期 1）；frontend/dist/index.html 命中 $distIndex 个（须 >= 1）。"
    exit 1
}
Write-Host "SELF_CHECK=PASS"
exit 0