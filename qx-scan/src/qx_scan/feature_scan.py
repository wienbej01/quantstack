#!/usr/bin/env python3
"""Feature universe scanner v2: Catalog feature builders with allowlist/denylist and AST heuristics."""

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

# Allowlist roots: 16 strategy repos, include only src/**, lib/**, features/**
ALLOWLIST_ROOTS = [
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

# Denylist patterns
DENYLIST_PATTERNS = [
    "**/.venv/**",
    "**/site-packages/**",
    "**/build/**",
    "**/dist/**",
    "**/.git/**",
    "**/tests/**",
    "**/__pycache__/**",
]

FEATURE_KEYWORDS = [
    "vwap", "atr", "rsi", "macd", "bollinger", "feature", "indicator",
    "volume", "price", "f__", "rolling", "ewm", "resample", "ta",
    "orderflow", "ict", "sma", "ema", "std", "mean", "pct_change"
]


def should_include_file(file_path: Path) -> bool:
    """Check if file should be included based on allowlist/denylist."""
    # Check denylist
    for pattern in DENYLIST_PATTERNS:
        if file_path.match(pattern):
            return False

    # Check allowlist: must be under allowed roots and in allowed subdirs
    allowed_subdirs = ["src", "lib", "features"]
    for root in ALLOWLIST_ROOTS:
        try:
            file_path.relative_to(root)
            # Check if any parent is in allowed_subdirs
            parts = file_path.relative_to(root).parts
            if any(part in allowed_subdirs for part in parts):
                return True
        except ValueError:
            continue
    return False


def is_feature_function(node: ast.FunctionDef | ast.ClassDef, content: str) -> bool:
    """Advanced heuristic to detect feature builders."""
    name = node.name.lower()
    docstring = ast.get_docstring(node) or ""

    # Check name/docstring keywords
    if not any(kw in name or kw in docstring.lower() for kw in FEATURE_KEYWORDS):
        return False

    # Check if takes DataFrame with ts and symbol
    has_df_param = False
    has_ts_symbol = False

    # Parse function signature
    if isinstance(node, ast.FunctionDef):
        for arg in node.args.args:
            arg_name = arg.arg.lower()
            if arg_name in ["df", "data", "bars"]:
                has_df_param = True
            # Check annotations or defaults for DataFrame
            if arg.annotation:
                ann_str = ast.unparse(arg.annotation).lower()
                if "dataframe" in ann_str or "pd.dataframe" in ann_str:
                    has_df_param = True

    # Check content for ts/symbol references
    if "ts" in content and ("symbol" in content or "ticker" in content):
        has_ts_symbol = True

    # Check for pandas operations
    pandas_ops = ["rolling", "ewm", "resample", "groupby", "apply", "transform"]
    has_pandas_ops = any(op in content for op in pandas_ops)

    return (has_df_param or has_ts_symbol) and has_pandas_ops


def parse_for_features(file_path: Path) -> List[Dict[str, Any]]:
    """Parse file for potential feature builders with detailed analysis."""
    features = []
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=str(file_path))
    except Exception:
        return features

    content_hash = hashlib.md5(content.encode()).hexdigest()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if is_feature_function(node, content):
                name = node.name
                docstring = ast.get_docstring(node) or ""

                # Analyze inputs/outputs
                inputs = []
                outputs = []
                if isinstance(node, ast.FunctionDef):
                    # Simple input analysis
                    for arg in node.args.args:
                        inputs.append(arg.arg)

                    # Look for return statements or assignments
                    for child in ast.walk(node):
                        if isinstance(child, ast.Return):
                            if isinstance(child.value, ast.Name):
                                outputs.append(child.value.id)
                        elif isinstance(child, ast.Assign):
                            for target in child.targets:
                                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                                    if target.value.id in inputs:
                                        outputs.append(ast.unparse(target).split('.')[-1])

                # Standardize feature names
                pack = file_path.parent.name
                standardized_name = f"f__{pack}__{name}"
                needs_adapter = not name.startswith("f__")

                # Purity/idempotence (heuristic)
                purity_flags = {
                    "idempotent": "apply" not in content,  # Assume apply might modify
                    "pure": "random" not in content.lower() and "time" not in content.lower(),
                }

                features.append({
                    "name": name,
                    "standardized_name": standardized_name,
                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                    "file": str(file_path),
                    "callable": f"{file_path.stem}.{name}",
                    "inputs": inputs,
                    "outputs": list(set(outputs)),  # Dedupe
                    "feature_names": [standardized_name] if needs_adapter else [name],
                    "purity_flags": purity_flags,
                    "reuse_count": 1,  # Will be updated when clustering
                    "content_hash": content_hash,
                    "needs_adapter": needs_adapter,
                    "docstring": docstring[:200],
                })

    return features


def cluster_duplicates(features: List[Dict]) -> List[Dict]:
    """Cluster features by content hash and update reuse counts."""
    hash_groups = {}
    for feat in features:
        h = feat["content_hash"]
        if h not in hash_groups:
            hash_groups[h] = []
        hash_groups[h].append(feat)

    clustered = []
    for group in hash_groups.values():
        if len(group) > 1:
            # Update reuse count
            for feat in group:
                feat["reuse_count"] = len(group)
        clustered.extend(group)

    return clustered


def scan_features_v2() -> Dict[str, Any]:
    """Scan for features with allowlist/denylist."""
    catalog = []

    for root in ALLOWLIST_ROOTS:
        repo = Path(root)
        if not repo.exists():
            continue

        for py_file in repo.rglob("*.py"):
            if should_include_file(py_file):
                features = parse_for_features(py_file)
                catalog.extend(features)

    # Cluster duplicates
    catalog = cluster_duplicates(catalog)

    # Separate conforming and needing adapters
    conforming = [f for f in catalog if not f["needs_adapter"]]
    needing_adapters = [f for f in catalog if f["needs_adapter"]]

    return {
        "catalog": catalog,
        "conforming": conforming,
        "needing_adapters": needing_adapters,
    }


def main():
    """Main entry point."""
    result = scan_features_v2()

    out_dir = Path("~/quantstack/qx-scan/out").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # features_catalog_v2.json
    with open(out_dir / "features_catalog_v2.json", "w") as f:
        json.dump(result, f, indent=2)

    # features_catalog_v2.md
    md_content = "# Features Catalog v2\n\n"
    for feat in result["catalog"]:
        md_content += f"## {feat['standardized_name']}\n"
        md_content += f"- **Type:** {feat['type']}\n"
        md_content += f"- **File:** {feat['file']}\n"
        md_content += f"- **Callable:** {feat['callable']}\n"
        md_content += f"- **Inputs:** {', '.join(feat['inputs'])}\n"
        md_content += f"- **Outputs:** {', '.join(feat['outputs'])}\n"
        md_content += f"- **Feature Names:** {', '.join(feat['feature_names'])}\n"
        md_content += f"- **Purity:** {feat['purity_flags']}\n"
        md_content += f"- **Reuse Count:** {feat['reuse_count']}\n"
        md_content += f"- **Needs Adapter:** {feat['needs_adapter']}\n"
        md_content += f"- **Docstring:** {feat['docstring']}\n\n"

    with open(out_dir / "features_catalog_v2.md", "w") as f:
        f.write(md_content)

    # feature_adapters_todo.md
    todo_content = "# Feature Adapters TODO\n\n"
    for feat in result["needing_adapters"]:
        todo_content += f"## {feat['name']} -> {feat['standardized_name']}\n"
        todo_content += f"- **File:** {feat['file']}\n"
        todo_content += f"- **Current:** {feat['name']}\n"
        todo_content += f"- **Target:** {feat['standardized_name']}\n"
        todo_content += f"- **Inputs:** {feat['inputs']}\n"
        todo_content += f"- **Outputs:** {feat['outputs']}\n"
        todo_content += "- **Adapter needed:** Thin wrapper to conform to protocol\n\n"

    with open(out_dir / "feature_adapters_todo.md", "w") as f:
        f.write(todo_content)

    print(f"Feature scan v2 complete. Outputs in {out_dir}")


if __name__ == "__main__":
    main()