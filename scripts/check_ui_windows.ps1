# Safe read-only startup checks, no database writes or secrets.
$ErrorActionPreference = 'Continue'
Write-Host 'Checking The Last Seat local services...'
try {
    $ready = Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 5
    if ($ready.status -eq 'ready') { Write-Host '[PASS] FastAPI and PostgreSQL are ready' }
    else { Write-Warning '[CHECK] Unexpected readiness response' }
} catch { Write-Warning '[FAIL] FastAPI not responding at port 8000. Start the API first.' }
try {
    $docs = Invoke-WebRequest 'http://127.0.0.1:8000/docs' -UseBasicParsing -TimeoutSec 5
    if ($docs.Content -like '*booking-guide*') { Write-Host '[PASS] Enhanced Swagger is installed' }
    else { Write-Warning '[CHECK] Swagger exists, but the v1.2 banner was not found' }
} catch { Write-Warning '[FAIL] API documentation unreachable.' }
try {
    $page = Invoke-WebRequest 'http://127.0.0.1:8501' -UseBasicParsing -TimeoutSec 5
    if ($page.StatusCode -eq 200) { Write-Host '[PASS] Streamlit is responding at port 8501' }
} catch { Write-Warning '[FAIL] Streamlit not responding at port 8501. Start the frontend.' }
Write-Host 'Student portal: http://127.0.0.1:8501'
Write-Host 'API Explorer:   http://127.0.0.1:8000/docs'
