import csv
from io import StringIO
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


EXE = Path(__file__).resolve().with_name("nv_candidates.exe")


class CandidateDetectionTest(unittest.TestCase):
    def run_detector(self, counts):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            with (folder / "scan.csv").open("w", newline="", encoding="ascii") as file:
                writer = csv.writer(file)
                writer.writerow(("x_um", "y_um", "z_um", "count_kcps"))
                writer.writerows((x, y, 0, value) for (x, y), value in reversed(list(counts.items())))
            result = subprocess.run(
                [str(EXE), "scan.csv", "enhanced.csv"], cwd=folder, capture_output=True, text=True
            )
            enhanced = folder / "enhanced.csv"
            pixels = enhanced.read_text(encoding="ascii") if enhanced.exists() else ""
            return result, list(csv.DictReader(StringIO(pixels)))

    def test_top_candidate_matches_input_peak(self):
        counts = {}
        for y in range(15):
            for x in range(15):
                dx, dy = x - 9, y - 6
                counts[x, y] = 12 + 0.2 * x + 24 * max(0, 1 - (dx * dx + dy * dy) / 9)
        result, pixels = self.run_detector(counts)
        self.assertEqual(result.returncode, 0, result.stderr)
        top = next(csv.DictReader(StringIO(result.stdout)))
        self.assertEqual((float(top["x_um"]), float(top["y_um"])), (9, 6))
        self.assertGreater(float(top["contrast_kcps"]), 0)
        self.assertEqual(len(pixels), len(counts))

    def test_uniform_scan_has_no_peaks(self):
        counts = {(x, y): 12 for y in range(10) for x in range(10)}
        result, pixels = self.run_detector(counts)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(list(csv.DictReader(StringIO(result.stdout))))
        self.assertTrue(all(float(pixel["contrast_kcps"]) == 0 for pixel in pixels))

    def test_incomplete_grid_is_rejected(self):
        counts = {(x, y): 12 for y in range(10) for x in range(10) if (x, y) != (3, 5)}
        result, pixels = self.run_detector(counts)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("complete XY grid", result.stderr)
        self.assertFalse(pixels)


if __name__ == "__main__":
    unittest.main()
