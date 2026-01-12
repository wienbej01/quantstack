#!/usr/bin/env python3
"""
IBKR Gateway Connection Manager
- Monitors gateway health and client connections
- Kills zombie connections when services fail to connect
- Restarts gateway and triggers service reconnects when needed
"""
import subprocess
import socket
import time
import sys
import os
from datetime import datetime

# Configuration
GATEWAY_PORT = int(os.environ.get('IBKR_GATEWAY_PORT', 7497))
GATEWAY_HOST = os.environ.get('IBKR_GATEWAY_HOST', '127.0.0.1')
MAX_CONNECTIONS = int(os.environ.get('IBKR_MAX_CONNECTIONS', 8))
HEALTH_CHECK_INTERVAL = int(os.environ.get('IBKR_HEALTH_INTERVAL', 30))
MAX_FAILED_CHECKS = int(os.environ.get('IBKR_MAX_FAILED_CHECKS', 3))

# Services that depend on IBKR gateway
DEPENDENT_SERVICES = [
    'l2-collector.service',
    'l2-scalping.service',
    'intraday-paper.service',
    'intraday-sip.service',
]

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def get_gateway_connections():
    """Get current connections to gateway port"""
    try:
        result = subprocess.run(
            ['ss', '-tn', f'sport = :{GATEWAY_PORT}'],
            capture_output=True, text=True, timeout=5
        )
        lines = [l for l in result.stdout.strip().split('\n') if 'ESTAB' in l]
        return len(lines)
    except:
        return -1

def check_gateway_responsive():
    """Check if gateway accepts connections"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((GATEWAY_HOST, GATEWAY_PORT))
        sock.close()
        return result == 0
    except:
        return False

def get_service_status(service):
    """Check if a systemd service is active"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == 'active'
    except:
        return False

def get_failed_services():
    """Get list of dependent services that should be running but aren't connected"""
    failed = []
    for service in DEPENDENT_SERVICES:
        if get_service_status(service):
            # Service is running - check if it's actually connected
            # (simplified: assume if gateway has fewer connections than running services, something's wrong)
            failed.append(service)
    return failed

def kill_zombie_connections():
    """Kill connections to gateway port to clear zombies"""
    log("Killing zombie connections...")
    try:
        # Get PIDs connected to gateway port
        result = subprocess.run(
            ['ss', '-tnp', f'sport = :{GATEWAY_PORT}'],
            capture_output=True, text=True, timeout=5
        )
        
        killed = 0
        for line in result.stdout.split('\n'):
            if 'pid=' in line:
                # Extract PID
                import re
                match = re.search(r'pid=(\d+)', line)
                if match:
                    pid = match.group(1)
                    # Don't kill the gateway itself
                    if 'ibgateway' not in line and 'java' not in line:
                        try:
                            subprocess.run(['kill', '-9', pid], timeout=5)
                            killed += 1
                        except:
                            pass
        
        log(f"Killed {killed} zombie connections")
        return killed
    except Exception as e:
        log(f"Error killing zombies: {e}")
        return 0

def restart_gateway():
    """Restart IBKR gateway service"""
    log("Restarting IBKR gateway...")
    try:
        subprocess.run(['systemctl', 'restart', 'ibkr-gateway.service'], timeout=30)
        time.sleep(10)  # Wait for gateway to start
        return True
    except Exception as e:
        log(f"Gateway restart failed: {e}")
        return False

def restart_dependent_services():
    """Restart all dependent services to reconnect"""
    log("Restarting dependent services...")
    for service in DEPENDENT_SERVICES:
        if get_service_status(service):
            try:
                log(f"  Restarting {service}")
                subprocess.run(['systemctl', 'restart', service], timeout=30)
                time.sleep(2)
            except Exception as e:
                log(f"  Failed to restart {service}: {e}")

def trigger_service_reconnect(service):
    """Trigger a single service to reconnect"""
    log(f"Triggering reconnect for {service}")
    try:
        subprocess.run(['systemctl', 'restart', service], timeout=30)
        return True
    except:
        return False

def health_check():
    """Perform health check and return status"""
    gateway_up = check_gateway_responsive()
    connections = get_gateway_connections()
    running_services = sum(1 for s in DEPENDENT_SERVICES if get_service_status(s))
    
    return {
        'gateway_up': gateway_up,
        'connections': connections,
        'running_services': running_services,
        'healthy': gateway_up and (connections >= 0)
    }

def monitor_loop():
    """Main monitoring loop"""
    log(f"Starting IBKR Gateway Monitor")
    log(f"Gateway: {GATEWAY_HOST}:{GATEWAY_PORT}")
    log(f"Monitoring services: {', '.join(DEPENDENT_SERVICES)}")
    
    failed_checks = 0
    last_connection_count = 0
    
    while True:
        try:
            status = health_check()
            
            if not status['gateway_up']:
                failed_checks += 1
                log(f"Gateway not responsive (fail {failed_checks}/{MAX_FAILED_CHECKS})")
                
                if failed_checks >= MAX_FAILED_CHECKS:
                    log("Gateway unresponsive - attempting recovery")
                    kill_zombie_connections()
                    time.sleep(5)
                    
                    if not check_gateway_responsive():
                        restart_gateway()
                        time.sleep(15)
                        restart_dependent_services()
                    
                    failed_checks = 0
            else:
                failed_checks = 0
                
                # Check for connection issues
                if status['connections'] > MAX_CONNECTIONS:
                    log(f"Too many connections ({status['connections']}), clearing zombies")
                    kill_zombie_connections()
                    time.sleep(5)
                    restart_dependent_services()
                
                # Check if connections dropped unexpectedly
                elif status['running_services'] > 0 and status['connections'] == 0:
                    log("Services running but no connections - triggering reconnects")
                    restart_dependent_services()
                
                # Log status periodically
                if status['connections'] != last_connection_count:
                    log(f"Status: Gateway UP, {status['connections']} connections, {status['running_services']} services")
                    last_connection_count = status['connections']
            
            time.sleep(HEALTH_CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            log("Shutting down monitor")
            break
        except Exception as e:
            log(f"Monitor error: {e}")
            time.sleep(HEALTH_CHECK_INTERVAL)

def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == 'status':
            status = health_check()
            print(f"Gateway: {'UP' if status['gateway_up'] else 'DOWN'}")
            print(f"Connections: {status['connections']}")
            print(f"Running services: {status['running_services']}")
            
        elif cmd == 'kill-zombies':
            kill_zombie_connections()
            
        elif cmd == 'restart-gateway':
            restart_gateway()
            
        elif cmd == 'restart-services':
            restart_dependent_services()
            
        elif cmd == 'recover':
            log("Manual recovery triggered")
            kill_zombie_connections()
            time.sleep(5)
            restart_gateway()
            time.sleep(15)
            restart_dependent_services()
            
        else:
            print(f"Usage: {sys.argv[0]} [status|kill-zombies|restart-gateway|restart-services|recover]")
            print("       Run without arguments to start monitor daemon")
    else:
        monitor_loop()

if __name__ == "__main__":
    main()
