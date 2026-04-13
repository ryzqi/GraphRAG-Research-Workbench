param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$issues = New-Object System.Collections.Generic.List[string]

function Add-Issue {
    param([Parameter(Mandatory = $true)][string]$Message)

    $issues.Add($Message) | Out-Null
}

function Resolve-RepoPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    return Join-Path $repoRoot $RelativePath
}

function Assert-FileExists {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $absolutePath = Resolve-RepoPath -RelativePath $RelativePath
    if (-not (Test-Path -LiteralPath $absolutePath)) {
        Add-Issue "missing required file: $RelativePath"
    }
}

function Assert-FileDoesNotMatch {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$RuleName
    )

    $absolutePath = Resolve-RepoPath -RelativePath $RelativePath
    if (-not (Test-Path -LiteralPath $absolutePath)) {
        Add-Issue "scan target missing: $RelativePath"
        return
    }

    $matches = Select-String -Path $absolutePath -Pattern $Pattern
    foreach ($match in $matches) {
        Add-Issue "${RelativePath}:$($match.LineNumber) violates $RuleName"
    }
}

$loopbackIpv4 = "127" + ".0.0.1"
$loopbackHost = "local" + "host"
$legacyFrontendEnvAlias = "VITE" + "_API_BASE_URL"
$defaultMinioCredential = "minio" + "admin"
$replaceMarker = "REPLACE" + "_ME"
$defaultSearxngSecret = "change-me-" + "searxng-secret"
$fixedProxyAddress = "192" + ".168.3.52:7890"
$ambiguousComposeScope = "development" + " and deployment"

$requiredFiles = @(
    "docs/ops/config-and-secrets.md",
    "infra/env/dev.env.example",
    "infra/env/prod.env.example",
    "infra/podman-compose.base.yml",
    "infra/podman-compose.dev.yml",
    "infra/podman-compose.prod.example.yml",
    ".gitleaks.toml",
    "backend/tests/test_no_duplicate_provider_registry.py",
    "backend/tests/test_policy_manifest_integrity.py",
    "frontend/scripts/check-public-runtime-config.mjs"
)

foreach ($relativePath in $requiredFiles) {
    Assert-FileExists -RelativePath $relativePath
}

$sharedAndProdTargets = @(
    ".env.example",
    "README.md",
    "scripts/start_all.ps1",
    "scripts/verify_quickstart.ps1",
    "infra/podman-compose.yml",
    "infra/podman-compose.base.yml",
    "infra/podman-compose.prod.example.yml",
    "infra/searxng/config/settings.yml"
)

foreach ($relativePath in $sharedAndProdTargets) {
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($loopbackIpv4)) `
        -RuleName "hardcoded loopback ipv4"
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($loopbackHost)) `
        -RuleName "hardcoded loopback host"
}

$dangerousDefaultTargets = @(
    ".env.example",
    "README.md",
    "infra/podman-compose.yml",
    "infra/podman-compose.base.yml",
    "infra/podman-compose.prod.example.yml",
    "infra/searxng/config/settings.yml"
)

foreach ($relativePath in $dangerousDefaultTargets) {
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($defaultMinioCredential)) `
        -RuleName "dangerous default credential"
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($replaceMarker)) `
        -RuleName "placeholder secret marker"
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($defaultSearxngSecret)) `
        -RuleName "dangerous searxng secret"
}

$legacyAliasTargets = @(
    ".env.example",
    "README.md",
    "scripts/start_all.ps1"
)

foreach ($relativePath in $legacyAliasTargets) {
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($legacyFrontendEnvAlias)) `
        -RuleName "legacy frontend env alias"
}

$proxyTargets = @(
    "README.md",
    "infra/podman-compose.yml",
    "infra/podman-compose.base.yml",
    "infra/podman-compose.prod.example.yml",
    "infra/searxng/config/settings.yml"
)

foreach ($relativePath in $proxyTargets) {
    Assert-FileDoesNotMatch `
        -RelativePath $relativePath `
        -Pattern ([regex]::Escape($fixedProxyAddress)) `
        -RuleName "fixed host proxy address"
}

Assert-FileDoesNotMatch `
    -RelativePath "infra/podman-compose.yml" `
    -Pattern ([regex]::Escape($ambiguousComposeScope)) `
    -RuleName "ambiguous compose scope wording"

if ($issues.Count -gt 0) {
    Write-Host "[FAIL] hardcoded config audit detected $($issues.Count) issue(s)." -ForegroundColor Red
    foreach ($issue in $issues) {
        Write-Host " - $issue" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "[PASS] hardcoded config audit passed." -ForegroundColor Green
exit 0
