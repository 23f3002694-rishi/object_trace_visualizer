# Contributing

Run the local CI helper before opening a PR:

    .\tools\run-ci.ps1

Expected runtime: ~10–30s for tests and environment setup on a typical dev machine.

If CI fails on GitHub but passes locally, open an issue and include:
- the first 40 lines of .\tools\run-ci.ps1 output
- python --version and python -m pip --version
