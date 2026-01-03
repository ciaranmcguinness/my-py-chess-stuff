Set-StrictMode -Version Latest

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Found 'uv' CLI — using uv to run commands inside the project environment."

    uv sync
    uv add pyinstaller

    Write-Host "Building random_move with PyInstaller..."
    uv run pyinstaller random_move.py -f

    if ($LASTEXITCODE -ne 0) {
        Write-Host "pyinstaller build failed."
        exit $LASTEXITCODE
    }
    Write-Host "Build completed."
} else {
    Write-Host "'uv' not found"
}