# ── VoicOps Validator Tools Installer ──
# Downloads hadolint (Dockerfile linter) and terraform CLI into .\bin\
# Run: powershell -ExecutionPolicy Bypass -File install_validators.ps1

$ErrorActionPreference = "Stop"
$BIN_DIR = Join-Path $PSScriptRoot "bin"

if (!(Test-Path $BIN_DIR)) {
    New-Item -ItemType Directory -Path $BIN_DIR -Force | Out-Null
}

Write-Host ""
Write-Host "  VoicOps Validator Tools Installer" -ForegroundColor Cyan
Write-Host "  ─────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# ── hadolint ──
$HADOLINT_URL = "https://github.com/hadolint/hadolint/releases/download/v2.12.0/hadolint-Windows-x86_64.exe"
$HADOLINT_PATH = Join-Path $BIN_DIR "hadolint.exe"

if (Test-Path $HADOLINT_PATH) {
    $testResult = & $HADOLINT_PATH --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] hadolint already installed" -ForegroundColor Green
    } else {
        Write-Host "  [!!] hadolint exists but is corrupt — re-downloading" -ForegroundColor Yellow
        Remove-Item $HADOLINT_PATH -Force
    }
}

if (!(Test-Path $HADOLINT_PATH)) {
    Write-Host "  [..] Downloading hadolint v2.12.0..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $HADOLINT_URL -OutFile $HADOLINT_PATH -UseBasicParsing
        $testResult = & $HADOLINT_PATH --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] hadolint installed successfully" -ForegroundColor Green
        } else {
            Write-Host "  [!!] hadolint download may be corrupt — try again" -ForegroundColor Red
        }
    } catch {
        Write-Host "  [FAIL] hadolint download failed: $_" -ForegroundColor Red
        if (Test-Path $HADOLINT_PATH) { Remove-Item $HADOLINT_PATH -Force }
    }
}

# ── terraform ──
$TF_URL = "https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_windows_amd64.zip"
$TF_ZIP = Join-Path $BIN_DIR "terraform.zip"
$TF_PATH = Join-Path $BIN_DIR "terraform.exe"

if (Test-Path $TF_PATH) {
    $testResult = & $TF_PATH version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] terraform already installed" -ForegroundColor Green
    } else {
        Write-Host "  [!!] terraform exists but is corrupt — re-downloading" -ForegroundColor Yellow
        Remove-Item $TF_PATH -Force
    }
}

if (!(Test-Path $TF_PATH)) {
    Write-Host "  [..] Downloading terraform v1.9.8..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $TF_URL -OutFile $TF_ZIP -UseBasicParsing
        Write-Host "  [..] Extracting terraform..." -ForegroundColor Yellow
        Expand-Archive -Path $TF_ZIP -DestinationPath $BIN_DIR -Force
        Remove-Item $TF_ZIP -Force
        $testResult = & $TF_PATH version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] terraform installed successfully" -ForegroundColor Green
        } else {
            Write-Host "  [!!] terraform install may be corrupt — try again" -ForegroundColor Red
        }
    } catch {
        Write-Host "  [FAIL] terraform download failed: $_" -ForegroundColor Red
        if (Test-Path $TF_ZIP) { Remove-Item $TF_ZIP -Force }
        if (Test-Path $TF_PATH) { Remove-Item $TF_PATH -Force }
    }
}

# ── PATH hint ──
Write-Host ""
Write-Host "  Tools installed to: $BIN_DIR" -ForegroundColor DarkGray
Write-Host "  To add to PATH for the current session:" -ForegroundColor DarkGray
Write-Host "    `$env:PATH = `"$BIN_DIR;`$env:PATH`"" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Then start VoicOps:" -ForegroundColor DarkGray
Write-Host "    uvicorn app.main:app --reload --port 8000" -ForegroundColor Cyan
Write-Host ""
