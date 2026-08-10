# VideoSeek — Nuitka standalone release build (Windows)
#
# Usage (from repo root, in conda env VideoSeek):
#   .\scripts\build_release.ps1
#   .\scripts\build_release.ps1 -Clean
#   .\scripts\build_release.ps1 -Zip   # also write dist\VideoSeek-<version>.zip
#
# Version source of truth: src\app\app_meta.py → "version"
#   QQ soft-release: set "1.0.88-beta.1" before building; promote to "1.0.88" for stable.
#   Do not write beta builds into the public version.json.
#
# Output: dist\main.dist\VideoSeek.exe (+ bundled deps)

[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Zip,
    [string]$Python = "",
    [string]$OutputDir = "dist",
    [string]$OutputFilename = "VideoSeek"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-RequiredPath([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Label`: $Path"
    }
}

function Copy-TreeForce([string]$Source, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $Source)) {
        throw "Copy source not found: $Source"
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $RepoRoot

Write-Step "Repo root: $RepoRoot"

if ($Python) {
    $PythonExe = (Resolve-Path -LiteralPath $Python).Path
} else {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        throw "python not found on PATH. Activate conda env VideoSeek or pass -Python <path-to-python.exe>"
    }
}

Write-Step "Python: $PythonExe"
& $PythonExe -m nuitka --version | Out-Host

Write-Step "Resolve app version (app_meta.py)"
$AppVersion = & $PythonExe -c "from src.app.app_meta import get_app_meta; print(get_app_meta()['version'])"
if ($LASTEXITCODE -ne 0 -or -not $AppVersion) {
    throw "Failed to read version from src.app.app_meta"
}
$AppVersion = ([string]$AppVersion).Trim()
Write-Host "App version: $AppVersion"

# Keep pyproject.toml in sync with app_meta (best-effort).
$Pyproject = Join-Path $RepoRoot "pyproject.toml"
if (Test-Path -LiteralPath $Pyproject) {
    $pyText = Get-Content -LiteralPath $Pyproject -Raw -Encoding UTF8
    $updated = [regex]::Replace(
        $pyText,
        '(?m)^version\s*=\s*"[^"]*"',
        "version = `"$AppVersion`""
    )
    if ($updated -ne $pyText) {
        Set-Content -LiteralPath $Pyproject -Value $updated -Encoding UTF8 -NoNewline
        Write-Host "Synced pyproject.toml version -> $AppVersion"
    }
}

Write-Step "Preflight checks"
Test-RequiredPath (Join-Path $RepoRoot "main.py") "entrypoint"
Test-RequiredPath (Join-Path $RepoRoot "icon.ico") "icon"
Test-RequiredPath (Join-Path $RepoRoot "config.json") "default config"
Test-RequiredPath (Join-Path $RepoRoot "vlc_lib") "vlc_lib"
Test-RequiredPath (Join-Path $RepoRoot "static") "static"
Test-RequiredPath (Join-Path $RepoRoot "resources") "resources"
Test-RequiredPath (Join-Path $RepoRoot "docs\for-agents.md") "Agent API doc"
Test-RequiredPath (Join-Path $RepoRoot "server\nginx\nginx.exe") "embedded nginx.exe"
Test-RequiredPath (Join-Path $RepoRoot "server\nginx\conf\nginx.conf") "nginx.conf"

$DistRoot = Join-Path $RepoRoot $OutputDir
$BundleDir = Join-Path $DistRoot "main.dist"

if ($Clean -and (Test-Path -LiteralPath $DistRoot)) {
    Write-Step "Cleaning $DistRoot"
    Remove-Item -LiteralPath $DistRoot -Recurse -Force
}

Write-Step "Running Nuitka (this may take a while)"
$NuitkaArgs = @(
    "-m", "nuitka",
    "--standalone",
    "--plugin-enable=pyside6",
    "--include-qt-plugins=multimedia",
    "--windows-console-mode=disable",
    "--output-dir=$OutputDir",
    "--output-filename=$OutputFilename",
    "--windows-icon-from-ico=icon.ico",
    "--include-data-file=config.json=config.json",
    "--include-package=yt_dlp",
    "--include-package=lancedb",
    "--include-package=pyarrow",
    "--include-package=fastapi",
    "--include-package=uvicorn",
    "--include-package=starlette",
    "--include-package=multipart",
    "--include-package=rookiepy",
    "--include-package=pillow_heif",
    "--include-package=qrcode",
    "--include-package=certifi",
    # Lazy-imported at runtime — force-include so Nuitka does not drop them.
    "--include-package=vlc",
    "--include-package=rapidocr_onnxruntime",
    # Non-.py package data: --include-package alone often omits these.
    "--include-package-data=rapidocr_onnxruntime",
    "--include-package-data=certifi",
    "--include-package-data=yt_dlp",
    "--include-data-dir=resources/rapidocr_onnxruntime=rapidocr_onnxruntime",
    "--include-package=onnxruntime",
    "--include-package=cv2",
    "--include-package=faiss",
    "--nofollow-import-to=yt_dlp.extractor.lazy_extractors",
    "--nofollow-import-to=transformers",
    "--nofollow-import-to=pytest,unittest",
    "--show-progress",
    "main.py"
)

& $PythonExe @NuitkaArgs
if ($LASTEXITCODE -ne 0) {
    throw "Nuitka failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $BundleDir)) {
    throw "Expected bundle directory not found: $BundleDir"
}

Write-Step "Copying runtime assets into $BundleDir"
Copy-TreeForce (Join-Path $RepoRoot "vlc_lib") (Join-Path $BundleDir "vlc_lib")
Copy-TreeForce (Join-Path $RepoRoot "static") (Join-Path $BundleDir "static")
Copy-TreeForce (Join-Path $RepoRoot "resources") (Join-Path $BundleDir "resources")
Copy-TreeForce (Join-Path $RepoRoot "server\nginx") (Join-Path $BundleDir "server\nginx")

# Drop machine-local nginx runtime junk; app recreates logs/temp and videos.conf.
$NginxBundle = Join-Path $BundleDir "server\nginx"
foreach ($junkName in @("logs", "temp")) {
    $junkPath = Join-Path $NginxBundle $junkName
    if (Test-Path -LiteralPath $junkPath) {
        Remove-Item -LiteralPath $junkPath -Recurse -Force
    }
}
$VideosConf = Join-Path $NginxBundle "conf\conf.d\videos.conf"
if (Test-Path -LiteralPath $VideosConf) {
    Remove-Item -LiteralPath $VideosConf -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $NginxBundle "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $NginxBundle "temp") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $NginxBundle "conf\conf.d") | Out-Null

$DocsDir = Join-Path $BundleDir "docs"
New-Item -ItemType Directory -Force -Path $DocsDir | Out-Null
Copy-Item -LiteralPath (Join-Path $RepoRoot "docs\for-agents.md") -Destination (Join-Path $DocsDir "for-agents.md") -Force

# Ensure RapidOCR config.yaml sits where Path(__file__).resolve() looks for it.
$RapidOcrConfigSrc = Join-Path $RepoRoot "resources\rapidocr_onnxruntime\config.yaml"
$RapidOcrConfigDst = Join-Path $BundleDir "rapidocr_onnxruntime\config.yaml"
if (Test-Path -LiteralPath $RapidOcrConfigSrc) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RapidOcrConfigDst) | Out-Null
    Copy-Item -LiteralPath $RapidOcrConfigSrc -Destination $RapidOcrConfigDst -Force
    Get-ChildItem -LiteralPath $BundleDir -Recurse -Directory -Filter "rapidocr_onnxruntime" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -LiteralPath $RapidOcrConfigSrc -Destination (Join-Path $_.FullName "config.yaml") -Force
    }
}

# Copy package data that Nuitka often drops even with --include-package.
Write-Step "Copying high-risk package data from site-packages"
$CertifiDir = & $PythonExe -c "import certifi; from pathlib import Path; print(Path(certifi.__file__).resolve().parent)"
if ($LASTEXITCODE -ne 0 -or -not $CertifiDir) {
    throw "Failed to resolve certifi package path from $PythonExe"
}
$CertifiDir = ([string]$CertifiDir).Trim()
$CertifiPem = Join-Path $CertifiDir "cacert.pem"
Test-RequiredPath $CertifiPem "certifi cacert.pem (env)"
$BundleCertifiDir = Join-Path $BundleDir "certifi"
New-Item -ItemType Directory -Force -Path $BundleCertifiDir | Out-Null
Copy-Item -LiteralPath $CertifiPem -Destination (Join-Path $BundleCertifiDir "cacert.pem") -Force
Get-ChildItem -LiteralPath $BundleDir -Recurse -Directory -Filter "certifi" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item -LiteralPath $CertifiPem -Destination (Join-Path $_.FullName "cacert.pem") -Force
}

Write-Step "Verifying bundle"
$ExePath = Join-Path $BundleDir "$OutputFilename.exe"
Test-RequiredPath $ExePath "executable"

$RequiredRelative = @(
    "config.json",
    "vlc_lib",
    "static\index.html",
    "resources",
    "resources\asr\silero_vad.onnx",
    "resources\rapidocr_onnxruntime\config.yaml",
    "rapidocr_onnxruntime\config.yaml",
    "certifi\cacert.pem",
    "docs\for-agents.md",
    "server\nginx\nginx.exe",
    "server\nginx\conf\nginx.conf"
)
foreach ($rel in $RequiredRelative) {
    Test-RequiredPath (Join-Path $BundleDir $rel) $rel
}

$LanceHints = @(
    (Join-Path $BundleDir "lancedb"),
    (Join-Path $BundleDir "_lancedb.pyd")
)
$LanceFound = $false
foreach ($hint in $LanceHints) {
    if (Test-Path -LiteralPath $hint) {
        $LanceFound = $true
        break
    }
}
$LancePyd = Get-ChildItem -LiteralPath $BundleDir -Recurse -Filter "_lancedb.pyd" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($LancePyd) {
    $LanceFound = $true
}
if (-not $LanceFound) {
    Write-Warning "Could not find lancedb binaries (_lancedb.pyd). Packaged search/index may fail until you add --include-package=lancedb manually."
}

$PyarrowDll = Get-ChildItem -LiteralPath $BundleDir -Recurse -Filter "arrow*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $PyarrowDll) {
    Write-Warning "Could not find pyarrow DLLs under $BundleDir. Lance search may fail at runtime."
}

Write-Step "Build complete"
$VersionStampPath = Join-Path $BundleDir "VERSION.txt"
Set-Content -LiteralPath $VersionStampPath -Value $AppVersion -Encoding ASCII -NoNewline
Write-Host "Bundle: $BundleDir" -ForegroundColor Green
Write-Host "Exe:    $ExePath" -ForegroundColor Green
Write-Host "Version:$AppVersion (also $VersionStampPath)" -ForegroundColor Green

if ($Zip) {
    Write-Step "Packaging zip"
    $ZipName = "VideoSeek-$AppVersion.zip"
    $ZipPath = Join-Path $DistRoot $ZipName
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Compress-Archive -Path (Join-Path $BundleDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal
    Write-Host "Zip:    $ZipPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "Release notes:" -ForegroundColor Yellow
Write-Host "  - Source of truth: src/app/app_meta.py version=$AppVersion"
Write-Host "  - QQ beta: use 1.0.x-beta.N in app_meta; do not publish to public version.json"
Write-Host "  - Stable: drop -beta.N, tag v$AppVersion, update OSS version.json"
Write-Host ""
Write-Host "Smoke test checklist:" -ForegroundColor Yellow
Write-Host "  1. Start VideoSeek.exe and import runtime resources (models + FFmpeg)"
Write-Host "  2. Sync a library -> confirm lance/ appears under user data"
Write-Host "  3. Text/image search returns hits"
Write-Host "  4. Subtitle library -> extract subtitles (RapidOCR config.yaml must load)"
Write-Host "  5. Download / HTTPS model fetch (certifi cacert.pem)"
Write-Host "  6. Enable Agent API -> GET http://127.0.0.1:8765/api/v1/health"
Write-Host "  7. Team server mode -> media nginx starts (bundle has server\nginx\nginx.exe)"
