"""Generate a Diamond-II style workbook with three synthetic fluorescence spots."""

import argparse
import math
from pathlib import Path

from openpyxl import Workbook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    spots = ((7, 8, 75), (21, 12, 45), (15, 23, 58))
    workbook = Workbook(write_only=True)
    scan = workbook.create_sheet("data")
    scan.append(("X (μm)", "Y (μm)", "Z (μm)", "Count(kcps)"))
    for y in range(31):
        for x in range(31):
            background = 22 + 0.15 * x + 0.22 * y + 0.8 * math.sin(1.3 * x + 2.1 * y)
            signal = sum(amplitude * math.exp(-((x - sx) ** 2 + (y - sy) ** 2) / 2.8)
                         for sx, sy, amplitude in spots)
            scan.append((round(x * 0.4, 4), round(y * 0.4, 4), 12.0, background + signal))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        workbook.save(stream)


if __name__ == "__main__":
    main()
