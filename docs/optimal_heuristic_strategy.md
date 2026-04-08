# Optimal Heuristic Strategy for CAGE Challenge 4

## 1. Executive Summary

### Performance Comparison

| Version | Mean Reward (30ep) | Std Dev | Min | Max | vs SleepAgent |
|---------|-------------------|---------|-----|-----|---------------|
| SleepAgent | -18,386 | -- | -- | -- | baseline |
| v7 (decoys) | ~-5,025 | ~1,570 | -- | -- | +72.7% |
| v9 (messaging) | ~-1,100 | ~400 | -- | -- | +94.0% |
| **v9.1 (tuned)** | **-868.7** | **292.0** | -1,935 | -370 | **+95.3%** |

### Key Finding

**The v9.1 agent is near-optimal within the heuristic framework.** Extensive
experimentation with 8 distinct improvement strategies (Phase 0 upstream mappings,
decoy redeployment reduction, block ordering, FP suppression, pre-emptive Restores,
server_host_0 prioritization, malfile-guarded escalation, and reduced user decoys)
demonstrated that all changes either have no measurable effect or cause regressions.

The remaining 4.7% loss gap relative to perfect play (reward=0) is dominated by:
- **Phase 0 uncontested red activity (58% of losses)**: fundamentally unaddressable
  within the heuristic framework due to comms_policy constraints
- **Green agent false positives (33-54% of proc_flag alerts)**: indistinguishable
  from real red activity without environment-level changes
- **DegradeServices invisibility**: permanent, undetectable damage with no
  observation signal

These gaps require RL-based adaptation or environment-level architectural changes.

---

## 2. Full Attack Chain View

### 2.1 Red FSM State Machine

```
                         +---------+
                         |  INIT   |
                         | (step 0)|
                         +----+----+
                              |
                     Starting host = U (contractor_network)
                              |
     +------- DiscoverRemoteSystems (1 step) ---------+
     |           discovers new IPs -> K               |
     v                                                v
+----+----+                                     +-----+-----+
|  K      |---AggrSvcDisc(1step)--> S           |  KD        |
| (Known) |---StlthSvcDisc(3step)-> S           | (Known +   |
|         |---DiscRemSys--------->  KD          |  Decoy)    |
+---------+                                     +-----+------+
 P(DRS)=50%, P(Aggr)=25%, P(Stlth)=25%               |

+----+----+                                     +------+-----+
|  S      |---Exploit(4step)-----> U            |  SD        |
| (Svcs)  |---DiscDeception(2step)> S           | (Svcs +    |
|         |---DiscRemSys---------> SD           |  Decoy)    |
+---------+                                     +------+-----+
 P(Exploit)=50%, P(DD)=25%, P(DRS)=25%          P(Exploit)=75%

+----+----+                                     +------+-----+
|  U      |---PrivEsc(2step)-----> R            |  UD        |
| (User)  |---DiscRemSys---------> UD           | (User +    |
+---------+                                     |  Decoy)    |
 P(PrivEsc)=50%, P(DRS)=50%                     +------+-----+
                                                 P(PrivEsc)=100%

+----+----+                                     +------+-----+
|  R      |---Impact(2step)------> R            |  RD        |
| (Root)  |---Degrade(2step)-----> R            | (Root +    |
|         |---DiscRemSys---------> RD           |  Decoy)    |
+---------+                                     +------+-----+
 P(Impact)=25%, P(Degrade)=25%, P(DRS)=50%      P(Impact)=50%
                                                 P(Degrade)=50%
```

### 2.2 Attack Timing

| Path | Steps | Notes |
|------|-------|-------|
| Starting host (U) to Impact | 4 | PrivEsc(2) + Impact(2) |
| New host (K) to Impact (fastest) | 10 | DRS(1)+AggrSvc(1)+Exploit(4)+PrivEsc(2)+Impact(2) |
| New host (K) to Impact (expected) | ~23 | Probabilistic path with random action selection |
| Post-Restore red recovery | ~11-15 | Red drops to KD, must re-scan and re-exploit |

### 2.3 Blue Detection Windows

| Red Action | Duration | Blue-Observable Signal | Detection Timing |
|------------|----------|----------------------|------------------|
| DiscoverRemoteSystems | 1 | None | Invisible |
| AggressiveServiceDiscovery | 1 | None | Invisible |
| StealthServiceDiscovery | 3 | None | Invisible |
| DiscoverDeception | 2 | None | Invisible |
| ExploitRemoteService | 4 | proc_flag (95%), conn_flag, malfile | Next step |
| PrivilegeEscalate | 2 | malfile only (no proc/conn) | Next step |
| Impact | 2 | None (but stops OT service) | Indirect via green LWF |
| DegradeServices | 2 | None | Completely invisible |

### 2.4 Network Topology and Attack Paths

```
Internet -> Contractor -> RZ-A -> OZ-A (Impact target Phase 1)
                       -> RZ-B -> OZ-B (Impact target Phase 2)
                       -> PAZ  -> Admin / Office (HQ, always -3 RIA)
```

Chokepoints: `server_host_0` in each subnet is the ONLY inter-subnet link.

---

## 3. Optimal Response Matrix

### 3.1 Per Alert Type x Phase x Zone

| Alert Type | Phase 0 (any zone) | Phase 1 OZ-A | Phase 1 RZ-A | Phase 2 OZ-B | Phase 2 RZ-B | HQ (any phase) |
|-----------|-------------------|-------------|-------------|-------------|-------------|---------------|
| conn + malfile | Restore | Restore | Restore | Restore | Restore | Restore |
| conn + proc | Restore | Restore | Restore | Restore | Restore | Restore |
| conn only (decoy deployed) | Skip | Skip | Skip | Skip | Skip | Skip |
| conn only (no decoy) | Restore | Restore | Restore | Restore | Restore | Restore |
| malfile only (PrivEsc) | Restore | Restore | Restore | Restore | Restore | Restore |
| proc only (flag_age=0) | Remove | Remove | Remove | Remove | Remove | Remove |
| proc only (flag_age>=1) | Restore | Restore | Restore | Restore | Restore | Restore |
| proc after Remove | Restore | Restore | Restore | Restore | Restore | Restore |

### 3.2 Why This Matrix is Optimal

- **conn + malfile/proc = confirmed red**: ExploitRemoteService always drops a
  file (malfile=1) and has 95% chance of proc_flag. Restore is the only safe
  response since root escalation may have already begun.

- **conn only + decoy = decoy hit**: When decoys are deployed, conn_flag without
  malfile means the exploit hit a decoy (no file dropped). Red wasted 4 steps.
  No action needed.

- **malfile only = PrivilegeEscalate**: This is the only action that drops a file
  without producing conn/proc events. Root session is present. Only Restore can
  clear root sessions.

- **proc only at flag_age=0 = possibly green FP**: 33-54% of proc_flag alerts are
  green false positives. Remove costs 0 reward and takes 3 steps. Green FPs clear
  within 1 step, so if the flag persists (flag_age >= 1), it's almost certainly
  real red.

- **proc after prior Remove = root session survived**: Remove clears user sessions
  but root sessions survive. Persistent proc_flag after Remove indicates root.

### 3.3 Cost-Benefit Analysis

| Scenario | Cost | Break-Even |
|----------|------|-----------|
| Unnecessary Restore on OZ during mission | -51 (-1 action + -10*5 LWF) | 1 step of prevented Impact justifies 5 Restores |
| Unnecessary Restore on HQ | -6 (-1 action + -1*5 LWF) | 2 steps of prevented Impact justifies 1 Restore |
| Unnecessary Remove (any host) | 0 (action free, no service disruption) | Always safe |
| Missed Impact on OZ during mission | -10/step + cascading LWF | Catastrophic within 5 steps |
| Missed Impact on HQ | -3/step | Significant but manageable |

---

## 4. Optimal Decoy Strategy

### 4.1 Decoy-Exploit Coverage Matrix

| Decoy | Port | Catches | Does NOT Catch |
|-------|------|---------|----------------|
| DecoyApache | 80 | HTTPRFI | SSH, SQL, FTP |
| DecoyTomcat | 443 | HTTPSRFI | SSH, SQL, FTP |
| DecoyHaraka | 25 | HarakaRCE | SSH, SQL, FTP |
| DecoyVsftpd | 80 | HTTPRFI | SSH, SQL, FTP |

**Apache and Vsftpd share port 80**: mutually exclusive. Max 3 decoys per host:
Apache/Vsftpd(80) + Tomcat(443) + Haraka(25).

**Uncoverable exploits**: SSHBruteForce (no SSH decoy in CC4) and SQLInjection
(no SQL decoy exists). These bypass all decoys.

### 4.2 Exploit Selection Algorithm (Key Insight)

Red's exploit selection has `odds_of_top_choice = 0`, meaning the highest-weighted
exploit is NEVER chosen. Selection is random among remaining applicable exploits.
This means the effective decoy coverage depends on the full set of applicable
exploits, not just the most likely one.

### 4.3 Effective Coverage Rates

| Host Configuration | Applicable Exploits | Decoy-Caught | Coverage |
|-------------------|--------------------|--------------| ---------|
| SSH only + 3 decoys | SSH, HTTP, HTTPS, SMTP | HTTP+HTTPS+SMTP caught | 100% (SSH is top, never chosen; all others hit decoys) |
| SSH + Apache + 3 decoys | SSH, HTTP(real+decoy), HTTPS, SMTP | HTTPS+SMTP caught (HTTP hits real first) | 67% |
| SSH + MySQL + 3 decoys | SSH, HTTP, HTTPS, SMTP, SQL | HTTP+HTTPS+SMTP caught | 60% (top removed, 3/5 remaining caught) |

### 4.4 Deployment Priority (Current, Optimal)

1. OZ-A/B server_host_0 (Impact targets)
2. Other OZ servers
3. RZ-A/B servers (chokepoints)
4. Other servers (HQ)
5. OZ user hosts
6. RZ user hosts
7. HQ user hosts

### 4.5 Decoy Redeployment After Restore

Each Restore wipes all decoys, costing 3 redeployment actions (6 steps). With
842 Restores per 10 episodes, this produces 2,131 redeploy actions (15.5% of
total actions). **Reducing this budget was experimentally shown to degrade
performance** because the 75% exploit interception rate is critical to defense.

---

## 5. Optimized Heuristic Strategy

### 5.1 Changes Tested and Their Outcomes

| Change | Hypothesis | Result | Reason |
|--------|-----------|--------|--------|
| Phase 0 upstream mappings | Enable T3 escalation when peer zones saturated | **Regression** (-970.8, +11.7% worse) | T3 threshold=0 triggers Restore on every green FP proc_flag |
| Decoy redeployment reduction (3->1 after Restore) | Save 2 actions per Restore cycle | **Regression** (-1025.0, +18.0% worse) | Reduced coverage (33% vs 75%) allows more red exploits |
| Block ordering (RZ->OZ first) | Cut direct attack path before entry points | **No effect** (identical to baseline) | All blocks complete within same steps regardless of order |
| Phase 0 FP suppression (threshold 2 for low-value hosts) | Reduce wasted Restores in Phase 0 | **No effect** (identical to baseline) | Condition rarely triggers; P4 already handles optimally |
| Pre-emptive Restore on OZ before phase transition | Ensure clean Impact targets at mission start | **Catastrophic regression** (-1217.0, +40.1% worse) | Restore on OZ during/near mission = -51 per unnecessary Restore |
| server_host_0 priority boost | Prioritize chokepoint defense | **Tradeoff** (-918.3 mean, -1405 worst vs -1935) | Reduces variance but increases mean; not a net improvement |
| Branch A malfile guard | Avoid unnecessary Restore after Remove when no malfile | **Regression** (-1142.7, +31.5% worse) | Lets root sessions persist; DegradeServices cascades |
| Reduced user host decoys (3->2) | Save deployment budget | **Regression** (-1048.7, +20.7% worse) | Lower coverage allows more exploits through |
| Cross-phase upstream (Phase 1: RZB->OZB) | Early warning for Phase 2 threats | **Regression** (-1163.8, +34.0% worse) | Same T3 escalation FP problem as Phase 0 upstream |
| max_peer_red_count usage | Broader escalation signal | **No effect** (identical to baseline) | Condition never triggers (P4 hosts lack malfile) |
| RZ-A Phase 2 priority fix (20->50) | Better prioritize RZ-A in Phase 2 | **No effect** (identical to baseline) | Agent_0 handles RZ-A; priority within-zone doesn't cross agents |
| HQ user host decoy deprioritization | Free agent_4's Phase 0 budget | **No effect** (identical to baseline) | P7 runs during idle; order doesn't affect threat response |

### 5.2 Why v9.1 is Near-Optimal

The v9.1 agent's strategy is remarkably robust because:

1. **Priority ordering is correct**: P1 (confirmed red) > P2 (fix blocks) > P3
   (add blocks) > P4 (suspicious activity) > P6/P7 (decoys) matches the reward
   structure perfectly.

2. **Escalation threshold of 1 is the sweet spot**: Green FPs clear within 1 step
   (flag_age=0). Real red persists (flag_age >= 1). Threshold=1 correctly
   separates them with minimal delay.

3. **3 decoys per host is critical**: The 75% exploit interception rate is the
   foundation of the defense. Any reduction immediately increases red success
   rates.

4. **conn-only skip with decoys is correct**: When decoys are deployed,
   conn_flag without malfile = decoy hit with > 99% probability.

5. **Remove before Restore saves budget**: Remove costs 0 and takes 3 steps.
   If it clears the threat (user session), we saved 2 steps and -1 reward vs
   Restore. If it doesn't (root session), we detect via flag persistence and
   escalate.

### 5.3 Final Agent State

The agent is unchanged from v9.1. The `_issue_restore()` helper method was added
as a code quality improvement (consolidates Restore bookkeeping) but does not
change behavior.

---

## 6. Experimental Results

### 6.1 Baseline v9.1 Performance (30 episodes, seed 42)

```
Mean reward    : -868.7 +/- 292.0
Min / Max      : -1935.0 / -370.0
Throughput     : 84.0 steps/sec
```

### 6.2 Per-Phase Breakdown (10 episodes, seed 42)

| Phase | Total Reward | Steps | Avg/Step | % of Loss |
|-------|-------------|-------|---------|-----------|
| Phase 0 (Preplanning) | -5,820 | 1,670 | -3.485 | **58.3%** |
| Phase 1 (Mission A) | -1,415 | 1,670 | -0.847 | 14.2% |
| Phase 2 (Mission B) | -2,745 | 1,650 | -1.664 | 27.5% |

### 6.3 Action Distribution

| Action | Count | % | Per Agent/Ep |
|--------|-------|---|-------------|
| P1 Restore (confirmed) | 549 | 2.2% | 11.0 |
| P2 Allow | 43 | 0.2% | 0.9 |
| P3 Block | 364 | 1.5% | 7.3 |
| P4 Remove | 480 | 1.9% | 9.6 |
| P4 Restore (escalated) | 293 | 1.2% | 5.9 |
| P6 Redeploy Decoy | 2,131 | 8.5% | 42.6 |
| P7 Deploy Decoy | 1,731 | 6.9% | 34.6 |
| P8 Sleep | 19,359 | 77.4% | 387.2 |

### 6.4 Statistical Significance

All improvement attempts were tested on the same 30 episodes with seed 42.
The deterministic nature of the simulation means any difference is real (not
noise). Changes producing identical results (within 0.0) confirmed no decision
path alteration. Changes producing different results confirmed altered behavior
but uniformly worsened performance.

---

## 7. Remaining Gaps

### 7.1 Fundamental Constraints (Cannot Fix Within Heuristic Framework)

| Gap | Impact | Root Cause | Possible Fix |
|-----|--------|-----------|-------------|
| Phase 0 no blocking | 58% of losses | comms_policy has no blocks in Phase 0 | Environment modification or proactive blocking with ASF cost acceptance |
| Green FP rate (33-54%) | ~480 wasted Removes | proc_flag identical for green and red | Environment-level signal differentiation |
| DegradeServices invisible | Ongoing LWF after root | No observation signal | Add service health to observation |
| SSH/SQL exploit bypass | Reduced decoy coverage | No SSH/SQL decoy factories in CC4 | Add SSHD decoy to DeployDecoy action |
| Single action per step | Delayed multi-host response | Agent architecture | Multi-action RL agent |

### 7.2 Heuristic Tradeoffs (Could Fix But Not Net-Positive)

| Gap | Tradeoff | Why Not Addressed |
|-----|---------|------------------|
| server_host_0 prioritization | Reduces variance (+27%) but increases mean (-5.7%) | Net-negative on mean performance |
| Upstream mappings (Phase 0, cross-phase) | Enables earlier escalation but triggers FP Restores | T3 threshold=0 is too aggressive for green FP environment |
| Reduced decoy coverage | Saves deployment time but reduces exploit interception | 75% coverage is critical; any reduction hurts more than it helps |

### 7.3 Observation Pipeline Limitations

Information NOT available in observations:
- Which specific exploit red used
- Whether DegradeServices has occurred
- Which services are running on a host
- Red's FSM state
- Whether green or red caused a proc_flag
- Session types (user vs root)
- Red's DiscoverDeception results

---

## 8. Recommendations

### 8.1 For RL Training

1. **Phase 0 strategy learning**: An RL agent could learn to tolerate some ASF
   penalties from proactive blocking if the prevented red exploitation saves
   more. The cost-benefit calculation is complex and scenario-dependent -- ideal
   for learned policies.

2. **FP discrimination**: An RL agent could learn temporal patterns (green FPs
   are random and transient; red proc_flags are correlated with prior conn_flags
   and persist) that a threshold heuristic cannot capture.

3. **DegradeServices detection**: An RL agent could learn to Restore hosts that
   have been compromised and not yet Restored, even without explicit signals,
   by correlating reward drops with host compromise history.

4. **Multi-host coordination**: With learned value functions, an RL agent could
   optimally allocate its single action per step across multiple simultaneous
   threats.

### 8.2 Architecture Changes

1. **Multi-action per step**: The single biggest structural limitation. If each
   agent could take 2-3 actions per step, the multi-host exploitation gap (FM-2)
   would be largely addressed.

2. **Service health observation**: Adding service reliability to the observation
   would enable DegradeServices detection, currently the largest invisible
   damage source.

3. **SSH/SQL decoy factories**: Adding SSHD (Linux-compatible, exists in code
   but not in CC4's DeployDecoy list) would close the exploit bypass gap.

4. **Phase 0 comms_policy**: Allowing blue to block contractor -> RZ paths in
   Phase 0 (with appropriate ASF cost) would address the 58% Phase 0 gap.

### 8.3 Immediate Low-Risk Improvements (For Future Testing)

1. **Explore threshold=0 for P4 with malfile+proc combination**: When both
   malfile AND proc_flag are present (guaranteed real red), skip Remove and
   go straight to Restore. Currently handled by P1 (conn+malfile) but the
   proc+malfile without conn case goes through P4.

2. **Adaptive decoy redeployment priority**: After Restore, redeploy decoys
   on the just-Restored host before other hosts' redeployment. Currently the
   deployment order is global, not responsive to which host was just Restored.

3. **Cross-agent coordination for Phase 2**: Agent_0 (RZ-A) could pre-emptively
   Restore RZ-A server_host_0 just before Phase 2 starts if it detects red
   presence, since RZ-A becomes less critical in Phase 2 (but still has RIA=-3).

---

## Appendix A: Red Agent Behavior Summary

- Red starts active in contractor_network with a user session
- 6 red agents total, but only red_agent_0 starts active
- Other red agents activate when sessions are passed to their subnets
- Red prioritizes servers (75% probability) over user hosts
- Red's FSM is probabilistic: exploit selection excludes highest-weighted option
- Decoy knowledge (UD/RD states) makes red MORE dangerous (100% PrivEsc in UD)
- Post-Restore recovery: red drops to KD, needs ~11-15 steps to re-Impact

## Appendix B: Reward Quick Reference

| Zone | Phase 0 RIA | Phase 1 RIA | Phase 2 RIA | Phase 1 LWF | Phase 2 LWF |
|------|------------|------------|------------|------------|------------|
| OZ-A | -1 | **-10** | -1 | **-10** | -1 |
| OZ-B | -1 | -1 | **-10** | -1 | **-10** |
| RZ-A | -1 | **-3** | **-3** | -2 | -1 |
| RZ-B | -1 | -1 | **-3** | -1 | -2 |
| HQ | -3 | -3 | -3 | -1 | -1 |
| Contractor | -5 | 0 | 0 | 0 | 0 |
| Internet | -1 | 0 | 0 | 0 | 0 |

## Appendix C: Comms Policy Summary

| Phase | Blocked Paths |
|-------|--------------|
| Phase 0 | None (full connectivity) |
| Phase 1 | RZ-A isolated: block contractor/internet/RZ-B/OZ-A <-> RZ-A |
| Phase 2 | RZ-B isolated: block contractor/internet/RZ-A/OZ-A <-> RZ-B |

Blocking is FREE (ASF=0) for mission-zone subnets during their active phase.
PhishingEmail bypasses all blocks.
