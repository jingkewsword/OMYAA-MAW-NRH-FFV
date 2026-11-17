"""Infer preparation required by one concrete test command.

Only literal imports and known runtime consumers are considered. A command that
cannot be parsed still runs, so its real failure remains visible.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

try:
    from .local_test_impact import NODE_BROWSER
    from .test_impact_graph import python_imports
    from .test_policy import MEDIA_CLASSES, MEDIA_METHODS, MEDIA_MODULES
except ImportError:
    from local_test_impact import NODE_BROWSER
    from test_impact_graph import python_imports
    from test_policy import MEDIA_CLASSES, MEDIA_METHODS, MEDIA_MODULES

JS_IMPORT = re.compile(
    r'''\b(?:import|export)\s+(?:[^;\n]*?\s+from\s*)?["']([^"']+)["']'''
    r'''|\b(?:import|require)\s*\(\s*["']([^"']+)["']''')
NODE_BUILTINS = {
    'assert', 'async_hooks', 'buffer', 'child_process', 'cluster', 'console', 'constants',
    'crypto', 'dgram', 'diagnostics_channel', 'dns', 'domain', 'events', 'fs', 'http',
    'http2', 'https', 'module', 'net', 'os', 'path', 'perf_hooks', 'process', 'punycode',
    'querystring', 'readline', 'repl', 'stream', 'string_decoder', 'sys', 'timers', 'tls',
    'trace_events', 'tty', 'url', 'util', 'v8', 'vm', 'wasi', 'worker_threads', 'zlib',
}
APP_BROWSER = re.compile(r'\b(?:startServer|startBlankServer|startLauncher|spawnServerProcess)\s*\(|(?:server-editor[/\\]serve\.py|maw_gui\.py)')
REAL_MEDIA = re.compile(r'''(?:execFile(?:Sync)?|spawn(?:Sync)?|subprocess\.(?:run|Popen|check_call|check_output))\s*\(\s*[\[\(]?\s*["'](?:ffmpeg|ffprobe)(?:\.exe)?["']''')


def _module_path(root: Path, module: str) -> Path | None:
    """Resolve a module or the longest local module prefix."""
    parts = module.split('.')
    while parts:
        rel = Path(*parts)
        for base in (root, root / 'tests'):
            for candidate in (base / rel.with_suffix('.py'), base / rel / '__init__.py'):
                if candidate.is_file():
                    return candidate
        parts.pop()
    return None


def _python_sources(root: Path, paths: list[Path]) -> tuple[list[tuple[Path, str]], bool]:
    pending = list(paths)
    seen = set()
    sources = []
    third_party = False
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            source = path.read_text(encoding='utf-8')
            name = path.relative_to(root).as_posix()
        except (OSError, UnicodeError, ValueError):
            continue
        sources.append((path, source))
        imported = python_imports(name, source)
        if imported is None:
            continue
        for module in imported:
            top = module.split('.', 1)[0]
            local = _module_path(root, module)
            if local is None:
                parts = module.split('.')
                while parts and local is None:
                    sibling = path.parent.joinpath(*parts).with_suffix('.py')
                    if sibling.is_file():
                        local = sibling
                    parts.pop()
            if local:
                pending.append(local)
            elif top and top not in sys.stdlib_module_names and not (root / top).is_dir() and not (root / 'tests' / top).is_dir():
                third_party = True
    return sources, third_party


def _js_sources(root: Path, paths: list[Path]) -> tuple[list[tuple[Path, str]], bool]:
    pending = list(paths)
    seen = set()
    sources = []
    third_party = False
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        try:
            source = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        sources.append((path, source))
        # Some tests store a literal module URL in a variable before import().
        # Resolve that direct pattern without treating arbitrary strings as imports.
        urls = re.findall(r"(?:const|let)\s+(\w+)\s*=\s*new\s+URL\(\s*[\"']([^\"']+)[\"']\s*,\s*import\.meta\.url\s*\)", source)
        for variable, relative in urls:
            if re.search(r"\bimport\s*\(\s*" + re.escape(variable) + r"\s*\)", source):
                candidate = (path.parent / relative).resolve()
                if candidate.is_file():
                    pending.append(candidate)
        for match in JS_IMPORT.finditer(source):
            name = match.group(1) or match.group(2)
            if name.startswith('node:') or name.split('/', 1)[0] in NODE_BUILTINS:
                continue
            if name.startswith(('.', '/')):
                candidate = (path.parent / name).resolve() if name.startswith('.') else root / name.lstrip('/')
                if candidate.is_file():
                    pending.append(candidate)
            elif not name.startswith(('data:', 'file:', 'http:', 'https:')):
                third_party = True
    return sources, third_party


def _python_real_media(source: str) -> bool:
    """Ignore sample programs embedded in strings; inspect executable AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in MEDIA_METHODS:
            return True
        if not isinstance(item, ast.Call) or not item.args:
            continue
        name = item.func.attr if isinstance(item.func, ast.Attribute) else item.func.id if isinstance(item.func, ast.Name) else ''
        if name not in {'run', 'Popen', 'check_call', 'check_output', 'which'}:
            continue
        first = item.args[0]
        if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
            first = first.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.lower() in {'ffmpeg', 'ffprobe', 'ffmpeg.exe', 'ffprobe.exe'}:
            return True
    return False


def _python_repo_build(source: str) -> bool:
    """Recognize real application rendering and ROOT-based artifact reads."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    root_names = set()
    for item in ast.walk(tree):
        if isinstance(item, (ast.Assign, ast.AnnAssign)) and item.value is not None:
            if any(isinstance(part, ast.Name) and part.id == '__file__' for part in ast.walk(item.value)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                root_names.update(target.id for target in targets if isinstance(target, ast.Name))
    for item in ast.walk(tree):
        if isinstance(item, ast.Call):
            name = item.func.attr if isinstance(item.func, ast.Attribute) else item.func.id if isinstance(item.func, ast.Name) else ''
            if name in {'render_empty_editor_page', 'ensure_editor_bundle'}:
                return True
        if isinstance(item, ast.BinOp):
            parts = list(ast.walk(item))
            if (any(isinstance(part, ast.Name) and part.id in root_names for part in parts)
                    and any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                            and ('editor-bundle.js' in part.value or 'launcher-bundle.js' in part.value) for part in parts)):
                return True
    return False


def _js_repo_build(source: str) -> bool:
    """Recognize root-derived bundle paths, not temp files with the same name."""
    bundle = r'(?:editor|launcher)-bundle\.js'
    if re.search(r'''(?:readFileSync|readFile)\s*\(\s*["']web/[^"']*''' + bundle, source):
        return True
    roots = re.findall(r'''(?:const|let)\s+(\w+)\s*=\s*fileURLToPath\s*\(\s*new\s+URL\([^;]*import\.meta\.url''', source)
    return any(re.search(r'''(?:join|resolve)\s*\(\s*''' + re.escape(name)
                         + r'''\s*,\s*["']web/[^"']*''' + bundle, source) for name in roots)


def _targets(command: list[str], root: Path, extension: str) -> list[Path]:
    targets = []
    # Options are not tests; the required root-relative paths and dotted unittest
    # names both contain a test_ component. Values such as report.json are ignored.
    for arg in command:
        value = str(arg).replace('\\', '/')
        if value.startswith('-') or 'test_' not in value and not value.endswith('.spec.mjs'):
            continue
        if extension == '.py':
            if value.endswith('.py') and (root / value).is_file():
                targets.append(root / value)
            else:
                path = _module_path(root, value.removesuffix('.py'))
                if path:
                    targets.append(path)
        elif value.endswith('.mjs') and (root / value).is_file():
            targets.append(root / value)
    return list(dict.fromkeys(targets))


def prerequisites(command: list[str], root: Path) -> set[str]:
    """Return the known preparation names needed by this command's files."""
    args = [str(item).replace('\\', '/') for item in command]
    root = Path(root).resolve()
    needed: set[str] = set()
    python_test = any(arg.endswith('scripts/run_tests.py') for arg in args)
    browser_test = any('@playwright/test/cli.js' in arg for arg in args)
    node_test = '--test' in args
    if python_test:
        targets = _targets(args, root, '.py')
        if not targets:
            return {'python-dependencies', 'ffmpeg', 'build'}
        sources, third_party = _python_sources(root, targets)
        if third_party:
            needed.add('python-dependencies')
        for path in targets:
            source = next((text for name, text in sources if name == path), '')
            module = path.stem
            if module in MEDIA_MODULES or module in {name for name, _ in MEDIA_CLASSES} or _python_real_media(source):
                needed.add('ffmpeg')
            if _python_repo_build(source):
                needed.add('build')
        return needed
    if browser_test or node_test:
        targets = _targets(args, root, '.mjs')
        if browser_test:
            needed.update({'node-dependencies', 'chromium'})
        if not targets:
            targets = list((root / ('tests/e2e' if browser_test else 'tests')).glob('*.spec.mjs' if browser_test else 'test_*.mjs'))
        sources, third_party = _js_sources(root, targets)
        if third_party:
            needed.add('node-dependencies')
        if any(path.name in NODE_BROWSER for path in targets) or any(re.search(r'\bchromium\.launch\s*\(', source) for _, source in sources):
            needed.update({'chromium', 'node-dependencies'})
        app_browser = False
        for path in targets:
            source = next((text for name, text in sources if name == path), '')
            if REAL_MEDIA.search(source):
                needed.add('ffmpeg')
            if browser_test and APP_BROWSER.search(source):
                needed.add('build')
                app_browser = True
            elif _js_repo_build(source):
                needed.add('build')
        server = root / 'server-editor/serve.py'
        if app_browser and server.is_file() and _python_sources(root, [server])[1]:
            needed.add('python-dependencies')
        return needed
    # Non-test maintenance commands have their own direct imports, not a
    # blanket dependency on the entire application environment.
    if any(arg.endswith('/ruff') or arg == 'ruff' or arg == 'ruff.exe' for arg in args) or '-m' in args and 'ruff' in args:
        needed.add('python-dependencies')
    js_paths = [root / arg for arg in args if arg.endswith(('.js', '.mjs')) and (root / arg).is_file()]
    if js_paths and _js_sources(root, js_paths)[1] or args and Path(args[0]).name in {'pnpm', 'pnpm.cmd', 'npm', 'npm.cmd'}:
        needed.add('node-dependencies')
    return needed
