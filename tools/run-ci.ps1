Param(
  [string]$VenvPath = '.venv',
  [string]$Requirements = 'ci/requirements.ci.txt',
  [string]$TestTarget = 'tests'
)

# create venv if missing
if (-not (Test-Path $VenvPath)) {
  python -m venv $VenvPath
}

# activate in-process for this PowerShell session
$activate = Join-Path $VenvPath 'Scripts\Activate.ps1'
if (Test-Path $activate) { . $activate } else { Write-Error "Activation script not found at $activate"; exit 1 }

# upgrade pip and install pinned CI deps if lockfile exists
python -m pip install --upgrade pip setuptools wheel
if (Test-Path $Requirements) {
  python -m pip install -r $Requirements
} else {
  Write-Output "Warning: $Requirements not found, skipping install"
}

# run tests (runs tests/ by default; also accepts -TestTarget to add other paths)
python -m pytest tests $TestTarget -q

