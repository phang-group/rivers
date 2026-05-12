"""
collector.py — File System Traversal
======================================
Technology: pathlib (file ops) + subprocess (git)

Why pathlib over os.path:
  pathlib uses an object-oriented API with method chaining. Path('/a') / 'b'
  is cleaner than os.path.join('/a', 'b'). It also makes file extension
  checks, parent traversal, and glob patterns more readable.

Why subprocess for git (not GitPython):
  GitPython is a large dependency that adds ~5MB and requires libgit2 on some
  platforms. Since we only need two git operations (list files in branch, read
  file from branch), subprocess + git CLI is lighter and more portable.

Key decisions:
  - Skip binary files: don't waste tokens on images/fonts/videos
  - Skip build artifacts: node_modules, __pycache__, dist, .git
  - Smart truncation: cap large files at MAX_FILE_LINES to avoid context overflow
  - Priority files: entry points and config files are always included in full
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Set

# Directories to skip entirely — they contain no meaningful source code
SKIP_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    "dist", "build", ".next", "out", "coverage", ".coverage",
    "venv", ".venv", "env", ".env", "virtualenv",
    ".tox", ".eggs", "*.egg-info",
    "vendor", "third_party", "external",
    ".idea", ".vscode", ".DS_Store",
    "target",  # Rust/Java build dir
    "bin", "obj",  # .NET build dirs
    ".gradle", ".mvn",
}

# File extensions to skip — binary, media, or auto-generated
SKIP_EXTENSIONS: Set[str] = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".tiff",
    # Fonts
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    # Video/Audio
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
    # Binaries/compiled
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe", ".dylib",
    # Lock files (parse separately for dependencies)
    ".lock",
    # Large data files
    ".db", ".sqlite", ".sqlite3",
    # Minified/bundled (useless to read)
    ".min.js", ".min.css", ".map",
    # Certificates
    ".pem", ".key", ".crt", ".cert",
}

# High-priority files — always included in full regardless of size
PRIORITY_FILES: Set[str] = {
    "main.py", "app.py", "server.py", "index.py", "manage.py", "wsgi.py", "asgi.py",
    "index.js", "index.ts", "server.js", "server.ts", "app.js", "app.ts",
    "main.go", "main.rs", "main.rb",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    ".env.example", ".env.sample",
    "README.md", "ARCHITECTURE.md", "CONTRIBUTING.md",
    "package.json", "requirements.txt", "pyproject.toml", "go.mod", "Gemfile",
    "Cargo.toml", "composer.json", "pom.xml", "build.gradle",
    "next.config.js", "next.config.ts", "vite.config.js", "vite.config.ts",
    "webpack.config.js", "tailwind.config.js",
    "settings.py", "config.py", "configuration.py",
    "schema.prisma", "schema.graphql",
}

# Lines to read for "regular" source files
MAX_FILE_LINES = 300

# Lines to read for large files (anything > MAX_FILE_LINES triggers truncation)
TRUNCATE_NOTE = "\n... [TRUNCATED — file continues beyond this point] ..."


def collect(project_path: Path, branch: Optional[str] = None) -> Dict[str, Any]:
    """
    Main collection function. Returns a structured dict with everything
    the analyzer and LLMs will need.

    Args:
        project_path: Absolute path to the project root
        branch:       Optional git branch name to analyze instead of working tree
    """
    project_path = project_path.resolve()

    if branch:
        return _collect_from_branch(project_path, branch)
    else:
        return _collect_from_filesystem(project_path)


def _collect_from_filesystem(root: Path) -> Dict[str, Any]:
    """
    Walk the local filesystem and collect all relevant files.
    """
    files: Dict[str, str] = {}       # filepath (relative) → content
    file_count = 0
    total_lines = 0
    skipped_count = 0

    for filepath in _walk(root):
        relative = str(filepath.relative_to(root))
        content, lines = _read_file(filepath, is_priority=filepath.name in PRIORITY_FILES)

        if content is not None:
            files[relative] = content
            file_count += 1
            total_lines += lines
        else:
            skipped_count += 1

    return {
        "root_path": str(root),
        "project_name": root.name,
        "files": files,
        "file_count": file_count,
        "total_lines": total_lines,
        "skipped_count": skipped_count,
        "branch": None,
        "file_tree": _build_tree(root, files),
    }


def _collect_from_branch(root: Path, branch: str) -> Dict[str, Any]:
    """
    Read files from a specific git branch using git CLI.
    Falls back to filesystem if git is unavailable.
    """
    # Verify git is available and this is a git repo
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", branch],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            raise ValueError(f"Branch '{branch}' not found in git repo at {root}")
    except FileNotFoundError:
        raise RuntimeError("git is not installed or not in PATH. Cannot use --branch.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("git command timed out.")

    # Get list of all files in the branch
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", branch, "--name-only"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to list files in branch '{branch}': {result.stderr}")

    all_files = result.stdout.strip().split("\n")
    files: Dict[str, str] = {}
    file_count = 0
    total_lines = 0

    for relative_path in all_files:
        if not relative_path:
            continue

        path_obj = Path(relative_path)

        # Apply same skip rules
        if _should_skip_path(path_obj):
            continue

        filename = path_obj.name
        is_priority = filename in PRIORITY_FILES

        # Read file content from git
        content = _git_read_file(root, branch, relative_path, is_priority)
        if content is not None:
            files[relative_path] = content
            file_count += 1
            total_lines += content.count("\n")

    return {
        "root_path": str(root),
        "project_name": root.name,
        "files": files,
        "file_count": file_count,
        "total_lines": total_lines,
        "skipped_count": len(all_files) - file_count,
        "branch": branch,
        "file_tree": _build_tree_from_paths(list(files.keys())),
    }


def _walk(root: Path):
    """
    Yield all file paths under root, skipping excluded directories.
    Uses os.walk for efficiency on large trees.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip directories in-place (modifying dirnames prevents os.walk
        # from descending into them — this is the documented correct way)
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]

        for filename in filenames:
            filepath = Path(dirpath) / filename
            if not _should_skip_path(filepath):
                yield filepath


def _should_skip_path(path: Path) -> bool:
    """
    Return True if this file should be excluded from analysis.
    """
    # Check extension
    suffix = path.suffix.lower()
    if suffix in SKIP_EXTENSIONS:
        return True

    # Check compound extensions like .min.js, .test.js
    name_lower = path.name.lower()
    if name_lower.endswith(".min.js") or name_lower.endswith(".min.css"):
        return True

    # Skip dot-files except important ones
    if path.name.startswith(".") and path.name not in {".env.example", ".env.sample", ".gitignore"}:
        return True

    return False


def _read_file(filepath: Path, is_priority: bool = False) -> tuple:
    """
    Read a file, applying smart truncation for non-priority large files.
    Returns (content, line_count) or (None, 0) if unreadable.
    """
    try:
        # Try UTF-8 first, fall back to latin-1 for files with encoding issues
        try:
            text = filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = filepath.read_text(encoding="latin-1")
            except Exception:
                return None, 0

        lines = text.split("\n")
        line_count = len(lines)

        if is_priority or line_count <= MAX_FILE_LINES:
            return text, line_count
        else:
            # Truncate large files but keep the most informative parts:
            # first 200 lines (imports, class definitions) +
            # last 50 lines (often summary or main block)
            head = "\n".join(lines[:200])
            tail = "\n".join(lines[-50:])
            truncated = f"{head}\n{TRUNCATE_NOTE}\n\n[Last 50 lines:]\n{tail}"
            return truncated, line_count

    except (PermissionError, OSError):
        return None, 0


def _git_read_file(root: Path, branch: str, relative_path: str, is_priority: bool) -> Optional[str]:
    """
    Read a single file from a git branch using git show.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{branch}:{relative_path}"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            return None

        text = result.stdout
        lines = text.split("\n")
        line_count = len(lines)

        if is_priority or line_count <= MAX_FILE_LINES:
            return text
        else:
            head = "\n".join(lines[:200])
            tail = "\n".join(lines[-50:])
            return f"{head}\n{TRUNCATE_NOTE}\n\n[Last 50 lines:]\n{tail}"

    except (subprocess.TimeoutExpired, UnicodeDecodeError):
        return None


def _build_tree(root: Path, files: Dict[str, str]) -> str:
    """
    Build a visual file tree string from collected files.
    """
    return _build_tree_from_paths(list(files.keys()))


def _build_tree_from_paths(paths: List[str]) -> str:
    """
    Build a visual ASCII file tree from a list of relative path strings.
    Groups files by directory and renders with tree symbols.
    """
    if not paths:
        return "(empty)"

    # Sort paths for consistent display
    sorted_paths = sorted(paths)

    # Build nested dict structure
    tree: Dict = {}
    for path in sorted_paths:
        parts = Path(path).parts
        node = tree
        for part in parts:
            if part not in node:
                node[part] = {}
            node = node[part]

    lines = []
    _render_tree(tree, lines, prefix="")
    return "\n".join(lines)


def _render_tree(node: Dict, lines: List[str], prefix: str, name: str = "") -> None:
    """
    Recursively render the tree dict as ASCII art.
    """
    items = sorted(node.items(), key=lambda x: (len(x[1]) == 0, x[0]))

    for i, (key, children) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{key}")

        if children:
            extension = "    " if is_last else "│   "
            _render_tree(children, lines, prefix + extension, key)


def get_key_files(collected: Dict[str, Any], max_files: int = 20) -> Dict[str, str]:
    """
    Extract the most important files for LLM context.
    Priority order:
      1. Files matching PRIORITY_FILES names
      2. Config files (*.json, *.toml, *.yaml)
      3. Entry-point-looking files (main*, app*, server*, index*)
      4. Files in root or src/ directory
    """
    files = collected["files"]
    selected: Dict[str, str] = {}

    # Pass 1: exact priority name matches
    for path, content in files.items():
        if Path(path).name in PRIORITY_FILES:
            selected[path] = content
            if len(selected) >= max_files:
                return selected

    # Pass 2: config files
    config_exts = {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf"}
    for path, content in files.items():
        if path not in selected and Path(path).suffix.lower() in config_exts:
            selected[path] = content
            if len(selected) >= max_files:
                return selected

    # Pass 3: entry-point-looking names
    entry_patterns = ("main", "app", "server", "index", "manage", "wsgi", "asgi")
    for path, content in files.items():
        stem = Path(path).stem.lower()
        if path not in selected and any(stem.startswith(p) for p in entry_patterns):
            selected[path] = content
            if len(selected) >= max_files:
                return selected

    # Pass 4: root-level source files
    for path, content in files.items():
        parts = Path(path).parts
        if path not in selected and len(parts) <= 2:
            selected[path] = content
            if len(selected) >= max_files:
                return selected

    return selected
