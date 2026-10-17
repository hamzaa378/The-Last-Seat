# Start the Streamlit student portal. No PostgreSQL password is required.
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
$python = '.\.venv313\Scripts\python.exe'
if (!(Test-Path $python)) { Write-Error 'Missing .venv313. See docs/STREAMLIT_GUIDE.md.'; exit 1 }
if (-not $env:TICKET_API_URL) { $env:TICKET_API_URL = 'http://127.0.0.1:8000' }
& $python -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
