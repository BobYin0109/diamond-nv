"""Run the C++ detector on Diamond-II XY scan workbooks and export results."""

import argparse
import csv
import json
from pathlib import Path
import re
import statistics
import subprocess

import matplotlib
import numpy as np
from openpyxl import load_workbook

matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCAN_HEADER = ("X (μm)", "Y (μm)", "Z (μm)", "Count(kcps)")
POSITION = re.compile(r"(-?\d+(?:\.\d+)?);(-?\d+(?:\.\d+)?)(?:;-?\d+(?:\.\d+)?)?")


def convert_workbook(workbook, destination):
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        rows = iter(book["data"].values)
        if next(rows, ())[:4] != SCAN_HEADER:
            raise ValueError(f"Expected a Diamond XY scan workbook: {workbook}")
        with destination.open("x", encoding="ascii", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(("x_um", "y_um", "z_um", "count_kcps"))
            for row in rows:
                writer.writerow(tuple(float(value) for value in row[:4]))
    finally:
        book.close()


def read_csv(path):
    with path.open(encoding="ascii", newline="") as file:
        return list(csv.DictReader(file))


def save_preview(pixels, candidates, path):
    x = sorted({float(row["x_um"]) for row in pixels})
    y = sorted({float(row["y_um"]) for row in pixels})
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.2), layout="constrained", sharex=True, sharey=True)
    for ax, column, title in zip(
        axes, ("raw_kcps", "contrast_kcps"), ("Raw photon count rate", "Enhanced image")
    ):
        matrix = np.array([float(row[column]) for row in pixels]).reshape(len(y), len(x))
        low = float(np.percentile(matrix, 2)) if column == "raw_kcps" else 0.0
        high = max(low + 1e-6, float(np.percentile(matrix, 99)))
        plot = ax.pcolormesh(x, y, matrix, cmap="magma", vmin=low, vmax=high, shading="nearest")
        ax.set(title=title, xlabel="X (µm)", aspect="equal")
        fig.colorbar(plot, ax=ax, label="kcps")
    axes[0].set_ylabel("Y (µm)")
    axes[1].scatter(
        [float(row["x_um"]) for row in candidates],
        [float(row["y_um"]) for row in candidates],
        facecolors="none", edgecolors="#69e0ff", s=27, linewidths=0.9,
    )
    fig.savefig(path, dpi=145)
    plt.close(fig)


def evaluate_positions(pixels, candidates, references):
    x = sorted({float(row["x_um"]) for row in pixels})
    y = sorted({float(row["y_um"]) for row in pixels})
    dx = statistics.median(b - a for a, b in zip(x, x[1:]))
    dy = statistics.median(b - a for a, b in zip(y, y[1:]))
    evaluations = []
    for rx, ry in sorted(references):
        if not ((x[0] - dx / 2 <= rx <= x[-1] + dx / 2) and
                (y[0] - dy / 2 <= ry <= y[-1] + dy / 2)):
            continue
        matches = [
            int(candidate["rank"])
            for candidate in candidates
            if ((float(candidate["x_um"]) - rx) / dx) ** 2
            + ((float(candidate["y_um"]) - ry) / dy) ** 2 <= 4
        ]
        evaluations.append({"x_um": rx, "y_um": ry, "best_matching_rank": min(matches, default=None)})
    return evaluations


def process(workbook, directory, exe, preview_candidates, reference_directory):
    directory.mkdir(parents=True)
    convert_workbook(workbook, directory / "scan.csv")
    with (directory / "candidates.csv").open("xb") as output:
        subprocess.run(
            [str(exe), "scan.csv", "enhanced.csv"], cwd=directory, stdout=output, check=True
        )
    pixels = read_csv(directory / "enhanced.csv")
    candidates = read_csv(directory / "candidates.csv")
    save_preview(pixels, candidates[:preview_candidates], directory / "preview.png")
    positions = set()
    if reference_directory is not None:
        for reference in reference_directory.glob("*.xlsx"):
            match = POSITION.fullmatch(reference.stem)
            if match:
                positions.add(tuple(map(float, match.groups())))
    return {
        "scan": str(workbook),
        "output": str(directory),
        "grid_points": len(pixels),
        "ranked_candidates": len(candidates),
        "recorded_recheck_positions": len(positions),
        "in_field_rechecks": evaluate_positions(pixels, candidates, positions),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="XY scan workbook or directory of XY scan workbooks")
    parser.add_argument("--exe", type=Path, default=Path(__file__).with_name("nv_candidates.exe"))
    parser.add_argument("--out", type=Path, required=True, help="new directory for the outputs")
    parser.add_argument("--top", type=int, default=25, help="number of ranked candidates to mark in the preview")
    parser.add_argument("--cw", type=Path, help="optional CW directory containing date and scan folders")
    args = parser.parse_args()
    source, exe, output = args.source.resolve(), args.exe.resolve(), args.out.resolve()
    if not exe.is_file():
        parser.error(f"C++ executable not found: {exe}")
    if args.top < 1:
        parser.error("--top must be positive")
    workbooks = [source] if source.is_file() else sorted(source.rglob("*.xlsx"))
    workbooks = [book for book in workbooks if not book.name.startswith("~$")]
    if not workbooks:
        parser.error(f"No scan workbooks found: {source}")
    if args.cw is not None and not args.cw.is_dir():
        parser.error(f"CW directory not found: {args.cw}")
    results = []
    output.mkdir(parents=True, exist_ok=False)
    for index, workbook in enumerate(workbooks, 1):
        reference_directory = None if args.cw is None else args.cw / workbook.parent.name / workbook.stem
        result = process(workbook, output / f"scan_{index:02d}", exe, args.top, reference_directory)
        results.append(result)
        print(f"{index}/{len(workbooks)}: {result['grid_points']} points, {result['ranked_candidates']} candidates",
              flush=True)
    rechecks = [item for result in results for item in result["in_field_rechecks"]]
    summary = {
        "scans": results,
        "in_field_rechecks": len(rechecks),
        "matching_tolerance": "within 2 scan steps after normalization by the X and Y spacings",
        "covered_rechecks_by_rank": {
            str(limit): sum(item["best_matching_rank"] is not None and item["best_matching_rank"] <= limit
                            for item in rechecks)
            for limit in sorted({10, 25, 50, args.top})
        },
        "note": "Recorded CW positions are selected rechecks, with no independent NV / non-NV labels.",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
