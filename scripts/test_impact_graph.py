"""Find literal, transitive consumers in the current checkout.

Dynamic application assembly is handled separately by the selector; this graph
is evidence for direct consumers, not a claim to resolve arbitrary code.
"""
from __future__ import annotations

import ast
import os
import posixpath
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path, PurePosixPath
import re

SOURCE_SUFFIXES = {'.py', '.js', '.mjs', '.ts', '.json', '.txt', '.html', '.css'}
QUOTED = re.compile(r'''["']([^"'\n]{1,240})["']''')


@lru_cache(maxsize=2048)
def python_imports(name: str, source: str) -> frozenset[str] | None:
    """Cache only by complete content, so edits never reuse a stale parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    package = name[:-3].replace('/', '.').rpartition('.')[0]
    imported = set()
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            imported.update(alias.name for alias in item.names)
        elif isinstance(item, ast.ImportFrom):
            prefix = package.split('.') if package else []
            if item.level:
                prefix = prefix[:max(0, len(prefix) - item.level + 1)]
                base = '.'.join(prefix + ([item.module] if item.module else []))
            else:
                base = item.module or ''
            imported.add(base)
            imported.update(f'{base}.{alias.name}' for alias in item.names)
    return frozenset(imported)


def consumers(root: Path, changed: list[str], *, direct_only: set[str] | None = None) -> tuple[set[str], set[str], set[str]]:
    files = {}
    for folder in ('maw', 'web', 'tests', 'scripts', 'server-editor', 'tools', 'website'):
        directory = root / folder
        if directory.is_dir():
            for parent, dirs, names in os.walk(directory):
                dirs[:] = [d for d in dirs if d not in {'node_modules', '__pycache__', '.git', 'dist', 'build', '.artifacts'}]
                for filename in names:
                    path = Path(parent) / filename
                    if path.suffix in SOURCE_SUFFIXES and not filename.endswith(('-bundle.js', '-bundle.meta.json')):
                        files[path.relative_to(root).as_posix()] = path
    for name in ("maw_gui.py", "edit.py"):
        path = root / name
        if path.is_file():
            files[name] = path
    # Include a removed path as a reference target so consumers can still be found.
    targets = set(files) | set(changed)
    modules = {path[:-3].replace('/', '.'): path for path in targets if path.endswith('.py')}
    modules.update({path[:-12].replace('/', '.'): path for path in targets if path.endswith('/__init__.py')})
    errors = set()
    by_suffix = defaultdict(set)
    for path in targets:
        parts = PurePosixPath(path).parts
        for count in range(1, min(4, len(parts)) + 1):
            by_suffix['/'.join(parts[-count:])].add(path)
    reverse = defaultdict(set)
    for name, path in files.items():
        try:
            source = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            errors.add(name)
            continue
        if name.endswith('.py'):
            imported = python_imports(name, source)
            if imported is None:
                errors.add(name)
            else:
                for module in imported:
                    if module in modules:
                        reverse[modules[module]].add(name)
        # Inline subprocess snippets can import Python modules inside a longer string.
        for module in re.findall(r'\b(?:from|import)\s+((?:maw|tests|scripts)(?:\.[A-Za-z_]\w*)+)', source):
            if module in modules:
                reverse[modules[module]].add(name)
        for match in QUOTED.finditer(source):
            value = match.group(1).split('?', 1)[0].replace('\\', '/')
            if '/' not in value and '.' not in value:
                continue
            # Literal paths are frequently relative either to the repository or to the caller.
            suffix_matches = by_suffix.get(value.lstrip('./'), ())
            candidates = set(suffix_matches) if '/' in value or len(suffix_matches) == 1 else set()
            relative = posixpath.normpath(posixpath.join(posixpath.dirname(name), value))
            if relative in targets:
                candidates.add(relative)
            if value in targets:
                candidates.add(value)
            # Python modules are also passed as strings to subprocess/importlib.
            if value in modules:
                candidates.add(modules[value])
            for candidate in candidates:
                if candidate != name:
                    reverse[candidate].add(name)
    def terminal(name: str) -> bool:
        # These aggregate many modules. Propagating through them selects every
        # consumer of the assembled app for a single input. The selector adds
        # domain-specific runtime checks for those dynamic boundaries instead.
        return (name.startswith("tests/test_") or name.endswith(".spec.mjs")
                or name in {"web/editor-scripts.txt", "web/launcher-scripts.txt",
                            "web/editor-modules.json", "server-editor/serve.py"}
                or name.startswith(("scripts/build-", "web/editor/boot/"))
                or "/editor-wiring-" in name)

    all_reached, unmatched = set(), set()
    for changed_path in changed:
        seen = {changed_path}
        queue = deque([changed_path])
        while queue:
            for consumer in reverse[queue.popleft()] - seen:
                seen.add(consumer)
                if changed_path not in (direct_only or set()) and not terminal(consumer):
                    queue.append(consumer)
        all_reached.update(seen)
        if not any((name.startswith("tests/test_") or name.endswith(".spec.mjs"))
                   and name in files for name in seen):
            unmatched.add(changed_path)
    return all_reached, unmatched, errors


def document_consumers(root: Path, paths: list[str]) -> set[str]:
    """Match test reads of repository documents, not fixture names or links."""
    found = set()
    for folder, pattern in ((root / 'tests', 'test_*.py'), (root / 'tests', 'test_*.mjs'),
                            (root / 'tests/e2e', '*.spec.mjs')):
        for path in folder.glob(pattern):
            try:
                source = path.read_text(encoding='utf-8')
                if path.suffix == '.py':
                    # A repository-rooted fixture can be assigned before its
                    # read; distinguish it from a same-named temporary file.
                    log_paths = {name for name in paths if name.startswith('docs/logs/')}
                    try:
                        tree = ast.parse(source) if any(name in source for name in log_paths) else None
                    except SyntaxError:
                        tree = None
                    if tree:
                        rooted = set()
                        for item in ast.walk(tree):
                            if not isinstance(item, (ast.Assign, ast.AnnAssign)):
                                continue
                            value = item.value
                            if not value:
                                continue
                            parts = list(ast.walk(value))
                            if not (any(isinstance(part, ast.Name) and part.id == 'ROOT' for part in parts)
                                    and any(isinstance(part, ast.Constant) and part.value in log_paths for part in parts)):
                                continue
                            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                            rooted.update(target.id for target in targets if isinstance(target, ast.Name))
                        if any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                               and item.func.attr in {'read_text', 'read_bytes'}
                               and isinstance(item.func.value, ast.Name) and item.func.value.id in rooted
                               for item in ast.walk(tree)):
                            found.add(path.relative_to(root).as_posix())
                for line in source.splitlines():
                    if any(name in line for name in paths) and re.search(r'(?:\b(?:readFileSync|readFile|read_text|read_bytes)|(?<![\w.])open)\s*\(', line):
                        if '.write_text(' not in line and '.write_bytes(' not in line:
                            found.add(path.relative_to(root).as_posix())
            except (OSError, UnicodeError):
                # The ordinary graph reports unreadable files and widens tests.
                pass
    return found
