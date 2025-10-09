Param(
  [string]$VenvPath = '.venv',
  [string]$Requirements = 'ci/requirements.ci.txt',
  [string]$TestTarget = 'tests'
)

# environment snapshot
Write-Output "[run-ci] Environment snapshot start"
python --version 2>$null | ForEach-Object { Write-Output "[run-ci] python: $_" }
python -c "import sys,platform; print(platform.platform())" 2>$null | ForEach-Object { Write-Output "[run-ci] platform: $_" }
python -m pip --version 2>$null | ForEach-Object { Write-Output "[run-ci] pip: $_" }
Write-Output "[run-ci] Environment snapshot end"

# Python version guard
$ciPinnedPython = '3.13'  # update to whatever CI uses
try {
  $localPy = python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
} catch {
  Write-Warning "Unable to determine local Python version"
  $localPy = ''
}
if ($localPy -and ($localPy -notlike "$ciPinnedPython*")) {
  Write-Warning "Local Python version $localPy does not match CI pinned $ciPinnedPython. Proceeding, but consider using the CI Python version for parity."
}

# create venv if missing
if (-not (Test-Path $VenvPath)) {
  Write-Output "[run-ci] Creating virtual environment at $VenvPath"
  python -m venv $VenvPath
}

# activate in-process for this PowerShell session
$activate = Join-Path $VenvPath 'Scripts\Activate.ps1'
if (Test-Path $activate) {
  Write-Output "[run-ci] Activating venv: $activate"
  . $activate
} else {
  Write-Error "Activation script not found at $activate"
  exit 1
}

# upgrade pip and install pinned CI deps if lockfile exists
Write-Output "[run-ci] Upgrading pip and installing CI deps"
python -m pip install --upgrade pip setuptools wheel
if (Test-Path $Requirements) {
  python -m pip install -r $Requirements
} else {
  Write-Output "[run-ci] Warning: $Requirements not found, skipping install"
}

# show installed packages quick list
Write-Output "[run-ci] Installed packages (top 50)"
python -m pip list --format=columns | Select-Object -First 50 | ForEach-Object { Write-Output $_ }

# run tests (runs tests/ by default; also accepts -TestTarget to add other paths)
Write-Output "[run-ci] Running pytest on tests and $TestTarget"
python -m pytest tests $TestTarget -q
