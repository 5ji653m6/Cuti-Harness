[CmdletBinding()]
param(
  [string]$Python = "python",
  [int]$Port = 18080,
  [string]$RuntimeUrl = "http://127.0.0.1:8001",
  [string]$StorageDirectory = ""
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($StorageDirectory)) {
  $StorageDirectory = Join-Path $repoRoot "services/video-runtime/data/uploads"
}
$env:STORAGE_BACKEND = "local"
$env:LOCAL_STORAGE_DIR = [IO.Path]::GetFullPath($StorageDirectory)
$env:PUBLIC_BASE_URL = $RuntimeUrl
$env:PYTHONIOENCODING = "utf-8"
Push-Location (Join-Path $repoRoot "services/media-service")
try {
  & $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1
} finally {
  Pop-Location
}
