Set-StrictMode -Version Latest

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Found 'uv' CLI — using uv to run commands inside the project environment."

    uv sync
    uv add pyoxidizer

    Write-Host "Building random_move with PyOxidizer..."
    uv run pyoxidizer build

    if ($LASTEXITCODE -ne 0) {
        Write-Host "PyOxidizer build failed. Check pyoxidizer.bzl and build logs."
        exit $LASTEXITCODE
    }
    Write-Host "PyOxidizer build completed. See build/ for outputs."
} else {
    Write-Host "'uv' not found"
}