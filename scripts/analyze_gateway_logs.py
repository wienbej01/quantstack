#!/usr/bin/env python3
"""
Analyze IBKR Gateway logs for unusual behavior and connection issues.
"""
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_timestamp(line: str) -> datetime | None:
    """Extract timestamp from log line."""
    match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") if match else None


def analyze_gateway_logs(log_path: str) -> dict:
    """Analyze Gateway logs for issues."""
    
    patterns = {
        "client_disconnects": r"Socket connection for client\{(\d+)\} has closed\. Reason: (.+)",
        "errors": r"\[II\] ERROR",
        "warnings": r"\[II\] WARN",
        "farm_disconnects": r"Lost active connection with disconnect status (.+)",
        "reconnects": r"Farm .+ Connected",
        "critical_errors": r"CRITICAL|FATAL|Exception",
    }
    
    results = {
        "client_disconnects": [],
        "errors": [],
        "warnings": [],
        "farm_disconnects": [],
        "reconnects": [],
        "critical_errors": [],
        "client_disconnect_summary": defaultdict(int),
        "disconnect_reasons": defaultdict(int),
    }
    
    with open(log_path, "r") as f:
        for line in f:
            ts = parse_timestamp(line)
            
            # Client disconnects
            if match := re.search(patterns["client_disconnects"], line):
                client_id, reason = match.groups()
                results["client_disconnects"].append({
                    "timestamp": ts,
                    "client_id": client_id,
                    "reason": reason,
                    "line": line.strip()
                })
                results["client_disconnect_summary"][client_id] += 1
                results["disconnect_reasons"][reason] += 1
            
            # Errors
            elif patterns["errors"] in line:
                results["errors"].append({
                    "timestamp": ts,
                    "line": line.strip()
                })
            
            # Warnings
            elif patterns["warnings"] in line:
                results["warnings"].append({
                    "timestamp": ts,
                    "line": line.strip()
                })
            
            # Farm disconnects
            elif match := re.search(patterns["farm_disconnects"], line):
                status = match.group(1)
                results["farm_disconnects"].append({
                    "timestamp": ts,
                    "status": status,
                    "line": line.strip()
                })
            
            # Reconnects
            elif patterns["reconnects"] in line:
                results["reconnects"].append({
                    "timestamp": ts,
                    "line": line.strip()
                })
            
            # Critical errors
            elif re.search(patterns["critical_errors"], line, re.IGNORECASE):
                results["critical_errors"].append({
                    "timestamp": ts,
                    "line": line.strip()
                })
    
    return results


def print_report(results: dict):
    """Print analysis report."""
    
    print("=" * 80)
    print("IBKR GATEWAY LOG ANALYSIS")
    print("=" * 80)
    print()
    
    # Critical issues
    if results["critical_errors"]:
        print(f"🔴 CRITICAL ERRORS: {len(results['critical_errors'])}")
        for item in results["critical_errors"][-10:]:
            print(f"  {item['timestamp']} - {item['line'][:100]}")
        print()
    
    # Farm disconnects (IBKR server connection loss)
    if results["farm_disconnects"]:
        print(f"⚠️  FARM DISCONNECTS: {len(results['farm_disconnects'])}")
        for item in results["farm_disconnects"]:
            print(f"  {item['timestamp']} - Status: {item['status']}")
        print()
    
    # Client disconnects summary
    if results["client_disconnect_summary"]:
        print(f"📊 CLIENT DISCONNECT SUMMARY:")
        for client_id, count in sorted(results["client_disconnect_summary"].items()):
            print(f"  Client {client_id}: {count} disconnects")
        print()
        
        print(f"📊 DISCONNECT REASONS:")
        for reason, count in sorted(results["disconnect_reasons"].items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")
        print()
    
    # Recent client disconnects
    if results["client_disconnects"]:
        print(f"🔌 RECENT CLIENT DISCONNECTS (last 10):")
        for item in results["client_disconnects"][-10:]:
            print(f"  {item['timestamp']} - Client {item['client_id']}: {item['reason']}")
        print()
    
    # Error summary
    print(f"📈 SUMMARY:")
    print(f"  Total Errors: {len(results['errors'])}")
    print(f"  Total Warnings: {len(results['warnings'])}")
    print(f"  Total Client Disconnects: {len(results['client_disconnects'])}")
    print(f"  Farm Disconnects: {len(results['farm_disconnects'])}")
    print(f"  Reconnects: {len(results['reconnects'])}")
    print()
    
    # Recent errors (sample)
    if results["errors"]:
        print(f"🔍 RECENT ERRORS (last 5):")
        for item in results["errors"][-5:]:
            print(f"  {item['timestamp']} - {item['line'][:120]}")
        print()
    
    # Health assessment
    print("=" * 80)
    print("HEALTH ASSESSMENT:")
    print("=" * 80)
    
    issues = []
    
    if results["farm_disconnects"]:
        issues.append(f"⚠️  Gateway lost connection to IBKR servers {len(results['farm_disconnects'])} time(s)")
    
    if results["critical_errors"]:
        issues.append(f"🔴 {len(results['critical_errors'])} critical errors detected")
    
    # Check for excessive disconnects
    for client_id, count in results["client_disconnect_summary"].items():
        if count > 10:
            issues.append(f"⚠️  Client {client_id} disconnected {count} times (possible connection leak)")
    
    # Check disconnect reasons
    if "Connection terminated" in results["disconnect_reasons"]:
        count = results["disconnect_reasons"]["Connection terminated"]
        if count > 20:
            issues.append(f"⚠️  {count} 'Connection terminated' events (possible reconnection bug)")
    
    if issues:
        for issue in issues:
            print(issue)
    else:
        print("✅ No major issues detected")
    
    print()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze IBKR Gateway logs")
    parser.add_argument(
        "--gateway-log",
        default="/home/jacobw/gateway-exported-logs.txt",
        help="Path to Gateway log file"
    )
    parser.add_argument(
        "--api-log",
        default="/home/jacobw/api-exported-logs.txt",
        help="Path to API log file"
    )
    
    args = parser.parse_args()
    
    if not Path(args.gateway_log).exists():
        print(f"Error: Gateway log not found at {args.gateway_log}")
        return 1
    
    results = analyze_gateway_logs(args.gateway_log)
    print_report(results)
    
    return 0


if __name__ == "__main__":
    exit(main())
