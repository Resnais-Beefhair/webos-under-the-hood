"""Verify the allowlisted real screenshots without a TV or imaging packages."""
import hashlib
import importlib.util
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("screensaver_publication", ROOT / "tools/check_publication.py")
scanner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scanner)


class ScreensaverGalleryTests(unittest.TestCase):
    def test_native_pngs_match_provenance_and_dimensions(self):
        manifest = json.loads((ROOT / "assets/evidence/screensavers.json").read_text(encoding="utf-8"))
        expected = {
            "screensavers/original-fireworks.png": (1920, 1080),
            "screensavers/moving-rings.png": (1920, 1080),
            "screensavers/original-fireworks-detail.png": (512, 512),
        }
        self.assertEqual({item["file"] for item in manifest["images"]}, set(expected))
        self.assertEqual(len(manifest["images"]), len(expected))
        for item in manifest["images"]:
            with self.subTest(image=item["file"]):
                data = (ROOT / "assets" / item["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", data[16:24]), expected[item["file"]])
                self.assertEqual(scanner.scan_png(data, item["file"]), [])
        self.assertEqual(manifest["full_frames_processing"], "none; native PNG bytes preserved")
        detail = manifest["detail_processing"]
        self.assertEqual(detail["source"], "screensavers/original-fireworks.png")
        self.assertEqual(detail["crop_xyxy"], [78, 215, 590, 727])
        x0, y0, x1, y1 = detail["crop_xyxy"]
        self.assertEqual([x1 - x0, y1 - y0], detail["size"])

    def test_optional_feature_and_images_are_discoverable_without_ai(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        gallery = (ROOT / "docs/screensavers.md").read_text(encoding="utf-8")
        for text in (readme, gallery):
            self.assertIn("optional-screensaver/README.md", text)
            self.assertIn("screensavers/original-fireworks.png", text)
            self.assertIn("screensavers/moving-rings.png", text)
        self.assertIn("Off by default", readme)
        self.assertIn("not a live test of the public generated installer", gallery)
        self.assertIn("not an MIT relicensing", (ROOT / "NOTICE.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
