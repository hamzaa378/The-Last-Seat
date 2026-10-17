# Start database-backed payment processing and hold expiration without RabbitMQ.
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
$python = '.\.venv313\Scripts\python.exe'
if (!(Test-Path $python)) { Write-Error 'Missing .venv313. See docs/STREAMLIT_GUIDE.md.'; exit 1 }
$secure = Read-Host 'PostgreSQL tickets password' -AsSecureString
$plain = [System.Net.NetworkCredential]::new('', $secure).Password
$encoded = [System.Uri]::EscapeDataString($plain)
$env:DATABASE_URL = "postgresql://tickets:$encoded@127.0.0.1:5432/tickets"
Remove-Variable secure, plain, encoded
$env:REDIS_ENABLED = '0'
& $python -c 'from app.database import start_pool; from worker.run import reconciliation_loop; start_pool(); reconciliation_loop()'
