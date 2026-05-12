"""
analyzer.py — Dependency Parsing + Structure Detection
========================================================
Technology: ast (Python), re (regex), json, tomllib/tomli

Why ast for Python:
  Python's built-in ast module produces a full abstract syntax tree. We use it
  to extract top-level imports, class names, and function signatures — giving
  the Archaeologist real structure to reference, not just file names.

Why regex for other languages:
  Rather than adding tree-sitter (which requires compiled language parsers and
  a build step), we use targeted regex patterns to extract imports and class
  definitions from JS/TS/Go/Ruby. The LLM does the semantic analysis — we just
  need enough signal to identify patterns.

Why parse multiple dependency formats:
  A modern project might have Python deps in requirements.txt AND a JS frontend
  in package.json AND infrastructure defined in pyproject.toml. We parse all of
  them so the LLMs see the complete dependency picture.
"""

import ast
import re
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

# Language detection by file extension
LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".php": "PHP",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".clj": "Clojure",
    ".hs": "Haskell",
    ".r": "R",
    ".jl": "Julia",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Bash",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".tf": "Terraform",
    ".proto": "Protobuf",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
}

# Framework detection: file patterns that indicate specific frameworks
FRAMEWORK_SIGNALS = {
    "Django": ["manage.py", "settings.py", "urls.py", "wsgi.py", "asgi.py"],
    "Flask": ["app.py", "flask"],
    "FastAPI": ["fastapi", "uvicorn"],
    "React": ["package.json→react", "jsx", "tsx"],
    "Next.js": ["next.config.js", "next.config.ts", "pages/", "_app.tsx", "_app.js"],
    "Vue": ["vue.config.js", ".vue"],
    "Svelte": [".svelte", "svelte.config.js"],
    "Express": ["package.json→express"],
    "NestJS": ["package.json→@nestjs"],
    "Rails": ["Gemfile→rails", "config/routes.rb", "app/controllers"],
    "Laravel": ["artisan", "composer.json→laravel"],
    "Spring": ["pom.xml→spring", "build.gradle→spring"],
    "Go (Gin)": ["go.mod→gin-gonic"],
    "Go (Echo)": ["go.mod→labstack/echo"],
    "Rust (Axum)": ["Cargo.toml→axum"],
    "Rust (Actix)": ["Cargo.toml→actix"],
    "Prisma": ["schema.prisma"],
    "GraphQL": [".graphql", ".gql", "schema.graphql"],
    "Docker": ["Dockerfile", "docker-compose.yml"],
    "Kubernetes": ["k8s/", "kubernetes/", ".yaml→kind: Deployment"],
    "Terraform": [".tf"],
    "tRPC": ["package.json→@trpc"],
    "Celery": ["requirements.txt→celery", "tasks.py"],
    "Redis": ["requirements.txt→redis", "package.json→redis"],
    "Stripe": ["requirements.txt→stripe", "package.json→stripe"],
}


def analyze(collected: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main analysis function. Takes the raw collected file data and returns
    a structured analysis dict ready to be passed to the LLMs.
    """
    files = collected["files"]

    # Detect languages
    languages, primary_language = _detect_languages(files)

    # Parse all dependency manifests
    dependencies = _parse_all_dependencies(files)

    # Detect frameworks
    frameworks = _detect_frameworks(files, dependencies)

    # Detect entry points
    entry_points = _detect_entry_points(files)

    # Extract Python structure (AST)
    python_structure = _extract_python_structure(files)

    # Build config summary
    config_summary = _build_config_summary(files)

    # Format dependencies for LLM consumption
    deps_formatted = _format_dependencies(dependencies)

    # Select key files for LLM context
    from .collector import get_key_files
    key_files = get_key_files(collected, max_files=25)

    return {
        **collected,
        "languages": languages,
        "primary_language": primary_language,
        "frameworks": frameworks,
        "dependencies": dependencies,
        "dependencies_formatted": deps_formatted,
        "entry_points": entry_points,
        "python_structure": python_structure,
        "config_summary": config_summary,
        "key_files": key_files,
    }


def _detect_languages(files: Dict[str, str]) -> tuple:
    """
    Count files per language, return sorted list and primary language.
    """
    counts: Dict[str, int] = {}

    for path in files.keys():
        ext = Path(path).suffix.lower()
        lang = LANGUAGE_MAP.get(ext)
        if lang and lang not in ("JSON", "YAML", "TOML", "HTML", "CSS"):
            counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        # Fall back to including config languages
        for path in files.keys():
            ext = Path(path).suffix.lower()
            lang = LANGUAGE_MAP.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1

    sorted_langs = sorted(counts.keys(), key=lambda l: counts[l], reverse=True)
    primary = sorted_langs[0] if sorted_langs else "Unknown"
    return sorted_langs, primary


def _parse_all_dependencies(files: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    """
    Parse every dependency manifest format we know about.
    Returns a dict like: {"python": {"django": "4.2.0"}, "nodejs": {...}}
    """
    deps: Dict[str, Dict[str, str]] = {}

    for path, content in files.items():
        filename = Path(path).name.lower()

        if filename == "requirements.txt":
            deps["python"] = deps.get("python", {})
            deps["python"].update(_parse_requirements_txt(content))

        elif filename == "package.json" and '"dependencies"' in content:
            pkg = _safe_json(content)
            if pkg:
                deps["nodejs"] = deps.get("nodejs", {})
                deps["nodejs"].update(pkg.get("dependencies", {}))
                deps["nodejs"].update(pkg.get("devDependencies", {}))

        elif filename == "pyproject.toml":
            parsed = _parse_pyproject_toml(content)
            if parsed:
                deps["python"] = deps.get("python", {})
                deps["python"].update(parsed)

        elif filename == "go.mod":
            deps["go"] = deps.get("go", {})
            deps["go"].update(_parse_go_mod(content))

        elif filename == "gemfile":
            deps["ruby"] = deps.get("ruby", {})
            deps["ruby"].update(_parse_gemfile(content))

        elif filename == "cargo.toml":
            parsed = _parse_cargo_toml(content)
            if parsed:
                deps["rust"] = deps.get("rust", {})
                deps["rust"].update(parsed)

        elif filename == "composer.json":
            pkg = _safe_json(content)
            if pkg:
                deps["php"] = deps.get("php", {})
                deps["php"].update(pkg.get("require", {}))

        elif filename in ("pom.xml",):
            # Basic Maven dep extraction via regex
            deps["java"] = deps.get("java", {})
            deps["java"].update(_parse_pom_xml(content))

    return deps


def _parse_requirements_txt(content: str) -> Dict[str, str]:
    """Parse pip requirements.txt format."""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        # Handle: django==4.2.0, django>=4.2, django[rest]>=4.0, etc.
        match = re.match(r"^([a-zA-Z0-9_\-\[\]]+)\s*([>=<!~^]+\s*[\d\w\.\*]+)?", line)
        if match:
            name = match.group(1).split("[")[0].lower()
            version = match.group(2).strip() if match.group(2) else "*"
            result[name] = version
    return result


def _parse_pyproject_toml(content: str) -> Optional[Dict[str, str]]:
    """Parse pyproject.toml [project.dependencies] section."""
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            data = tomllib.loads(content)
        else:
            import tomli
            data = tomli.loads(content)

        result = {}
        deps = data.get("project", {}).get("dependencies", [])
        for dep in deps:
            match = re.match(r"^([a-zA-Z0-9_\-]+)\s*([>=<!~^]+.*)?", dep)
            if match:
                result[match.group(1).lower()] = match.group(2) or "*"
        return result
    except Exception:
        # Fall back to regex if TOML parsing fails
        result = {}
        in_deps = False
        for line in content.splitlines():
            if "dependencies" in line and "[" in line:
                in_deps = True
            elif in_deps and line.strip().startswith("["):
                in_deps = False
            elif in_deps:
                match = re.match(r'"([a-zA-Z0-9_\-]+)', line)
                if match:
                    result[match.group(1).lower()] = "*"
        return result


def _parse_go_mod(content: str) -> Dict[str, str]:
    """Parse go.mod require block."""
    result = {}
    in_require = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("require ("):
            in_require = True
        elif in_require and line == ")":
            in_require = False
        elif in_require or line.startswith("require "):
            match = re.match(r"(?:require\s+)?([a-zA-Z0-9\-_./]+)\s+(v[\d\w\.\-]+)", line)
            if match:
                result[match.group(1)] = match.group(2)
    return result


def _parse_gemfile(content: str) -> Dict[str, str]:
    """Parse Ruby Gemfile gem declarations."""
    result = {}
    for line in content.splitlines():
        match = re.match(r'\s*gem\s+[\'"]([a-zA-Z0-9_\-]+)[\'"](?:,\s*[\'"]([^"\']+)[\'"])?', line)
        if match:
            result[match.group(1)] = match.group(2) or "*"
    return result


def _parse_cargo_toml(content: str) -> Optional[Dict[str, str]]:
    """Parse Rust Cargo.toml [dependencies]."""
    result = {}
    in_deps = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "[dependencies]":
            in_deps = True
        elif stripped.startswith("[") and in_deps:
            in_deps = False
        elif in_deps and "=" in stripped:
            name = stripped.split("=")[0].strip().strip('"')
            result[name] = "*"
    return result


def _parse_pom_xml(content: str) -> Dict[str, str]:
    """Basic Maven POM dependency extraction via regex."""
    result = {}
    artifact_ids = re.findall(r"<artifactId>([^<]+)</artifactId>", content)
    for aid in artifact_ids:
        result[aid] = "*"
    return result


def _safe_json(content: str) -> Optional[Dict]:
    """Parse JSON safely, returning None on failure."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _detect_frameworks(files: Dict[str, str], dependencies: Dict[str, Dict[str, str]]) -> List[str]:
    """
    Detect frameworks by looking for signal files and dependency names.
    """
    detected = []
    all_filenames = set(Path(p).name for p in files.keys())
    all_paths = set(files.keys())
    all_deps = set()
    for dep_group in dependencies.values():
        all_deps.update(dep_group.keys())

    for framework, signals in FRAMEWORK_SIGNALS.items():
        for signal in signals:
            if "→" in signal:
                # Dependency signal: "package.json→react"
                _, dep_name = signal.split("→", 1)
                if any(dep_name in dep for dep in all_deps):
                    detected.append(framework)
                    break
            elif "/" in signal:
                # Directory signal
                if any(signal in p for p in all_paths):
                    detected.append(framework)
                    break
            else:
                # File name signal
                if signal in all_filenames or signal in all_paths:
                    detected.append(framework)
                    break

    return list(dict.fromkeys(detected))  # deduplicate while preserving order


def _detect_entry_points(files: Dict[str, str]) -> List[str]:
    """
    Identify likely entry points: files that start the application.
    """
    entry_patterns = [
        r"^main\.(py|js|ts|go|rs|rb)$",
        r"^app\.(py|js|ts)$",
        r"^server\.(py|js|ts)$",
        r"^index\.(py|js|ts)$",
        r"^manage\.py$",
        r"^wsgi\.py$",
        r"^asgi\.py$",
        r"^Dockerfile$",
        r"^docker-compose\.ya?ml$",
    ]

    entry_points = []
    for path in sorted(files.keys()):
        filename = Path(path).name
        for pattern in entry_patterns:
            if re.match(pattern, filename, re.IGNORECASE):
                entry_points.append(path)
                break

    return entry_points


def _extract_python_structure(files: Dict[str, str]) -> Dict[str, Any]:
    """
    Use Python's built-in ast module to extract class and function
    definitions from Python files. This gives the Archaeologist real
    structure to reference.
    """
    structure = {}

    for path, content in files.items():
        if not path.endswith(".py"):
            continue

        try:
            tree = ast.parse(content)
            imports = []
            classes = []
            functions = []

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        imports.append(f"{module}.{alias.name}")
                elif isinstance(node, ast.ClassDef):
                    bases = [
                        ast.unparse(b) if hasattr(ast, "unparse") else b.id
                        for b in node.bases
                        if hasattr(b, "id") or hasattr(ast, "unparse")
                    ]
                    classes.append({
                        "name": node.name,
                        "bases": bases,
                        "line": node.lineno,
                    })
                elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    # Only top-level functions (not methods)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions.append({
                            "name": node.name,
                            "line": node.lineno,
                            "is_async": isinstance(node, ast.AsyncFunctionDef),
                        })

            if imports or classes or functions:
                structure[path] = {
                    "imports": imports[:30],  # cap at 30 to save context
                    "classes": classes,
                    "functions": [f for f in functions if not f["name"].startswith("_")][:20],
                }
        except SyntaxError:
            pass  # Skip files with syntax errors

    return structure


def _build_config_summary(files: Dict[str, str]) -> str:
    """
    Extract a readable summary of configuration files.
    """
    summary_parts = []
    config_names = {
        ".env.example", ".env.sample", "next.config.js", "next.config.ts",
        "vite.config.js", "vite.config.ts", "webpack.config.js",
        "tailwind.config.js", "jest.config.js", "tsconfig.json",
        ".eslintrc.js", ".prettierrc", "Dockerfile", "docker-compose.yml",
    }

    for path, content in files.items():
        if Path(path).name in config_names:
            # Truncate to first 30 lines for config preview
            preview = "\n".join(content.splitlines()[:30])
            summary_parts.append(f"### `{path}`\n```\n{preview}\n```")

    return "\n\n".join(summary_parts) if summary_parts else "No configuration files detected."


def _format_dependencies(dependencies: Dict[str, Dict[str, str]]) -> str:
    """
    Format the dependency dict into a readable string for LLM consumption.
    """
    if not dependencies:
        return "No dependency manifests found."

    parts = []
    for ecosystem, deps in dependencies.items():
        if not deps:
            continue
        header = f"### {ecosystem.title()} Dependencies ({len(deps)} packages)"
        dep_lines = [f"  - {name}: {version}" for name, version in sorted(deps.items())]
        parts.append(header + "\n" + "\n".join(dep_lines))

    return "\n\n".join(parts) if parts else "No dependencies found in manifest files."
