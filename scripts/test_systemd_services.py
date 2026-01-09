#!/usr/bin/env python3
"""
Systemd Service Test Suite for Trading System

Run this BEFORE market hours to catch silent failures.
Usage: python scripts/test_systemd_services.py
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str


def run_cmd(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run command and return exit code, stdout, stderr"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)


def test_service_file_exists(service: str) -> TestResult:
    """Check if service file exists"""
    path = Path(f"/etc/systemd/system/{service}.service")
    if path.exists():
        return TestResult(f"{service}_file_exists", True, "OK")
    return TestResult(f"{service}_file_exists", False, f"Missing: {path}")


def test_service_syntax(service: str) -> TestResult:
    """Check service file syntax"""
    code, out, err = run_cmd(f"systemd-analyze verify /etc/systemd/system/{service}.service 2>&1")
    # systemd-analyze verify returns warnings but exit 0 for valid files
    if "Failed" in out or "failed" in out.lower():
        return TestResult(f"{service}_syntax", False, out[:200])
    return TestResult(f"{service}_syntax", True, "OK")


def test_python_imports(service: str, test_cmd: str) -> TestResult:
    """Test Python imports for a service"""
    code, out, err = run_cmd(test_cmd, timeout=30)
    if code == 0:
        return TestResult(f"{service}_imports", True, "OK")
    return TestResult(f"{service}_imports", False, (err or out)[:300])


def test_service_can_start(service: str) -> TestResult:
    """Check if service can start (dry-run where possible)"""
    code, out, err = run_cmd(f"systemctl cat {service}.service")
    if code != 0:
        return TestResult(f"{service}_loadable", False, "Cannot load service")
    return TestResult(f"{service}_loadable", True, "OK")


def test_working_directory(service: str) -> TestResult:
    """Check if WorkingDirectory exists"""
    code, out, err = run_cmd(f"systemctl show {service}.service -p WorkingDirectory --value")
    workdir = out.strip()
    if workdir and not Path(workdir).exists():
        return TestResult(f"{service}_workdir", False, f"Missing: {workdir}")
    return TestResult(f"{service}_workdir", True, f"OK: {workdir or 'default'}")


def test_exec_start(service: str) -> TestResult:
    """Check if ExecStart binary exists"""
    code, out, err = run_cmd(f"systemctl show {service}.service -p ExecStart --value")
    exec_start = out.strip()
    if not exec_start:
        return TestResult(f"{service}_execstart", False, "No ExecStart defined")
    
    # Handle systemd's output format: { path=/usr/bin/python3 ; argv[]=/usr/bin/python3 ... }
    # Extract the path= value
    if "path=" in exec_start:
        import re
        match = re.search(r'path=([^\s;]+)', exec_start)
        if match:
            binary = match.group(1)
        else:
            binary = ""
    else:
        # Fallback: extract first word
        binary = exec_start.split()[0] if exec_start else ""
    
    if binary and not Path(binary).exists():
        return TestResult(f"{service}_execstart", False, f"Missing binary: {binary}")
    return TestResult(f"{service}_execstart", True, f"OK: {binary}")


def test_environment_file(service: str) -> TestResult:
    """Check if EnvironmentFile exists (if specified)"""
    code, out, err = run_cmd(f"systemctl show {service}.service -p EnvironmentFile --value")
    env_file = out.strip()
    if env_file and not Path(env_file).exists():
        return TestResult(f"{service}_envfile", False, f"Missing: {env_file}")
    return TestResult(f"{service}_envfile", True, f"OK: {env_file or 'none'}")


def main():
    print("=" * 70)
    print("TRADING SYSTEM SYSTEMD SERVICE TEST SUITE")
    print("=" * 70)
    
    services = [
        "l2-collector",
        "l2-scalping", 
        "l2-watchdog",
        "intraday-paper",
        "intraday-sip",
        "trading-orchestrator",
    ]
    
    # Python import tests
    import_tests = {
        "l2-collector": "/home/jacobw/.local/bin/l2-collect --help",
        "l2-scalping": "cd /home/jacobw/quantstack/l2_scalping && PYTHONPATH=/home/jacobw/quantstack/l2_scalping/src /usr/bin/python3 -c 'from main import main'",
        "l2-watchdog": "/home/jacobw/quantstack/.venv/bin/python -c \"exec(open('/home/jacobw/quantstack/scripts/l2_watchdog.py').read().split('if __name__')[0])\"",
        "trading-orchestrator": "/home/jacobw/quantstack/.venv/bin/python -c 'from bulletproof_orchestrator import BulletproofOrchestrator'",
    }
    
    results: list[TestResult] = []
    
    for service in services:
        print(f"\n--- Testing {service} ---")
        
        # Basic tests
        results.append(test_service_file_exists(service))
        results.append(test_service_syntax(service))
        results.append(test_service_can_start(service))
        results.append(test_working_directory(service))
        results.append(test_exec_start(service))
        results.append(test_environment_file(service))
        
        # Python import test if available
        if service in import_tests:
            results.append(test_python_imports(service, import_tests[service]))
    
    # Print results
    print("\n" + "=" * 70)
    print("TEST RESULTS")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"{status} | {r.name}: {r.message[:60]}")
        if r.passed:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} passed, {failed} failed")
    print("=" * 70)
    
    # Check current service status
    print("\n--- CURRENT SERVICE STATUS ---")
    for service in services:
        code, out, err = run_cmd(f"systemctl is-active {service}.service")
        status = out.strip()
        enabled_code, enabled_out, _ = run_cmd(f"systemctl is-enabled {service}.service")
        enabled = enabled_out.strip()
        
        if status == "active":
            icon = "🟢"
        elif status == "inactive":
            icon = "⚪"
        else:
            icon = "🔴"
        
        print(f"{icon} {service}: {status} ({enabled})")
    
    # Check timers
    print("\n--- TIMER STATUS ---")
    timers = ["l2-collector", "trading-orchestrator", "intraday-sip", "intraday-paper"]
    for timer in timers:
        code, out, err = run_cmd(f"systemctl is-active {timer}.timer")
        status = out.strip()
        icon = "🟢" if status == "active" else "⚪"
        
        # Get next trigger time
        code2, out2, _ = run_cmd(f"systemctl show {timer}.timer -p NextElapseUSecRealtime --value")
        next_run = out2.strip()[:19] if out2.strip() else "N/A"
        
        print(f"{icon} {timer}.timer: {status} (next: {next_run})")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
