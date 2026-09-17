[CmdletBinding()]
param(
  [string[]]$CredentialEnvFiles = @(),
  [string]$Python = "python",
  [int]$Port = 8001,
  [string]$MediaServiceUrl = "http://127.0.0.1:18080",
  [string]$StorageDirectory = ""
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
# Import credentials first, then apply this local service topology explicitly.
foreach ($envFile in $CredentialEnvFiles) {
  foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      $envName = $Matches[1]
      $envValue = $Matches[2].Trim()
      if ($envValue.Length -ge 2 -and (($envValue.StartsWith('"') -and $envValue.EndsWith('"')) -or ($envValue.StartsWith("'") -and $envValue.EndsWith("'")))) {
        $envValue = $envValue.Substring(1, $envValue.Length - 2)
      }
      [Environment]::SetEnvironmentVariable($envName, $envValue, 'Process')
    }
  }
}
$env:MEDIA_SERVICE_URL = $MediaServiceUrl
$env:VIDEO_STAGED_PLANNING_ENABLED = "true"
$env:VIDEO_CONTINUOUS_PLAN_PATCH_ENABLED = "true"
$env:PUBLIC_BASE_URL = "http://127.0.0.1:$Port"
$env:STORAGE_BACKEND = "local"
if ([string]::IsNullOrWhiteSpace($StorageDirectory)) {
  $StorageDirectory = Join-Path $repoRoot "services/video-runtime/data/uploads"
}
$env:LOCAL_STORAGE_DIR = [IO.Path]::GetFullPath($StorageDirectory)
$env:PYTHONIOENCODING = "utf-8"
$env:ACCOUNT_BACKEND = "env"
if ([string]::IsNullOrWhiteSpace($env:VIDEO_CAPABILITY_GRANT_SECRET)) {
  $env:VIDEO_CAPABILITY_GRANT_SECRET = "video-harness-local-development-grant-secret"
}
# Fail before accepting paid builds when the media service is unreachable.
$null = Invoke-RestMethod -Uri "$($MediaServiceUrl.TrimEnd('/'))/readyz" -TimeoutSec 10
Push-Location (Join-Path $repoRoot "services/video-runtime")
try {
  & $Python -m uvicorn app.video_runtime.standalone:app --host 127.0.0.1 --port $Port
} finally {
  Pop-Location
}
