# Object Trace Visualizer Project 

## Reproduce Windows smoke CI locally

Run the local CI helper (Windows PowerShell):

`powershell
.\tools\run-ci.ps1
`

This mirrors the GitHub Actions windows-smoke job: it creates a venv, installs pinned CI deps from ci/requirements.ci.txt, then runs tests.

