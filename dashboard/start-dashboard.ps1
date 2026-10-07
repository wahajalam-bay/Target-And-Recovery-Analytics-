# Starts the Propone Target & Recovery dashboard.
# Usage:  powershell -ExecutionPolicy Bypass -File "D:\Claude Work\dashboard\start-dashboard.ps1"
#         or double-click "D:\Claude Work\Start Dashboard.bat"
#
# The frontend is compiled once (a few seconds) and served by the backend on port 8000,
# so the browser loads one small bundle instead of ~3,000 dev-server modules.
# Add -Dev to also run the Vite dev server on :5173 for frontend development.
param([switch]$Dev, [switch]$Tunnel)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

if (-not (Test-Path (Join-Path $backend '.env'))) {
    Write-Host "Missing backend\.env - copy backend\.env.example to backend\.env and add the Redshift credentials." -ForegroundColor Red
    exit 1
}

# First-run setup
if (-not (Test-Path (Join-Path $backend '.venv'))) {
    Write-Host 'Creating Python environment...'
    python -m venv (Join-Path $backend '.venv')
    & (Join-Path $backend '.venv\Scripts\pip.exe') install -q -r (Join-Path $backend 'requirements.txt')
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'Installing frontend packages...'
    Push-Location $frontend; npm install; Pop-Location
}

# Build the frontend when sources are newer than the last build
$dist = Join-Path $frontend 'dist\index.html'
$newest = Get-ChildItem (Join-Path $frontend 'src') -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not (Test-Path $dist) -or $newest.LastWriteTime -gt (Get-Item $dist).LastWriteTime) {
    Write-Host 'Building frontend...' -NoNewline
    Push-Location $frontend
    & npm.cmd run build -- --logLevel error | Out-Null
    Pop-Location
    Write-Host ' done'
}

# Stop anything already running on the dashboard ports (including orphaned children).
foreach ($port in 8000, 5173) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        $owner = $_.OwningProcess
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $owner" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Start-Process powershell -WindowStyle Minimized -ArgumentList @(
    '-NoExit', '-Command',
    "`$host.UI.RawUI.WindowTitle = 'Dashboard :8000'; Set-Location '$backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
if ($Dev) {
    Start-Process powershell -WindowStyle Minimized -ArgumentList @(
        '-NoExit', '-Command',
        "`$host.UI.RawUI.WindowTitle = 'Dashboard dev server :5173'; Set-Location '$frontend'; npm run dev")
}

Write-Host 'Waiting for the dashboard...' -NoNewline
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-RestMethod http://127.0.0.1:8000/api/health -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep 1; Write-Host '.' -NoNewline }
}
Write-Host ''
Write-Host 'Dashboard:  http://127.0.0.1:8000' -ForegroundColor Green
Write-Host 'API docs:   http://127.0.0.1:8000/docs' -ForegroundColor Green
if ($Dev) { Write-Host 'Dev server: http://127.0.0.1:5173' -ForegroundColor Yellow }
Start-Process 'http://127.0.0.1:8000'

if ($Tunnel) {
    # Public https link through Cloudflare (the dashboard login in backend\.env protects it).
    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cf) { $cf = Get-ChildItem "$env:ProgramFiles*\cloudflared*\cloudflared.exe","$env:LOCALAPPDATA\Microsoft\WinGet\Packages\*cloudflared*\cloudflared.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 }
    if (-not $cf) { Write-Host 'cloudflared is not installed: winget install Cloudflare.cloudflared' -ForegroundColor Red; exit 1 }
    $log = Join-Path $root 'tunnel.log'
    if (Test-Path $log) { Remove-Item $log -Force }
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
    $cfPath = if ($cf.PSObject.Properties['Source'] -and $cf.Source) { $cf.Source } else { $cf.FullName }
    Start-Process -WindowStyle Minimized -FilePath $cfPath -ArgumentList 'tunnel','--url','http://127.0.0.1:8000','--logfile',$log,'--loglevel','info'
    Write-Host 'Opening tunnel...' -NoNewline
    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url; $i++) {
        Start-Sleep 1; Write-Host '.' -NoNewline
        if (Test-Path $log) { $m = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if ($m) { $url = $m.Matches[0].Value } }
    }
    Write-Host ''
    if ($url) { Write-Host "Public link: $url" -ForegroundColor Cyan; Set-Content -Path (Join-Path $root 'tunnel-url.txt') -Value $url }
    else { Write-Host 'Tunnel did not report a URL; see tunnel.log' -ForegroundColor Yellow }
}
