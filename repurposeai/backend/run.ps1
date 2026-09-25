$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot ".venv"
$pythonExe = "C:\Users\Ashish Jha\AppData\Local\Programs\Python\Python313\python.exe"

if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment with Python 3.13..."
    & $pythonExe -m venv $venvPath
}

& (Join-Path $venvPath "Scripts\Activate.ps1")

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "Environment ready. Run the app with:"
Write-Host "  python -m uvicorn main:app --reload --port 8000"
Write-Host "or set GROQ_API_KEY before starting:"
Write-Host "  `$env:GROQ_API_KEY = 'gsk_your_key_here'"

$env:GROQ_API_KEY = $env:GROQ_API_KEY
python -m uvicorn main:app --reload --port 8000
