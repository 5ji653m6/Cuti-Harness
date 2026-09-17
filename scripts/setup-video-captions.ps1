$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$installRoot = Join-Path $repoRoot ".runtime-deps/hyperframes"
& npm install --prefix $installRoot --no-audit --no-fund hyperframes@0.8.16 gsap@3.14.2
if ($LASTEXITCODE -ne 0) { throw "Caption runtime installation failed" }
& node (Join-Path $installRoot "node_modules/hyperframes/bin/hyperframes.mjs") browser ensure
if ($LASTEXITCODE -ne 0) { throw "Caption browser installation failed" }
