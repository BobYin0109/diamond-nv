"""Compare the frozen C++ detector with raw peak ranking on synthetic XY scans."""

import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np


GRID = 70
STEP_UM = 0.36
TRUTHS_PER_FIELD = 10
FIELDS_PER_GROUP = 15
TOP = 50
MATCH_STEPS = 2
SEED = 642012
AMPLITUDES = (12, 24, 48)
CONDITIONS = ("uniform", "gradient", "clutter")
Y, X = np.mgrid[:GRID, :GRID]


def known_positions(rng):
    positions = []
    while len(positions) < TRUTHS_PER_FIELD:
        x, y = rng.uniform(5, GRID - 6, 2)
        if all((x - old_x) ** 2 + (y - old_y) ** 2 > (2 * MATCH_STEPS + 1) ** 2
               for old_x, old_y in positions):
            positions.append((float(x), float(y)))
    return np.array(positions)


def spot(x, y, sigma):
    return np.exp(-((X - x) ** 2 + (Y - y) ** 2) / (2 * sigma ** 2))


def simulate(rng, nominal_intensity, condition):
    positions = known_positions(rng)
    level = rng.uniform(70, 130)
    intensity = np.full((GRID, GRID), level)
    if condition != "uniform":
        direction = rng.uniform(0, 2 * np.pi)
        slope = ((X / (GRID - 1) - 0.5) * np.cos(direction)
                 + (Y / (GRID - 1) - 0.5) * np.sin(direction))
        intensity += level * 0.65 * slope
        for _ in range(3):
            x, y = rng.uniform(0, GRID - 1, 2)
            intensity += level * rng.uniform(0.15, 0.55) * spot(x, y, rng.uniform(4, 10))
    if condition == "clutter":
        for _ in range(4):
            x, y = rng.uniform(0, GRID - 1, 2)
            intensity += rng.uniform(20, 85) * spot(x, y, rng.uniform(2, 4))
        for _ in range(8):
            x, y = rng.integers(0, GRID, 2)
            intensity[y, x] += rng.uniform(35, 100)
        for _ in range(3):
            x, y = rng.uniform(0, GRID - 1, 2)
            intensity += rng.uniform(10, 55) * spot(x, y, rng.uniform(0.65, 1.15))
    for x, y in positions:
        amplitude = nominal_intensity * rng.uniform(0.8, 1.2)
        intensity += amplitude * spot(x, y, rng.uniform(0.65, 1.15))
    return rng.poisson(intensity), positions


def raw_peaks(image):
    selection = np.ones(image.shape, dtype=bool)
    padded = np.pad(image.astype(float), 1, constant_values=-np.inf)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == dx == 0:
                continue
            neighbor = padded[1 + dy:1 + dy + GRID, 1 + dx:1 + dx + GRID]
            if (dy, dx) < (0, 0):
                selection &= image > neighbor
            else:
                selection &= image >= neighbor
    ys, xs = np.where(selection)
    ranked = np.argsort(-image[ys, xs], kind="stable")[:TOP]
    return np.column_stack((xs[ranked], ys[ranked]))


def enhanced_peaks(executable, scratch, image):
    scan = scratch / "scan.csv"
    with scan.open("w", newline="", encoding="ascii") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(("x_um", "y_um", "z_um", "count_kcps"))
        writer.writerows((round(x * STEP_UM, 5), round(y * STEP_UM, 5), 0, image[y, x])
                         for y in range(GRID) for x in range(GRID))
    process = subprocess.run([str(executable), "scan.csv", "enhanced.csv"], cwd=scratch,
                             capture_output=True, check=True, text=True, encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(process.stdout)))[:TOP]
    return np.array([(float(row["x_um"]) / STEP_UM, float(row["y_um"]) / STEP_UM) for row in rows])


def matches(peaks, positions):
    if not len(peaks):
        return 0
    distance_squared = ((positions[:, None, :] - peaks[None, :, :]) ** 2).sum(axis=2)
    return int(np.count_nonzero((distance_squared <= MATCH_STEPS ** 2).any(axis=1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=Path(__file__).with_name("nv_candidates.exe"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    executable = args.exe.resolve()
    output = (args.out or Path(__file__).parent / f"simulation_{datetime.now():%H%M%S}").resolve()
    output.mkdir()
    rng = np.random.default_rng(SEED)
    per_field = []
    groups = []
    with tempfile.TemporaryDirectory(dir=output) as scratch:
        for condition in CONDITIONS:
            for amplitude in AMPLITUDES:
                first = len(per_field)
                for _ in range(FIELDS_PER_GROUP):
                    image, positions = simulate(rng, amplitude, condition)
                    raw = raw_peaks(image)
                    enhanced = enhanced_peaks(executable, Path(scratch), image)
                    assert len(raw) == len(enhanced) == TOP
                    per_field.append({
                        "condition": condition, "peak_amplitude_photons": amplitude,
                        "raw_found": matches(raw, positions), "enhanced_found": matches(enhanced, positions),
                    })
                block = per_field[first:]
                groups.append({
                    "condition": condition, "peak_amplitude_photons": amplitude,
                    "truths": len(block) * TRUTHS_PER_FIELD,
                    "raw_found": sum(row["raw_found"] for row in block),
                    "enhanced_found": sum(row["enhanced_found"] for row in block),
                })
    truths = len(per_field) * TRUTHS_PER_FIELD
    raw_found = sum(row["raw_found"] for row in per_field)
    enhanced_found = sum(row["enhanced_found"] for row in per_field)
    result = {
        "seed": SEED, "scans": len(per_field), "truths": truths, "scan_grid": [GRID, GRID],
        "step_um": STEP_UM, "candidates_per_scan": TOP, "match_radius_steps": MATCH_STEPS,
        "raw_found": raw_found, "enhanced_found": enhanced_found,
        "raw_recall_percent": 100 * raw_found / truths,
        "enhanced_recall_percent": 100 * enhanced_found / truths,
        "difference_percentage_points": 100 * (enhanced_found - raw_found) / truths,
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "groups": groups,
        "scope": "Synthetic positions and photon counts, with uncalibrated background and nuisance assumptions.",
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    with (output / "per_field.csv").open("w", newline="", encoding="ascii") as file:
        writer = csv.DictWriter(file, fieldnames=tuple(per_field[0]))
        writer.writeheader()
        writer.writerows(per_field)
    print(output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
