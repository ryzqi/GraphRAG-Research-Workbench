param(
    [string]$RecordPath = "",
    [string]$PreviousGoodCommit = "",
    [switch]$Execute
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")

if (-not $RecordPath) {
    $RecordPath = Join-Path $repoRoot "full-refactor-deep-research\research-rollback-drill-record.md"
}

$recordDir = Split-Path -Parent $RecordPath
if (-not (Test-Path -LiteralPath $recordDir)) {
    New-Item -ItemType Directory -Force -Path $recordDir | Out-Null
}

$currentCommit = (git -C $repoRoot rev-parse HEAD).Trim()
$shortCommit = (git -C $repoRoot rev-parse --short HEAD).Trim()
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$mode = if ($Execute) { "execute" } else { "dry-run" }

$qualityGate = if ($env:RESEARCH_GATE_MIN_QUALITY_SCORE) {
    $env:RESEARCH_GATE_MIN_QUALITY_SCORE
} else {
    "0.75"
}
$latencyGate = if ($env:RESEARCH_GATE_MAX_P95_MS) {
    $env:RESEARCH_GATE_MAX_P95_MS
} else {
    "120000"
}
$costGate = if ($env:RESEARCH_GATE_MAX_SESSION_COST_USD) {
    $env:RESEARCH_GATE_MAX_SESSION_COST_USD
} else {
    "2.0"
}

$previousGoodCommitDisplay = if ($PreviousGoodCommit) {
    $PreviousGoodCommit
} else {
    "未指定（需人工填入最近一次 research 发布基线 commit）"
}

$resultSummary = if ($Execute) {
    "已生成执行版演练记录，等待人工确认后推进真实回滚。"
} else {
    "已生成 dry-run 演练记录，可作为 Task 11 交付证据。"
}

$contentLines = @(
    "# Research Rollback Drill Record",
    "",
    "- 时间: $timestamp",
    "- 模式: $mode",
    "- 当前提交: $currentCommit ($shortCommit)",
    "- 目标回滚提交: $previousGoodCommitDisplay",
    "",
    "## Drill Scope",
    "",
    "- 目标链路: ``create session -> confirm -> runtime -> interrupt -> resume -> final``",
    "- 重点对象: ``research_sessions`` / ``research_events`` / ``research_artifacts``、Celery ``research,export`` 队列、frontend research workbench",
    "- 当前门禁:",
    "  - ``RESEARCH_GATE_MIN_QUALITY_SCORE=$qualityGate``",
    "  - ``RESEARCH_GATE_MAX_P95_MS=$latencyGate``",
    "  - ``RESEARCH_GATE_MAX_SESSION_COST_USD=$costGate``",
    "",
    "## Preconditions",
    "",
    "- 已确认 ``scripts/start_all.ps1``、``backend``、``frontend``、``full-refactor-deep-research`` 存在",
    "- 已确认本次演练不执行破坏性 checkout / reset；如需真实回滚，必须人工审批",
    "",
    "## Planned Rollback Steps",
    "",
    "1. 冻结新的 research 会话入口，避免新增 session 进入 ``research`` / ``export`` 队列。",
    "2. 记录当前提交、门禁阈值、队列/服务状态，并导出最近一次 ``research_rollback_drill.ps1`` 记录。",
    "3. 备份 ``research_sessions`` / ``research_events`` / ``research_artifacts`` 的最新快照与关键工件。",
    "4. 如需真实回滚，切换到最近一次 research 发布基线 commit，并重新安装依赖 / 重启 backend、frontend、Celery。",
    "5. 运行最小回归：``POST /api/v1/research/sessions``、``GET /api/v1/research/sessions/{session_id}/artifacts``、frontend typecheck / build。",
    "6. 校验 planner、interrupt / resume、metrics / gate 工件、导出链路与启动脚本状态。",
    "7. 若回滚验证通过，再解除冻结；若失败，保持冻结并进入人工处置。",
    "",
    "## Execute Notes",
    "",
    "- 本次脚本模式: $mode",
    "- 真实回滚需要人工审批后执行 ``git checkout <previous-good-commit>`` 或等价方案",
    "- 本次脚本只生成演练记录，不修改 git 工作树，不停止服务，不删除数据",
    "",
    "## Result",
    "",
    "- 记录文件已生成: ``$RecordPath``",
    "- 结论: $resultSummary"
)

Set-Content -LiteralPath $RecordPath -Value $contentLines -Encoding utf8
Write-Host "Research rollback drill record written to: $RecordPath"
