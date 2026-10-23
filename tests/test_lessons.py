"""The catalog teaches sequential lessons without claiming live evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from inference_lab.lessons import CATALOG


class LessonCatalogTests(unittest.TestCase):
    def test_four_ordered_lessons_have_teaching_material_and_repository_folders(self):
        self.assertEqual([item["id"][:2] for item in CATALOG], ["01", "02", "03", "04"])
        root = Path(__file__).resolve().parents[1]
        for item in CATALOG:
            with self.subTest(lesson=item["id"]):
                for field in ("title", "objective", "prediction", "reflection", "steps"):
                    self.assertTrue(item[field])
                self.assertTrue((root / "lessons" / item["id"] / "README.md").is_file())
                self.assertNotIn("state", item)  # Preparation is not live observation.

    def test_unresolved_stacks_have_explicit_gates(self):
        self.assertIsNone(CATALOG[0]["gate"])
        self.assertIsNone(CATALOG[1]["gate"])
        self.assertIn("privilege", CATALOG[2]["gate"])
        self.assertIn("disk", CATALOG[3]["gate"])


if __name__ == "__main__":
    unittest.main()
