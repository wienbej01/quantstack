# GCP e2-micro Feasibility Assessment for L2 Collector Service

**Assessment Date:** 2026-01-14  
**Target VM:** GCP e2-micro (34.126.104.195)  
**Current System:** Local laptop (29GB RAM, high-spec)

---

## Executive Summary

**❌ NOT RECOMMENDED** - The GCP e2-micro instance is **insufficient** for reliably running your l2-collector service with IBKR Client Portal Gateway.

**Critical Issues:**
1. **Insufficient Memory**: 1GB RAM vs 4GB minimum requirement
2. **CPU Constraints**: 0.25 vCPU (shared) vs recommended Intel i5+
3. **Java Runtime Overhead**: Client Portal Gateway alone needs ~500MB-1GB
4. **Service Memory Usage**: Current l2-collector uses 45MB + 142MB peak + 56MB swap

---

## Resource Requirements Analysis

### IBKR Client Portal Gateway Requirements

**Official IBKR Requirements (Linux):**
- **Minimum RAM:** 4GB
- **Recommended RAM:** 16GB
- **Minimum CPU:** Intel i5
- **Recommended CPU:** Intel i7+
- **Java Runtime:** Required (JRE 8 update 192+)

**Actual Resource Usage:**
- **Gateway Memory:** ~500MB-1GB (Java process)
- **Gateway CPU:** 40% less than TWS, but still significant
- **Disk Space:** ~70MB (Docker image reference)

### Your L2 Collector Service Requirements

**Current Observed Usage (from systemctl status):**
```
Memory: 45M (peak: 142.1M, swap: 56.5M)
CPU: 1.484s over 1h 8min runtime
Tasks: 9 threads
```

**IBKR Platform Service:**
```
Memory: 17.1M (max: 512M, peak: 54.7M, swap: 28.3M)
CPU: 7.748s
Tasks: 2 threads
```

**Total Combined Requirements:**
- **Minimum Memory:** ~600-800MB (Gateway + Platform + Collector)
- **Realistic Memory:** 1.5-2GB (with headroom for peaks)
- **CPU:** Moderate (data collection + REST API + Java runtime)

### GCP e2-micro Specifications

**Available Resources:**
- **vCPU:** 2 vCPU (but only 0.25 vCPU sustained, 1/8 shared physical core)
- **Memory:** 1GB RAM (1024MB)
- **Burst Capability:** Can burst to 2 vCPUs for short periods
- **Cost:** ~$7.11/month (us-central1)

**Resource Comparison:**
```
Component              Required    e2-micro    Gap
─────────────────────────────────────────────────
RAM (Minimum)          4GB         1GB         -3GB ❌
RAM (Realistic)        1.5-2GB     1GB         -0.5-1GB ❌
CPU (Sustained)        1+ core     0.25 vCPU   -0.75 ❌
CPU (Burst)            OK          2 vCPU      ✓
```

---

## Multiple IBKR Gateway Instances

### Can You Run 2 Instances Simultaneously?

**✅ YES - With Limitations**

**IBKR Policy:**
- **Same Account, Different Machines:** ❌ NOT ALLOWED
- **Different Accounts, Different Machines:** ✅ ALLOWED
- **Same Machine, Multiple Client IDs:** ✅ ALLOWED (up to 32 clients per Gateway)

**From Research:**
> "You can only use one IB account per machine" - EliteTrader Forum
> 
> "Up to thirty-two clients can be connected to a single instance of the TWS/Gateway simultaneously" - StackOverflow

**Your Situation:**
- **Current Setup:** Single Gateway on laptop → Platform (port 8000) → l2-collector (client ID 1)
- **Proposed Setup:** Gateway on VM + Gateway on laptop = ❌ **NOT SUPPORTED**

**Why It Won't Work:**
1. IBKR detects simultaneous logins from different IPs
2. Second login will disconnect the first
3. You'll get "Already logged in" errors
4. Data feeds will be unreliable

**Workaround Options:**
1. **Use Paper + Live Accounts:** Run paper on VM, live on laptop (requires 2 accounts)
2. **Single Gateway, Multiple Clients:** Run Gateway on one machine, connect both services via network
3. **Time-Based Switching:** Run VM during market hours, laptop for development (not simultaneous)

---

## Recommended Alternatives

### Option 1: Upgrade to e2-small (RECOMMENDED)

**Specifications:**
- **vCPU:** 2 vCPU (0.5 vCPU sustained)
- **Memory:** 2GB RAM
- **Cost:** ~$14.22/month (+$7/month vs e2-micro)

**Assessment:** ⚠️ **MARGINAL** - Meets minimum but no headroom

### Option 2: Upgrade to e2-medium (IDEAL)

**Specifications:**
- **vCPU:** 2 vCPU (1 vCPU sustained)
- **Memory:** 4GB RAM
- **Cost:** ~$28.44/month (+$21/month vs e2-micro)

**Assessment:** ✅ **RECOMMENDED** - Meets IBKR minimum requirements

### Option 3: Use n2-standard-2 (PRODUCTION GRADE)

**Specifications:**
- **vCPU:** 2 vCPU (full dedicated cores)
- **Memory:** 8GB RAM
- **Cost:** ~$48.54/month (+$41/month vs e2-micro)

**Assessment:** ✅ **BEST** - Exceeds requirements, production-ready

### Option 4: Keep Gateway on Laptop, Run Collector on VM

**Architecture:**
- **Laptop:** IBKR Client Portal Gateway (port 5000) + Platform (port 8000)
- **VM:** l2-collector service only (connects to laptop via network)

**Requirements:**
- **VM Specs:** e2-micro sufficient (only Python service, no Gateway)
- **Network:** Expose port 8000 on laptop (firewall rules + SSH tunnel)
- **Reliability:** Laptop must stay online during market hours

**Assessment:** ✅ **COST-EFFECTIVE** - Works with e2-micro, but laptop dependency

---

## Risk Analysis

### Running on e2-micro (Current Plan)

**High Risk Factors:**
1. **OOM Kills:** Java Gateway will likely trigger out-of-memory killer
2. **Swap Thrashing:** 1GB RAM insufficient, will rely heavily on swap
3. **CPU Throttling:** Sustained load will hit 0.25 vCPU limit
4. **Service Instability:** Frequent restarts, missed data collection windows
5. **Gateway Crashes:** Java heap errors under memory pressure

**Expected Behavior:**
- Gateway starts but crashes within minutes/hours
- Collector fails to connect or times out
- Systemd restart loops
- Data gaps during market hours

### Running on e2-medium (Recommended)

**Low Risk Factors:**
1. **Meets Minimum:** 4GB RAM matches IBKR requirement
2. **Headroom:** Enough for OS + Gateway + Platform + Collector
3. **Stable Operation:** No swap thrashing or OOM kills
4. **Production Viable:** Can run reliably during market hours

---

## Network Architecture Considerations

### Current Architecture (Laptop)
```
IBKR Client Portal Gateway (port 5000)
    ↓
IBKR Platform Service (port 8000)
    ↓
l2-collector (client ID 1)
```

### Proposed Architecture (VM Migration)
```
[VM: 34.126.104.195]
    IBKR Client Portal Gateway (port 5000)
        ↓
    IBKR Platform Service (port 8000)
        ↓
    l2-collector (client ID 1)

[Laptop]
    Development environment
    Manual trading (separate Gateway instance) ❌ NOT ALLOWED
```

### Alternative Architecture (Hybrid)
```
[Laptop]
    IBKR Client Portal Gateway (port 5000)
        ↓
    IBKR Platform Service (port 8000) [exposed via SSH tunnel]
        ↓
        ├─ Local services
        └─ [VM: 34.126.104.195]
               l2-collector (connects to laptop:8000)
```

---

## Cost-Benefit Analysis

### Monthly Costs (us-central1)

| Instance Type | vCPU | RAM | Cost/Month | Viability |
|---------------|------|-----|------------|-----------|
| e2-micro      | 0.25 | 1GB | $7.11      | ❌ Insufficient |
| e2-small      | 0.5  | 2GB | $14.22     | ⚠️ Marginal |
| e2-medium     | 1.0  | 4GB | $28.44     | ✅ Recommended |
| n2-standard-2 | 2.0  | 8GB | $48.54     | ✅ Production |

### Break-Even Analysis

**Current Laptop Costs:**
- **Power:** ~$5-10/month (24/7 operation)
- **Wear & Tear:** Reduced laptop lifespan
- **Reliability:** Must stay online, no mobility

**VM Benefits:**
- **Uptime:** 99.95% SLA (vs laptop reliability)
- **Mobility:** Laptop free for travel/development
- **Scalability:** Easy to upgrade resources
- **Monitoring:** GCP monitoring/alerting built-in

**Recommendation:** e2-medium ($28/month) is worth the cost for production reliability

---

## Migration Checklist

### If Proceeding with e2-medium (Recommended)

- [ ] Provision GCP e2-medium instance (4GB RAM, 1 vCPU)
- [ ] Install Java Runtime Environment (JRE 8+)
- [ ] Transfer IBKR Client Portal Gateway files
- [ ] Configure Gateway with your IBKR credentials
- [ ] Set up systemd services (ibkr-platform, l2-collector)
- [ ] Configure firewall rules (allow port 5000 for Gateway auth)
- [ ] Test authentication flow (browser login + 2FA)
- [ ] Verify data collection during market hours
- [ ] Set up monitoring/alerting (GCP + ntfy)
- [ ] Document failover procedure (back to laptop if needed)

### If Using Hybrid Architecture (e2-micro)

- [ ] Configure laptop firewall to allow port 8000
- [ ] Set up SSH tunnel or VPN between laptop and VM
- [ ] Modify l2-collector config to point to laptop IP
- [ ] Test connectivity from VM to laptop Platform
- [ ] Ensure laptop stays online during market hours
- [ ] Set up laptop monitoring (uptime alerts)

---

## Final Recommendation

### Primary Recommendation: e2-medium on GCP

**Rationale:**
1. Meets IBKR minimum requirements (4GB RAM)
2. Provides stable, reliable operation
3. Frees laptop for development/mobility
4. Cost-effective for production use ($28/month)
5. Easy to upgrade if needed

### Alternative: Hybrid Architecture

**If budget is critical:**
1. Keep Gateway + Platform on laptop
2. Run l2-collector on e2-micro VM
3. Connect via SSH tunnel
4. Accept laptop dependency

### Do NOT Attempt:

❌ Running full stack on e2-micro (will fail)  
❌ Running 2 Gateway instances on same account (IBKR will block)  
❌ Using e2-small (too marginal, will struggle)

---

## Testing Plan

### Phase 1: Proof of Concept (1 day)

1. Provision e2-medium instance
2. Install Java + Gateway
3. Test Gateway authentication
4. Verify Platform service starts
5. Run l2-collector for 1 hour

### Phase 2: Market Hours Test (1 week)

1. Run during full market day (9:30 AM - 4:00 PM ET)
2. Monitor memory usage (should stay under 3GB)
3. Monitor CPU usage (should stay under 80%)
4. Verify data collection completeness
5. Check for any OOM or crash events

### Phase 3: Production Cutover

1. Migrate all services to VM
2. Update DNS/monitoring
3. Decommission laptop services
4. Monitor for 1 week
5. Document any issues

---

## Conclusion

The GCP e2-micro instance is **not suitable** for running your l2-collector service with IBKR Client Portal Gateway due to insufficient memory (1GB vs 4GB minimum) and CPU constraints.

**Upgrade to e2-medium ($28/month)** for reliable production operation, or use a **hybrid architecture** with Gateway on laptop and collector on e2-micro if budget is critical.

**You cannot run 2 IBKR Gateway instances simultaneously on the same account** - IBKR will disconnect the first session when the second logs in.

---

## References

1. [IBKR TWS System Requirements](https://www.interactivebrokers.com/en/trading/tws-requirements.php) - Official minimum: 4GB RAM, Intel i5
2. [GCP e2-micro Specs](https://cloudprice.net/gcp/compute/instances/e2-micro) - 1GB RAM, 0.25 vCPU sustained
3. [IBKR Gateway Resource Usage](https://interactivebrokers.github.io/tws-api/initial_setup.html) - "40% fewer resources than TWS"
4. [Client Portal Docker Image](https://osquant.com/papers/dockerising-interactive-brokers-client-portal-api/) - ~70MB image size
5. StackOverflow: "Up to 32 clients per Gateway instance, but only one Gateway per account per machine"

---

**Generated:** 2026-01-14 14:59 PST  
**System:** quantstack l2-collector migration assessment
