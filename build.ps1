param(
    [string]$Zig = 'zig',
    [string]$Python = 'python',
    [switch]$Bundle
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (Test-Path -LiteralPath 'nv_candidates.exe') {
        throw 'nv_candidates.exe already exists. Build from a fresh source directory.'
    }
    if ($Bundle -and (Test-Path -LiteralPath 'dist')) {
        throw 'dist already exists. Build from a fresh source directory.'
    }

    & $Zig c++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -Werror candidate_detection.cpp -o nv_candidates.exe
    if ($LASTEXITCODE -ne 0) { throw 'C++ compilation failed.' }

    if ($Bundle) {
        & $Python -m PyInstaller --onedir --name DiamondNV --add-binary 'nv_candidates.exe:.' analyze_scans.py
        if ($LASTEXITCODE -ne 0) { throw 'Windows bundle build failed.' }
    }
}
finally {
    Pop-Location
}
