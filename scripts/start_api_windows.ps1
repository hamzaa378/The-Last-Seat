# Start FastAPI without Docker. Does not modify PostgreSQL or the database schema.
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
$python = '.\.venv313\Scripts\python.exe'
if (!(Test-Path $python)) { Write-Error 'Missing .venv313. See docs/STREAMLIT_GUIDE.md.'; exit 1 }
$secure = Read-Host 'PostgreSQL tickets password' -AsSecureString
$plain = [System.Net.NetworkCredential]::new('', $secure).Password
$encoded = [System.Uri]::EscapeDataString($plain)
$env:DATABASE_URL = "postgresql://tickets:$encoded@127.0.0.1:5432/tickets"
Remove-Variable secure, plain, encoded
$env:REDIS_ENABLED = '0'
if (-not $env:JWT_SECRET) {
    $env:JWT_SECRET = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    Write-Host 'Created a temporary JWT secret. Existing login tokens will expire when the API restarts.'
}
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
