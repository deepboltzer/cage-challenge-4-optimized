# EnterpriseHeuristicAgent v10-final: Change Documentation

**Date**: 2026-04-07
**File**: `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgentV10Final.py`

---

## Summary

v10-final combines two independently-validated improvements into one agent:
- **Blocking-first priority** (from v10 experiment)
- **Restore-only threat response** (from v10b experiment)

Plus targeted optimizations from Oracle V3 analysis and ablation data.

---

## Performance Table

| Agent | Mean Reward | Std | 95% CI | Notes |
|-------|-----------|-----|--------|-------|
| SleepAgent | -30,578.9 | 6,195 | -- | Lower bound |
| v9.1 baseline | -1,039.3 | 550.7 | [-1147, -931] | 100 eps, seed 42 |
| v10-final | TBD | TBD | TBD | Pending full eval |
| Oracle V3 | -893.5 | 206.7 | -- | Upper bound (ground truth) |

Quick validation (10 eps, seed 42):
| Agent | Mean | Std |
|-------|------|-----|
| v9.1 | -998.0 | 346.1 |
| v10-final | -854.0 | 133.3 |
| **Delta** | **+144.0** | **-212.8 (lower variance)** |

---

## Changes with Justification

### Change 1: Block/Allow at Priority 1-2 (was 2-3)

**What**: Move `BlockTrafficZone` and `AllowTrafficZone` above all alert response actions.

**Before (v9.1)**:
```
P1:  RESTORE on conn + (malfile OR proc)
P1b: RESTORE on conn-only without decoy
P1c: RESTORE on pure malfile
P2:  ALLOW per comms_policy
P3:  BLOCK per comms_policy
P4:  REMOVE on proc flags
...
```

**After (v10-final)**:
```
P1:  BLOCK per comms_policy
P2:  ALLOW per comms_policy
P3:  RESTORE on conn + (malfile OR proc)
P3b: RESTORE on conn-only without decoy
P3c: RESTORE on pure malfile
P4:  RESTORE on proc flags (smart threshold)
...
```

**Justification**: Oracle V3 scored -893.5 vs Oracle V1's -1678.7 (which blocked at priority 3). The single biggest improvement was blocking before any alert response. Blocking is free (no reward cost), instant (1 step), and prevents an entire subnet from being reached. Responding to one compromised host (Restore: 5 steps, -1 cost) is less urgent than preventing new compromises across multiple hosts.

**Reference**: `docs/swarm_analysis/oracle_architecture.md`, Section 3 ("Why V3 succeeds where V1/V2 failed")

### Change 2: Remove Eliminated (Restore-only)

**What**: Remove action is never issued. All threat response uses Restore exclusively.

**Before (v9.1)**: Priority 4 tries Remove first on proc-flag-only alerts. If flag persists after Remove (3 steps), escalates to Restore.

**After (v10-final)**: Priority 4 goes directly to Restore with a flag_age threshold to filter green false positives.

**Justification**: Ablation study showed Restore-only scored -931.7 +/- 221.7 vs full agent -1037.2 +/- 610.4 (30 episodes, seed 42). Remove is:
- 90% success rate (10% failure causes escalation cascade)
- 3 steps duration (PrivEsc is 100% success in 2 steps; red gets root before Remove completes)
- Cannot evict root sessions (only user sessions)
- The 3-step delay while Remove runs is 3 steps of unmitigated damage

Restore is definitive: evicts ALL sessions, costs -1 but saves downstream damage.

**Reference**: `docs/optimality_analysis.md`, Section 4 ("Remove is expendable")

### Change 3: Smart Restore Thresholds

**What**: flag_age-based threshold for proc-flag Restore decisions:

| Context | Threshold | Rationale |
|---------|-----------|-----------|
| Default | flag_age >= 1 | Green FPs clear within 1 step |
| Impact target (OZ server_host_0) | flag_age >= 0 | -10/step Impact penalty >> FP Restore cost |
| High-priority host (>= 100) | flag_age >= 0 | Mission-critical hosts |
| T3 escalation (upstream saturated) | flag_age >= 0 | Upstream zone overwhelmed |

**Justification**: Green process FP rate is 0.776% (69 per episode). flag_age >= 1 filters most FPs since green FP events are transient (1 step). But on Impact targets during active missions, DegradeServices is invisible (no observable events), runs at 100% success, and causes cascading LWF damage (83.3% of total cost per `docs/swarm_analysis/environment_mechanics_database.md`). The cost of one false-positive Restore (-1) is negligible compared to one step of unmitigated root presence.

**Reference**: Oracle V3 `_is_impact_target` logic; `docs/swarm_analysis/red_attack_chain_database.md` (DegradeServices 50% probability in R/RD state)

### Change 4: MAX_DECOYS Reduced from 3 to 2

**What**: Deploy 2 decoys per host instead of 3.

**Before**: 3 decoys + 1 legit service = 75% red exploit failure rate, ~45 actions for initial deployment.

**After**: 2 decoys + 1 legit service = 67% red exploit failure rate, ~30 actions for initial deployment.

**Justification**: Oracle V3 uses zero decoys and scores -893.5. The heuristic needs decoys for detection (lacks ground truth), but 3 per host consumes too much of the initial action budget. Reducing to 2 frees ~15 actions for blocking and restoring during the critical early Phase 0 period. The marginal detection loss (75% -> 67%) is small compared to the action budget freed.

**Reference**: `docs/optimality_analysis.md`, Section 6 (action budget: 15.8% DeployDecoy)

### Change 5: RZ->OZ Block Priority (retained)

**What**: RZ->OZ subnet pair gets priority 250 at phase transitions (highest blocking priority). Contractor/internet entries get priority 200.

**Justification**: Red is likely already in the restricted zone by Phase 1/2 start (167 steps of uncontested Phase 0). The RZ->OZ path is the direct lateral movement route to mission-critical hosts. Blocking this first cuts the most dangerous attack vector.

**Reference**: Already in v9.1 `_pair_priority`; confirmed by Oracle V3 pair_priority logic

---

## Per-Phase Analysis

(To be updated with full evaluation data)

### Expected Improvements by Phase

| Phase | v9.1 Loss/step | Expected v10 Change | Mechanism |
|-------|---------------|--------------------:|-----------|
| Phase 0 (1-167) | -3.10 | Marginal | No blocks available; Restore-only + fewer decoys may help |
| Phase 1 (168-334) | -1.70 | Significant | Blocking 1-2 steps earlier per phase transition |
| Phase 2 (335-500) | -1.42 | Significant | Same; plus reduced transition spike |

---

## Cross-Seed Validation

(To be updated with full evaluation data)

v9.1 reference: mean -1044.7, std 50.4, CV 4.8% (seeds 42, 123, 456, 789, 1337)

---

## Files

| File | Purpose |
|------|---------|
| `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgentV10Final.py` | v10-final agent |
| `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgentV10.py` | v10 blocking-first experiment |
| `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgentV10b.py` | v10b Restore-only experiment |
| `scripts/evaluate_v10.py` | Comparison evaluation (30 ep + cross-seed) |
| `scripts/evaluate_v10_submission.py` | Official format evaluation (100 ep) |
| `CybORG/Evaluation/submission/submission.py` | Official submission adapter |
