<#
Build a Windows EXE for `random_move.py` using Nuitka.

This script prefers the `uv` project environment manager if available.
If `uv` is not found it falls back to creating a regular `venv` and activating it.

Run in an elevated PowerShell if you need to install system-wide build tools.
#>

Set-StrictMode -Version Latest

function Run-Command($cmd) {
    Write-Host "> $cmd"
    & cmd /c $cmd
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Found 'uv' CLI — using uv to run commands inside the project environment."

    # Ensure pip is up-to-date inside the uv environment
    uv run python -m pip install --upgrade pip
    uv run pip install nuitka

    Write-Host "Building random_move.exe with Nuitka (standalone, onefile)..."
    uv run python -m nuitka --standalone --onefile --output-dir=dist --remove-output random_move.py

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed. Try building without --onefile for debugging:"
        Write-Host "uv run python -m nuitka --standalone --output-dir=dist random_move.py"
        exit $LASTEXITCODE
    }
    Write-Host "Built: dist\random_move.exe"
} else {
    Write-Host "'uv' not found — falling back to venv + pip."

    if (-Not (Test-Path -Path .venv)) {
        python -m venv .venv
    }

    # Activate the venv for the rest of the script
    $activate = Join-Path -Path $PWD -ChildPath ".venv\Scripts\Activate.ps1"
    if (Test-Path $activate) {
        & $activate
    } else {
        Write-Host "Could not find Activate.ps1; ensure the venv was created and PowerShell execution policy allows running scripts."
    }

    python -m pip install --upgrade pip
    pip install nuitka
    pip install -e . || pip install chess

    Write-Host "Building random_move.exe with Nuitka (standalone, onefile)..."
    python -m nuitka --standalone --onefile --output-dir=dist --remove-output random_move.py

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build failed. Try building without --onefile for debugging:"
        Write-Host "python -m nuitka --standalone --output-dir=dist random_move.py"
        exit $LASTEXITCODE
    }

    Write-Host "Built: dist\random_move.exe"
}
