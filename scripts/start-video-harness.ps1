[CmdletBinding()]
param(
  [int]$Port = 3080,
  [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Import-DotEnv {
  param([string]$Path)

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    return
  }

  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      continue
    }
    $name = $Matches[1]
    if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name, "Process"))) {
      continue
    }
    $value = $Matches[2].Trim()
    if ($value.Length -ge 2) {
      $quoted = ($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))
      if ($quoted) {
        $value = $value.Substring(1, $value.Length - 2)
      }
    }
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
  }
}

function ConvertTo-ProxyUri {
  param([string]$Value)

  if ([string]::IsNullOrWhiteSpace($Value)) {
    return $null
  }
  if ($Value -match '^[A-Za-z][A-Za-z0-9+.-]*://') {
    return $Value
  }
  return "http://$Value"
}

function Import-WindowsUserProxy {
  if ($env:OS -ne "Windows_NT") {
    return
  }
  if (-not [string]::IsNullOrWhiteSpace($env:HTTP_PROXY) -or -not [string]::IsNullOrWhiteSpace($env:HTTPS_PROXY)) {
    return
  }

  $internetSettings = Get-ItemProperty -LiteralPath "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
  if ($null -eq $internetSettings -or $internetSettings.ProxyEnable -ne 1 -or [string]::IsNullOrWhiteSpace($internetSettings.ProxyServer)) {
    return
  }

  $httpProxy = $null
  $httpsProxy = $null
  $proxyServer = [string]$internetSettings.ProxyServer
  if ($proxyServer.Contains(';')) {
    foreach ($entry in $proxyServer.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)) {
      $pair = $entry.Split('=', 2)
      if ($pair.Length -ne 2) {
        continue
      }
      switch ($pair[0].Trim().ToLowerInvariant()) {
        "http" { $httpProxy = ConvertTo-ProxyUri $pair[1].Trim() }
        "https" { $httpsProxy = ConvertTo-ProxyUri $pair[1].Trim() }
      }
    }
  } else {
    $httpProxy = ConvertTo-ProxyUri $proxyServer
    $httpsProxy = $httpProxy
  }

  if (-not [string]::IsNullOrWhiteSpace($httpProxy)) {
    $env:HTTP_PROXY = $httpProxy
    $env:http_proxy = $httpProxy
  }
  if (-not [string]::IsNullOrWhiteSpace($httpsProxy)) {
    $env:HTTPS_PROXY = $httpsProxy
    $env:https_proxy = $httpsProxy
  }
  if (-not [string]::IsNullOrWhiteSpace($httpProxy) -or -not [string]::IsNullOrWhiteSpace($httpsProxy)) {
    $env:NODE_USE_ENV_PROXY = "1"
    if ([string]::IsNullOrWhiteSpace($env:NO_PROXY)) {
      $env:NO_PROXY = "127.0.0.1,localhost"
    }
    Write-Host "DeepSeek Harness will use the Windows user proxy."
  }
}

if (-not [string]::IsNullOrWhiteSpace($EnvFile)) {
  Import-DotEnv ([string](Resolve-Path -LiteralPath $EnvFile))
} else {
  Import-DotEnv (Join-Path $repoRoot ".env")
  if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
    Import-DotEnv (Join-Path (Split-Path -Parent $repoRoot) "cuti-video-agent\.env")
  }
}

Import-WindowsUserProxy

if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
  throw "OPENAI_API_KEY is missing. Set it in the process environment or the repository .env file."
}

if ([string]::IsNullOrWhiteSpace($env:VIDEO_RUNTIME_URL)) {
  $env:VIDEO_RUNTIME_URL = "http://127.0.0.1:8001"
}

Push-Location $repoRoot
try {
  & pnpm dsh web --patch packages/bundle/video-agent/cordis.patch.yml --no-open --port $Port
  if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
  }
} finally {
  Pop-Location
}
