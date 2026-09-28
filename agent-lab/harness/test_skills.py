import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


HARNESS_DIR = Path(__file__).resolve().parent
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

from skills import (  # noqa: E402
    DEFAULT_SKILL_NAMES,
    SkillError,
    find_skills,
    list_skills,
    resolve_skill_selection,
)


class SkillRegistryTests(unittest.TestCase):
    def write_project_skill(self, root: Path, name: str = "field-notes") -> Path:
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Capture concise project notes before editing.\n---\n\nUse the project files as evidence.\n",
            encoding="utf-8",
        )
        return skill_dir

    def test_defaults_are_deterministic_and_include_only_bundled_core(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selection = resolve_skill_selection(Path(temporary))

        self.assertEqual(selection["defaults"], list(DEFAULT_SKILL_NAMES))
        self.assertEqual([item["name"] for item in selection["resolved"]], list(DEFAULT_SKILL_NAMES))
        self.assertTrue(all(item["source"] == "builtin" for item in selection["resolved"]))
        self.assertTrue(all(item["content_hash"] for item in selection["resolved"]))

    def test_optional_operator_skills_are_available_without_becoming_defaults(self) -> None:
        names = {item["name"] for item in list_skills()}

        self.assertTrue({"test-driven-changes", "systematic-debugging", "review-before-finish"} <= names)
        self.assertEqual(list(DEFAULT_SKILL_NAMES), ["inspect-and-plan", "verify-before-finish"])

    def test_project_skill_is_discoverable_but_not_selected_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.write_project_skill(project)
            catalog = list_skills(project)
            selection = resolve_skill_selection(project)

        project_skill = next(item for item in catalog if item["name"] == "field-notes")
        self.assertEqual(project_skill["source"], "project")
        self.assertNotIn("field-notes", [item["name"] for item in selection["resolved"]])

    def test_overrides_enable_project_skill_and_disable_a_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.write_project_skill(project)
            selection = resolve_skill_selection(
                project,
                {"enabled": ["field-notes"], "disabled": ["verify-before-finish"]},
            )

        self.assertEqual(selection["enabled"], ["field-notes"])
        self.assertEqual(selection["disabled"], ["verify-before-finish"])
        self.assertEqual([item["name"] for item in selection["resolved"]], ["inspect-and-plan", "field-notes"])

    def test_skill_content_hash_is_sha256_of_loaded_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.write_project_skill(project)
            item = next(item for item in list_skills(project) if item["name"] == "field-notes")

        expected = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        self.assertEqual(item["content_hash"], expected)

    def test_find_skills_searches_local_catalog_and_returns_quality_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self.write_project_skill(project)
            results = find_skills("notes", project)

        self.assertEqual([item["name"] for item in results], ["field-notes"])
        self.assertEqual(results[0]["source"], "project")
        self.assertIn("quality", results[0])
        self.assertIn("activate", results[0]["quality"].lower())

    def test_remote_discovery_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SkillError):
                find_skills("browser testing", Path(temporary), source="remote")


if __name__ == "__main__":
    unittest.main()

