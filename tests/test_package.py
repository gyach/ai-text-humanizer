"""Проверка реальных ZIP, включая запуск из другого рабочего каталога."""
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def copy_project(self, tmp):
        project = Path(tmp) / 'project'
        shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns('dist', '__pycache__', '.git'))
        return project

    def assert_build_rejected(self, project, tmp, expected):
        out = Path(tmp) / 'out'
        result = subprocess.run(
            [sys.executable, str(project / 'scripts/package.py'), '--out', str(out)],
            cwd=tmp, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0, 'Invalid package was accepted')
        self.assertIn(expected, result.stderr)
        self.assertEqual(list(out.glob('*.zip')), [], 'Validation must precede archive writing')

    def test_existing_but_unshipped_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.copy_project(tmp)
            (project / 'skills/humanize-text/references/unlisted.md').write_text('Extra reference')
            with (project / 'skills/humanize-text/SKILL.md').open('a') as f:
                f.write('\n[Extra](references/unlisted.md)\n')
            self.assert_build_rejected(project, tmp, 'Unpackaged reference')

    def test_private_context_in_each_shipped_document_is_rejected(self):
        for name in ('README.md', 'docs/sources.md', 'docs/verification.md',
                     'skills/humanize-text/agents/openai.yaml', '.codex-plugin/plugin.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                project = self.copy_project(tmp)
                path = project / name
                if path.suffix == '.json':
                    data = json.loads(path.read_text())
                    data['description'] = 'Local setup /Users/example/Projects/private-tool'
                    path.write_text(json.dumps(data))
                else:
                    with path.open('a') as f:
                        f.write('\n# Local setup /Users/example/Projects/private-tool\n')
                self.assert_build_rejected(project, tmp, 'Nonportable context')

    def test_reference_definition_cannot_point_to_unshipped_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.copy_project(tmp)
            (project / 'internal-note.md').write_text('Not for distribution')
            with (project / 'README.md').open('a') as f:
                f.write('\n[More][extra]\n\n[extra]: internal-note.md\n')
            self.assert_build_rejected(project, tmp, 'Unpackaged reference')

    def test_standalone_skill_cannot_depend_on_plugin_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.copy_project(tmp)
            with (project / 'skills/humanize-text/SKILL.md').open('a') as f:
                f.write('\n[Setup](../../README.md)\n')
            # README exists in plugin ZIP, but not in the standalone skill ZIP.
            self.assert_build_rejected(project, tmp, 'Unpackaged reference')

    def test_other_home_paths_and_known_private_tree_names_are_rejected(self):
        for text in ('/home/example/private', r'C:\Users\example\private',
                     'sysanalysts/specs', 'clearcode/hr-link', 'ekd-dev-docs'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                project = self.copy_project(tmp)
                with (project / 'docs/sources.md').open('a') as f:
                    f.write('\n' + text + '\n')
                self.assert_build_rejected(project, tmp, 'Nonportable context')

    def test_archives_contain_only_installable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/package.py'), '--out', tmp],
                cwd=tmp, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            paths = sorted(Path(tmp).glob('*.zip'))
            self.assertEqual(len(paths), 2)
            plugin = next(p for p in paths if not p.name.endswith('-skill.zip'))
            skill = next(p for p in paths if p.name.endswith('-skill.zip'))
            with ZipFile(plugin) as archive:
                self.assertIsNone(archive.testzip())
                names = set(archive.namelist())
                for manifest in ['plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json']:
                    data = json.loads(archive.read(manifest))
                    self.assertEqual(data['name'], 'ai-text-humanizer')
                    self.assertEqual(data['version'], '0.1.1')
                self.assertIn('skills/humanize-text/SKILL.md', names)
                self.assertEqual({n for n in names if n.startswith('docs/')}, {'docs/sources.md', 'docs/verification.md'})
                self.assertIn('skills/humanize-text/references/profiles.md', names)
                self.assertFalse(any(n.startswith(('evals/', 'tests/', 'scripts/', '.git/')) for n in names))
                self.assertFalse(any('..' in Path(n).parts or n.startswith('/') for n in names))
                with ZipFile(skill) as standalone:
                    self.assertIsNone(standalone.testzip())
                    for name in standalone.namelist():
                        self.assertTrue(name.startswith('humanize-text/'))
                        self.assertEqual(standalone.read(name), archive.read('skills/' + name))
                    self.assertIn('humanize-text/SKILL.md', standalone.namelist())


if __name__ == '__main__':
    unittest.main()
