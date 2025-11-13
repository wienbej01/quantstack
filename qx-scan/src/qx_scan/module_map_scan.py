#!/usr/bin/env python3
"""Module topology scanner: Map upstream/downstream modules, mechanisms, and params."""

import ast
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

# Legacy repos to scan
LEGACY_REPOS = [
    "/home/jacobw/trade_system_modules",
    "/home/jacobw/timegpt_v2",
    "/home/jacobw/project-chimera",
    "/home/jacobw/transalpha/transalpha",
    "/home/jacobw/transalpha",
    "/home/jacobw/volume_price_trade",
    "/home/jacobw/llm_rebuilt",
    "/home/jacobw/HMM_SIP",
    "/home/jacobw/intraday_stack",
    "/home/jacobw/Cor_trading",
    "/home/jacobw/hybrid_fourier",
    "/home/jacobw/options",
    "/home/jacobw/LLM_Trading",
    "/home/jacobw/hybrid-local",
    "/home/jacobw/order_book",
    "/home/jacobw/RL_trading",
]


def parse_python_file(file_path: Path) -> dict[str, Any]:
    """Parse a Python file for imports, functions, classes."""
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return {}

    imports = []
    functions = []
    classes = []
    io_paths = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")
        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Str):
            # Heuristic for file paths
            if "/" in node.s and (
                ".csv" in node.s or ".parquet" in node.s or "gcs" in node.s.lower()
            ):
                io_paths.append(node.s)

    return {
        "imports": imports,
        "functions": functions,
        "classes": classes,
        "io_paths": io_paths,
    }


def scan_repos() -> dict[str, Any]:
    """Scan legacy repos for module topology."""
    topology = defaultdict(
        lambda: {
            "files": [],
            "imports": set(),
            "functions": set(),
            "classes": set(),
            "io_paths": set(),
        }
    )

    for repo_path in LEGACY_REPOS:
        repo = Path(repo_path)
        if not repo.exists():
            continue
        for py_file in repo.rglob("*.py"):
            rel_path = py_file.relative_to(repo)
            module_name = str(rel_path).replace("/", ".").replace("\\", ".").rstrip(".py")
            parsed = parse_python_file(py_file)
            topology[module_name]["files"].append(str(py_file))
            topology[module_name]["imports"].update(parsed.get("imports", []))
            topology[module_name]["functions"].update(parsed.get("functions", []))
            topology[module_name]["classes"].update(parsed.get("classes", []))
            topology[module_name]["io_paths"].update(parsed.get("io_paths", []))

    # Convert sets to lists for JSON
    for mod in topology:
        topology[mod]["imports"] = list(topology[mod]["imports"])
        topology[mod]["functions"] = list(topology[mod]["functions"])
        topology[mod]["classes"] = list(topology[mod]["classes"])
        topology[mod]["io_paths"] = list(topology[mod]["io_paths"])

    return dict(topology)


def generate_mermaid(topology: dict[str, Any]) -> str:
    """Generate Mermaid diagram."""
    lines = ["graph TD"]
    for mod, data in topology.items():
        lines.append(f"    {mod.replace('.', '_')}({mod})")
        for imp in data["imports"][:5]:  # Limit for readability
            clean_imp = imp.replace(".", "_")
            lines.append(f"    {mod.replace('.', '_')} --> {clean_imp}")
    return "\n".join(lines)


def main():
    """Main entry point."""
    topology = scan_repos()

    out_dir = Path("~/quantstack/qx-scan/out").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    with open(out_dir / "module_map.json", "w") as f:
        json.dump(topology, f, indent=2)

    # MD
    md_content = "# Module Topology Map\n\n"
    for mod, data in topology.items():
        md_content += f"## {mod}\n"
        md_content += f"- Files: {len(data['files'])}\n"
        md_content += f"- Imports: {', '.join(data['imports'][:10])}\n"
        md_content += f"- Functions: {', '.join(data['functions'][:10])}\n"
        md_content += f"- Classes: {', '.join(data['classes'][:10])}\n"
        md_content += f"- IO Paths: {', '.join(data['io_paths'][:5])}\n\n"

    with open(out_dir / "module_map.md", "w") as f:
        f.write(md_content)

    # Mermaid
    mermaid = generate_mermaid(topology)
    with open(out_dir / "module_map.mmd", "w") as f:
        f.write(mermaid)


if __name__ == "__main__":
    main()
