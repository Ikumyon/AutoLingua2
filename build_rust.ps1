param([switch]$Run)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$repoRoot = $PSScriptRoot
$pythonExe = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Project Python was not found: $pythonExe"
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw 'cargo was not found in PATH.'
}

$previousPython = $env:PYO3_PYTHON
$previousUtf8 = $env:PYTHONUTF8
Push-Location -LiteralPath $repoRoot
try {
    $env:PYO3_PYTHON = $pythonExe
    $env:PYTHONUTF8 = '1'

    Write-Host '[1/3] Building the native extension...'
    & cargo build --release --locked --manifest-path crates/autolingua2-native/Cargo.toml
    if ($LASTEXITCODE -ne 0) { throw 'Native extension build failed.' }

    Write-Host '[2/3] Installing the development extension...'
    $nativeDir = Join-Path $repoRoot 'build/native'
    New-Item -ItemType Directory -Force -Path $nativeDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot 'crates/autolingua2-native/target/release/autolingua2_native.dll') `
        -Destination (Join-Path $nativeDir 'autolingua2_native.pyd') -Force

    Write-Host '[3/3] Building the launcher...'
    & cargo build --release --locked --manifest-path crates/launcher/Cargo.toml
    if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed.' }

    Write-Host 'Rust build complete.'
    if ($Run) {
        $launcher = Join-Path $repoRoot 'crates/launcher/target/release/autolingua-launcher.exe'
        & $launcher --development-root $repoRoot
    }
}
finally {
    $env:PYO3_PYTHON = $previousPython
    $env:PYTHONUTF8 = $previousUtf8
    Pop-Location
}
