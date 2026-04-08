Set-StrictMode -Version Latest

$script:UvAmbientEnvVarNames = @(
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "PYTHONHOME",
    "PYTHONPATH"
)

function Get-UvIsolationScriptLines {
    param(
        [string]$ProjectEnvironment = ".venv"
    )

    $lines = @()
    foreach ($name in $script:UvAmbientEnvVarNames) {
        $lines += "Remove-Item Env:$name -ErrorAction SilentlyContinue"
    }

    $lines += "`$env:UV_NO_ACTIVE = '1'"
    if ($ProjectEnvironment) {
        $escapedProjectEnvironment = $ProjectEnvironment.Replace("'", "''")
        $lines += "`$env:UV_PROJECT_ENVIRONMENT = '$escapedProjectEnvironment'"
    }

    return $lines
}

function Invoke-UvIsolated {
    param(
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$ProjectEnvironment = ".venv"
    )

    $savedEnv = @{}
    foreach ($name in ($script:UvAmbientEnvVarNames + @("UV_NO_ACTIVE", "UV_PROJECT_ENVIRONMENT"))) {
        $savedEnv[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    $script:LastUvExitCode = 0
    Push-Location $WorkingDirectory
    try {
        foreach ($name in $script:UvAmbientEnvVarNames) {
            Remove-Item -Path ("Env:" + $name) -ErrorAction SilentlyContinue
        }

        $env:UV_NO_ACTIVE = "1"
        if ($ProjectEnvironment) {
            $env:UV_PROJECT_ENVIRONMENT = $ProjectEnvironment
        }
        else {
            Remove-Item -Path "Env:UV_PROJECT_ENVIRONMENT" -ErrorAction SilentlyContinue
        }

        $output = & uv @Arguments 2>&1
        $script:LastUvExitCode = $LASTEXITCODE
        return @($output)
    }
    finally {
        Pop-Location

        foreach ($name in $savedEnv.Keys) {
            $value = $savedEnv[$name]
            if ($null -eq $value) {
                Remove-Item -Path ("Env:" + $name) -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -Path ("Env:" + $name) -Value $value
            }
        }
    }
}
