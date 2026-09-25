$ErrorActionPreference = "Stop"

$venvPath = Join-Path $PSScriptRoot ".venv"
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3 -m venv $venvPath
    } else {
        $systemPython = Get-Command python -ErrorAction Stop
        & $systemPython.Source -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python virtual environment." }
}

Set-Location $PSScriptRoot
& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }

& $pythonExe -m uvicorn main:app --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) { throw "RepurposeAI exited with an error." }
