# EnterpriseHeuristicAgent v9.1 — Change Log

**Date:** 2026-04-07  
**Base version:** v9 (inter-agent messaging protocol, BlueFlatWrapperV2 integration)  
**Files changed:**
- `CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgent.py`
- `CybORG/Agents/Wrappers/BlueFlatWrapper.py`
- `scripts/evaluate_heuristic.py`

---

## Performance

| Version | Mean reward / agent | Std dev | vs SleepAgent | Episodes |
|---------|---------------------|---------|---------------|----------|
| v7 | -221 | ±102 | 96.6% | 100×500 |
| v9 | -214 | ±74 | 96.7% | 100×500 |
| **v9.1** | **-174** | **±58** | **97.3%** | 30×500, seed 42 |

v9.1 lowers mean reward by 19% and tightens std dev by 22% versus v9.

---

## Changes

### Fix 1 — Clear `_remove_at` on every Restore

**File:** `EnterpriseHeuristicAgent.py`  
**Locations:** 6 sites — Priority 1, Priority 1b, Priority 1c, Priority 4 (branch A),
Priority 4 (threshold branch), Priority 5

**What changed:**
```python
# Before (all Restore sites):
self._restore_at[hostname] = self._step
self._decoy_deployed.pop(hostname, None)

# After:
self._restore_at[hostname] = self._step
self._remove_at.pop(hostname, None)      # ← added
self._decoy_deployed.pop(hostname, None)
```

**Why:** When a host is Restored (full reimage), all state is wiped — sessions, files,
processes. The agent's `_remove_at` history is now stale: it recorded when a previous
Remove was attempted, but the Restore has made that history irrelevant. Without clearing
`_remove_at`, a subsequent exploit on the same host would immediately jump to Restore
(skipping Remove entirely) via Branch A of Priority 4 (`ra >= 0`). Clearing it allows
the cheaper Remove to be tried first on the fresh compromise, as intended.

**Effect:** Reduces unnecessary Restores on hosts that get re-exploited after a Restore,
lowering the -1 reward cost and preserving decoys longer.

---

### Fix 2 — Phase 0 host priorities

**File:** `EnterpriseHeuristicAgent.py`  
**Function:** `_host_priority(hostname, phase)`

**What changed:**
```python
# Before: Phase 0 fell through to generic fallback (20 or 50)

# After: explicit Phase 0 block added before the generic fallback
elif phase == 0:
    if "operational_zone_a" in hostname: return 40
    if "operational_zone_b" in hostname: return 40
    if "restricted_zone_a"  in hostname: return 30
    if "restricted_zone_b"  in hostname: return 30
```

**Why:** In Phase 0 (Preplanning, roughly steps 1–34), red is actively scanning and
potentially exploiting. The Preplanning phase still follows the RZ→OZ attack path — OZ
hosts are Impact targets and RZ hosts are the gateway. Prioritising alerts on these zones
from the very start focuses the agent's limited action budget on the hosts that matter
most before the mission phases begin.

**Effect:** Alert response ordering in Phase 0 now matches the actual threat model.
Previously a Phase-0 alert on an OZ server had the same priority as a generic user host.

---

### Fix 3 — Phase-2 OZA residual priority

**File:** `EnterpriseHeuristicAgent.py`  
**Function:** `_pair_priority(from_subnet, phase)`

**What changed:**
```python
# Before:
elif phase == 2:
    if from_subnet == "restricted_zone_b_subnet": return 100
# After:
elif phase == 2:
    if from_subnet == "restricted_zone_b_subnet": return 100
    if from_subnet == "restricted_zone_a_subnet": return 50   # ← added
```

**Why:** In Phase 2 (Mission B active), the mission focus shifts to Zone B. But red may
have established a foothold in Zone A during Phase 1 and can still pivot through it.
Before this fix, RZA comms paths fell to the generic priority of 10 in Phase 2, meaning
they were deprioritised behind everything else. A residual red session in RZA could
exploit an unblocked RZA→RZB path while the agent was busy with higher-priority tasks.

**Effect:** RZA paths retain meaningful blocking priority (50) in Phase 2, closing the
residual Phase-1 lateral movement window.

---

### Fix 4 — Default escalation threshold 2 → 1

**File:** `EnterpriseHeuristicAgent.py`  
**Location:** Priority 4 escalation block

**What changed:**
```python
# Before:
else:
    direct_restore_threshold = 2

# After:
else:
    direct_restore_threshold = 1
```

**Why (FSM analysis):** Red in state U (user session) selects PrivilegeEscalate with
50% probability per action step; in state UD, it is 100% certain. PrivEsc takes 2 steps.
With threshold=2, the agent would wait 2 steps before escalating from Remove to Restore
for a persistent proc_flag — giving red a near-certain window to reach root.

With threshold=1, a proc_flag that persists for 1 step (after Remove was already tried
and failed, or when processing was delayed by another higher-priority action) immediately
triggers Restore. Green agent false-positive proc_flags typically clear within 1 step,
so a flag_age ≥ 1 flag is almost certainly real red — the faster escalation is correct.

**Effect:** The T3/T2/default tiers now collapse to a 2-tier design:
- T3 (`upstream_red_count >= 3`): threshold=0 — Restore immediately
- All other cases: threshold=1 — Remove first, Restore if flag persists 1+ step

---

### Fix 5 — Priority 7 `_busy()` guard

**File:** `EnterpriseHeuristicAgent.py`  
**Location:** Priority 7 (initial decoy deployment loop)

**What changed:**
```python
# Before:
for hostname in self._deploy_hosts:
    if self._decoy_deployed.get(hostname, 0) < MAX_DECOYS and hostname in self._decoy:
        ...

# After:
for hostname in self._deploy_hosts:
    if self._busy(hostname):        # ← added
        continue
    if self._decoy_deployed.get(hostname, 0) < MAX_DECOYS and hostname in self._decoy:
        ...
```

**Why:** Priority 7 deploys initial decoys in episode order. It previously had no check
for whether a Restore or Remove was already in progress on a host. If a host was
mid-Restore, attempting DeployDecoy during the Restore window wastes the action: the
Restore will reimage the host at the end of its duration, wiping any decoy just deployed.
Additionally, `_decoy_deployed[hostname]` would be incremented prematurely, causing the
count to be inconsistent after the Restore clears it.

**Effect:** Decoy deployments now skip hosts that are mid-Restore or mid-Remove, avoiding
wasted actions and keeping `_decoy_deployed` counts accurate.

---

### Fix 6 — Escalation comment corrected

**File:** `EnterpriseHeuristicAgent.py`  
**Location:** Priority 4 comment block above the escalation logic

**What changed:** The comment above the threshold block referred to a 3-tier system with
"default (threshold 2)" — which was outdated after Fix 4 changed the default to 1. The
comment now accurately describes the actual 2-tier behaviour and explains the reasoning.

```python
# Before (comment):
# 3-tier escalation based on v9 peer message fields:
#   T3 (threshold 0): ...
#   T2 (threshold 1): ...
#   default (threshold 2): normal Remove-first flow

# After (comment):
# 2-tier escalation based on v9 peer message fields:
#   T3 (threshold 0): upstream zone has 3+ compromised hosts → Restore immediately
#   default (threshold 1): Restore if proc_flag persists 1+ step (Remove issued first).
#     Peer T2 conditions ... also resolve to threshold=1.
#     Green FPs typically clear within 1 step, so flag_age >= 1 = almost certainly real red.
```

---

## Swarm Review Findings — No Action Required

The 4-agent expert swarm (coord-analyst, trivial-fixer, fsm-analyst, eval-runner) also
investigated several other potential improvements and confirmed they are either already
handled correctly or not worth implementing:

| Item | Finding | Verdict |
|------|---------|---------|
| Multi-agent decoy coordination (#5) | Blue agents have strictly disjoint subnets by design (`blue_agent_allowed_subnets` in `EnterpriseScenarioGenerator`). No redundant deployments possible. | No change needed |
| Root tracking after Remove (#7) | Priority 1c correctly handles malfile-only reappearance regardless of Remove history. `root_indicators` set also correct. | No change needed |
| `reset()` correctness | All 7 state dicts/sets are correctly cleared. `_decoy_hit_hosts.clear()` was added in v9 and remains. | No change needed |
| `_busy()` timing | Off-by-one verified: `step <= at + DUR - 1` is correct for both Remove (DUR=3) and Restore (DUR=5). | No change needed |
| Green FP suppression (proc_only threshold+1) | Tested: adding +1 to threshold for proc_flag-only cases reverts Fix 4 for most Priority 4 cases. Empirically worse. | Tested and reverted |
| DegradeServices detection | No observation signal available. Only mitigation is faster Restore, which v9.1 already achieves. | No change needed |
| `upstream_restoring` usage | Field decoded and available in `peer_state` but no decision uses it. Impact is marginal (~1-3 reward/episode). | Deferred |
| Sleep vs Monitor | Monitor provides no additional observation in CC4's wrapper pipeline. Semantically cleaner but functionally identical. | Not implemented |

---

## How to Evaluate

```bash
# Quick 30-episode benchmark
python scripts/evaluate_heuristic.py --episodes 30 --steps 500 --seed 42

# Standard 100-episode benchmark (matches README protocol)
python scripts/evaluate_heuristic.py --episodes 100 --steps 500 --seed 42
```

Expected output (seed 42, 30 episodes):
```
Mean reward    :     -868.7 ± 292.0  (sum across 5 agents)
                      -173.7 ± 58.4  (per-agent equivalent)
vs dummy base  :   +17517.3  (+95.3%)
```

---

## Related Documents

| Document | Contents |
|----------|----------|
| `docs/v9_messaging_protocol.md` | Full v9 inter-agent messaging protocol specification with illustrations |
| `docs/heuristic_agent_improvement_analysis.md` | 10-point improvement analysis from initial swarm review |
| `docs/heuristic_agent_v7_strategy.md` | v7 decoy saturation strategy (still applies in v9.1) |
