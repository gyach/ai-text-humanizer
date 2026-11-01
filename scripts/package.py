"""Сборка переносимого плагина и самостоятельного Agent Skill. Python 3.9+."""
import argparse
import json
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SKILL_FILES = (
    'skills/humanize-text/SKILL.md',
    'skills/humanize-text/references/profiles.md',
    'skills/humanize-text/references/patterns.md',
    'skills/humanize-text/agents/openai.yaml',
)
PLUGIN_FILES = (
    'plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json',
    'README.md', *SKILL_FILES, 'docs/sources.md', 'docs/verification.md',
)

# Known source-tree names are attribution context, not distributable resources.
PRIVATE_CONTEXT = (
    r'/Users/', r'/home/[^/\s]+/', r'[A-Za-z]:[\\/]+Users[\\/]+',
    r'<specsRoot>', r'sysanalysts/specs', r'clearcode/hr-link', r'ekd-dev-docs',
)


def markdown_targets(text):
    """Inline links/images and reference definitions; ignore fenced examples."""
    text = re.sub(r'(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1\s*$', '', text)
    for match in re.finditer(r'\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)', text):
        yield match.group(1).strip('<>')
    for match in re.finditer(r'(?m)^ {0,3}\[[^\]\n]+\]:\s*(<[^>]+>|\S+)', text):
        yield match.group(1).strip('<>')


def validate_distribution(entries):
    """Check the actual names in one archive, including its documentation."""
    names = {archive_name for _, archive_name in entries}
    for source, name in entries:
        path = ROOT / source
        if not path.is_file() or path.resolve() != path.absolute():
            raise ValueError('Missing file or symlink in package: ' + source)
        text = path.read_text(encoding='utf-8')
        if path.suffix == '.json':
            text = json.dumps(json.loads(text), ensure_ascii=False)
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in PRIVATE_CONTEXT):
            raise ValueError('Nonportable context in ' + name)
        if path.suffix != '.md':
            continue
        for target in markdown_targets(text):
            parts = urlsplit(target)
            if parts.scheme in ('https', 'http', 'mailto') or parts.netloc:
                continue
            if parts.scheme or parts.path.startswith('/'):
                raise ValueError('Nonportable reference in ' + name)
            if not parts.path:
                continue
            dest = posixpath.normpath(posixpath.join(posixpath.dirname(name), unquote(parts.path)))
            if dest not in names:
                raise ValueError('Unpackaged reference in ' + name + ': ' + target)


def validate():
    """Проверяет локальную структуру, а не установку в целевом приложении."""
    for name in PLUGIN_FILES:
        path = ROOT / name
        if not path.is_file() or path.resolve() != path.absolute():
            raise ValueError('Missing file or symlink in package: ' + name)
    manifests = [json.loads((ROOT / name).read_text(encoding='utf-8')) for name in PLUGIN_FILES[:3]]
    portable = manifests[0]
    if portable['name'] != 'ai-text-humanizer' or not re.fullmatch(r'\d+\.\d+\.\d+', portable['version']):
        raise ValueError('Invalid package identity')
    for manifest in manifests:
        if (manifest['name'], manifest['version']) != (portable['name'], portable['version']):
            raise ValueError('Inconsistent manifest identity')
        if not manifest.get('description'):
            raise ValueError('Missing description')
    codex = manifests[2]
    if codex['skills'] != './skills/' or not isinstance(codex['interface']['defaultPrompt'], list):
        raise ValueError('Invalid Codex skills path or prompt type')
    validate_distribution([(name, name) for name in PLUGIN_FILES])
    validate_distribution([(name, name.removeprefix('skills/')) for name in SKILL_FILES])
    return portable


def write_zip(path, entries):
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for source, name in sorted(entries):
            info = ZipInfo(name, date_time=(2026, 11, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (ROOT / source).read_bytes())


def build(out_dir: Path):
    manifest = validate()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = manifest['name'] + '-' + manifest['version']
    plugin = out_dir / (prefix + '.zip')
    skill = out_dir / (prefix + '-skill.zip')
    write_zip(plugin, [(name, name) for name in PLUGIN_FILES])
    write_zip(skill, [(name, name.removeprefix('skills/')) for name in SKILL_FILES])
    return [plugin, skill]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    for output in build(args.out):
        print(output)
