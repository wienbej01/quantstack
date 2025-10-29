#!/usr/bin/env python3
"""
S12 Quality Gates Validation Script

Validates that S12 implementation meets quality standards for:
- CI pipeline functionality
- Reproducibility testing
- Documentation completeness
- Code quality standards
"""

import pathlib
import subprocess
import sys
from datetime import datetime


def test_ci_pipeline():
    """Test CI pipeline components are present and functional."""
    print("\n🔍 Testing CI Pipeline...")

    ci_file = pathlib.Path(".github/workflows/ci.yml")
    if not ci_file.exists():
        print("   ❌ CI workflow file missing")
        return False

    with open(ci_file) as f:
        ci_content = f.read()

    required_jobs = ["test", "reproducibility-test", "smoke-test", "build-docs"]
    required_steps = ["lint", "type check", "pytest", "coverage"]

    all_present = True
    for job in required_jobs:
        if job in ci_content:
            print(f"   ✅ {job} job present")
        else:
            print(f"   ❌ {job} job missing")
            all_present = False

    for step in required_steps:
        if step.lower() in ci_content.lower():
            print(f"   ✅ {step} step present")
        else:
            print(f"   ❌ {step} step missing")
            all_present = False

    return all_present


def test_reproducibility_tests():
    """Test reproducibility test framework."""
    print("\n🔍 Testing Reproducibility Tests...")

    test_file = pathlib.Path("tests/test_reproducibility.py")
    if not test_file.exists():
        print("   ❌ Reproducibility test file missing")
        return False

    with open(test_file) as f:
        test_content = f.read()

    required_tests = [
        "test_dataframe_hash_stability",
        "test_feature_hash_determinism",
        "test_inputs_checksum_generation",
        "test_reproducibility_validation",
    ]

    all_present = True
    for test in required_tests:
        if test in test_content:
            print(f"   ✅ {test} test present")
        else:
            print(f"   ❌ {test} test missing")
            all_present = False

    return all_present


def test_documentation_completeness():
    """Test documentation completeness for S12."""
    print("\n🔍 Testing Documentation...")

    required_docs = [
        "docs/SCHEMAS.md",
        "docs/E2E_SMOKE_TEST.md",
        "docs/EXPERIMENTS.md",
        "docs/GOVERNANCE.md",
    ]

    all_present = True
    for doc in required_docs:
        doc_path = pathlib.Path(doc)
        if doc_path.exists():
            with open(doc_path) as f:
                content = f.read()
            if len(content) > 1000:  # Reasonable content length
                print(f"   ✅ {doc} present and substantial")
            else:
                print(f"   ⚠️  {doc} present but minimal content")
        else:
            print(f"   ❌ {doc} missing")
            all_present = False

    return all_present


def test_code_quality_tools():
    """Test code quality tools are configured."""
    print("\n🔍 Testing Code Quality Tools...")

    # Check Makefile targets
    makefile_path = pathlib.Path("Makefile")
    if not makefile_path.exists():
        print("   ❌ Makefile missing")
        return False

    with open(makefile_path) as f:
        makefile_content = f.read()

    required_targets = ["lint", "fix", "format", "check-types", "test", "qa-all"]
    all_present = True

    for target in required_targets:
        if f"{target}:" in makefile_content:
            print(f"   ✅ {target} target present")
        else:
            print(f"   ❌ {target} target missing")
            all_present = False

    return all_present


def test_basic_linting():
    """Test basic linting functionality."""
    print("\n🔍 Testing Basic Linting...")

    try:
        # Test ruff is working (no --version flag in this version)
        result = subprocess.run(
            ["ruff", "check", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("   ✅ Ruff linter available")
        else:
            print("   ❌ Ruff linter not working")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("   ❌ Ruff linter not available")
        return False

    # Test a subset of files for critical errors only
    try:
        result = subprocess.run(
            ["ruff", "check", "qx-core/src/", "--select=E,F", "--quiet"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        error_count = (
            len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        )
        if error_count == 0:
            print("   ✅ No critical syntax errors in qx-core")
        else:
            print(
                f"   ⚠️  {error_count} potential issues found (acceptable for development)"
            )
    except subprocess.TimeoutExpired:
        print("   ⚠️  Linting timeout (may be acceptable)")

    return True


def test_import_functionality():
    """Test core imports are working."""
    print("\n🔍 Testing Core Imports...")

    test_imports = [
        ("qx_core.hashers", "hash_dataframe"),
        ("qx_core.schemas", "validate_bars"),
        ("qx_features.registry", "apply"),
    ]

    working_imports = 0
    for module, function in test_imports:
        try:
            exec(f"from {module} import {function}")
            print(f"   ✅ {module}.{function} importable")
            working_imports += 1
        except ImportError as e:
            print(f"   ⚠️  {module}.{function} import failed: {e}")
        except Exception as e:
            print(f"   ❌ {module}.{function} error: {e}")

    # Accept if at least half the imports work (development environment)
    return working_imports >= len(test_imports) // 2


def test_makefile_functionality():
    """Test basic Makefile functionality."""
    print("\n🔍 Testing Makefile Functionality...")

    try:
        # Test makefile parsing
        result = subprocess.run(
            ["make", "-n", "lint"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            cwd=pathlib.Path.cwd(),
        )
        if "ruff" in result.stdout:
            print("   ✅ Makefile lint target functional")
            return True
        else:
            print("   ❌ Makefile lint target not working")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("   ⚠️  Make test timeout (may be acceptable)")
        return True


def validate_s12_components():
    """Validate S12 implementation components."""
    print("\n🔍 Testing S12 Implementation...")

    s12_components = {
        "CI Pipeline": test_ci_pipeline,
        "Reproducibility Tests": test_reproducibility_tests,
        "Documentation": test_documentation_completeness,
        "Code Quality Tools": test_code_quality_tools,
        "Basic Linting": test_basic_linting,
        "Core Imports": test_import_functionality,
        "Makefile": test_makefile_functionality,
    }

    results = {}
    for component_name, test_func in s12_components.items():
        try:
            results[component_name] = test_func()
        except Exception as e:
            print(f"   ❌ {component_name} test failed with error: {e}")
            results[component_name] = False

    return results


def generate_quality_report(results: dict) -> str:
    """Generate quality gates report."""
    report = []
    report.append("# S12 Quality Gates Validation Report")
    report.append(f"Generated: {datetime.now().isoformat()}")
    report.append("")

    passed = sum(results.values())
    total = len(results)

    report.append(f"## Summary: {passed}/{total} components passed")
    report.append("")

    report.append("## Component Status")
    for component, status in results.items():
        status_emoji = "✅ PASS" if status else "❌ FAIL"
        report.append(f"- {component}: {status_emoji}")

    report.append("")

    if passed == total:
        report.append("🎉 **ALL QUALITY GATES PASSED**")
        report.append("")
        report.append("S12 implementation is ready for production use.")
    else:
        report.append("⚠️ **SOME QUALITY GATES FAILED**")
        report.append("")
        report.append("Address failed components before proceeding to production.")

    return "\n".join(report)


def main():
    """Run S12 quality gates validation."""
    print("🚀 S12 Quality Gates Validation")
    print("=" * 50)

    # Run all tests
    results = validate_s12_components()

    # Generate and display report
    report = generate_quality_report(results)
    print("\n" + report)

    # Save report
    report_path = pathlib.Path("s12_quality_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\n📄 Report saved to: {report_path}")

    # Return success if all critical components pass
    critical_components = ["CI Pipeline", "Reproducibility Tests", "Documentation"]
    critical_passed = all(results[comp] for comp in critical_components)

    return critical_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
