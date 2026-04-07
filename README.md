# CAGE Challenge 4 — Optimized Research Fork

This repository is an optimized fork of the official [CAGE Challenge 4 (CC4)](https://github.com/cage-challenge/cage-challenge-4)
environment for ML/AI research on autonomous cyber-defence. It adds:

- **10–20x faster training** via three waves of behavior-safe performance optimizations
- **10 simulation bug fixes** that improve correctness without changing intended mechanics
- **EnterpriseHeuristicAgent v9** — a rule-based blue agent achieving **96.7% improvement** over a
  do-nothing baseline, with fully functional inter-agent messaging

> **Base:** CAGE Challenge 4 (competition close, May 2024) · **Fixes applied:** 2026-04-07

---

## Published Results

Results from the original challenge were published at AAAI 2025. Please cite:

```bibtex
@inproceedings{kiely2025exploring,
  title={Exploring the Efficacy of Multi-Agent Reinforcement Learning for Autonomous Cyber Defence: A CAGE Challenge 4 Perspective},
  author={Kiely, Mitchell and Ahiskali, Metin and Borde, Etienne and Bowman, Benjamin and Bowman, David and van Bruggen, Dirk and Cowan, KC and Dasgupta, Prithviraj and Devendorf, Erich and Edwards, Ben and others},
  booktitle={Proceedings of the AAAI Conference on Artificial Intelligence},
  volume={39}, number={28}, pages={28907--28913}, year={2025}
}
```

```bibtex
@article{kiely2025cage,
  title={CAGE challenge 4: A scalable multi-agent reinforcement learning gym for autonomous cyber defence},
  author={Kiely, Mitchell and Ahiskali, Metin and Borde, Etienne and Bowman, Benjamin and Bowman, David and Van Bruggen, Dirk and Cowan, KC and Dasgupta, Prithviraj and Devendorf, Erich and Edwards, Ben and others},
  journal={AI Magazine}, volume={46}, number={3}, pages={e70021}, year={2025},
  publisher={Wiley Online Library}
}
```

---

## Quick Start

```bash
pip install -e .
pip install -r requirements.txt
```

**Run the heuristic agent benchmark (100 episodes):**

```bash
python -c "
import sys; sys.path.insert(0, 'CybORG/Evaluation/submission')
from submission import Submission
from CybORG.Evaluation.evaluation import run_evaluation
run_evaluation(Submission, log_path='Results/v9/', max_eps=100, seed=42)
"
```

**Run ML training (Ray RLlib):**

```bash
python CybORG/Evaluation/training_example/TrainingRay.py
```

---

## The Scenario

### Network Layout

CC4 simulates a two-site enterprise network under coordinated attack. Five blue agents
defend it; one red agent attacks; fifty green agents do legitimate work.

```
  INTERNET ──── CONTRACTOR (undefended)
      │                │
      │         ┌──────┴──────┐
      │         │  HQ NETWORK │
      │         │  (Admin/PAZ)│
      │         └──────┬──────┘
      │                │
   ┌──┴──────────────────────────┐
   │         DEPLOYED NETWORK    │
   │                             │
   │  ┌─────────────────────┐    │
   │  │  SITE A             │    │
   │  │  ┌───────────────┐  │    │
   │  │  │ Restricted ZA │◄─┼────┤  ← blue_agent_0 defends
   │  │  │  (RZA)        │  │    │
   │  │  └───────┬───────┘  │    │
   │  │          │ Mission A │    │
   │  │  ┌───────▼───────┐  │    │
   │  │  │Operational ZA │  │    │  ← blue_agent_1 defends
   │  │  │  (OZA) ★      │  │    │    ★ = Impact target
   │  │  └───────────────┘  │    │
   │  └─────────────────────┘    │
   │                             │
   │  ┌─────────────────────┐    │
   │  │  SITE B             │    │
   │  │  ┌───────────────┐  │    │
   │  │  │ Restricted ZB │◄─┼────┤  ← blue_agent_2 defends
   │  │  │  (RZB)        │  │    │
   │  │  └───────┬───────┘  │    │
   │  │          │ Mission B │    │
   │  │  ┌───────▼───────┐  │    │
   │  │  │Operational ZB │  │    │  ← blue_agent_3 defends
   │  │  │  (OZB) ★      │  │    │    ★ = Impact target
   │  │  └───────────────┘  │    │
   │  └─────────────────────┘    │
   └─────────────────────────────┘
      blue_agent_4 defends HQ/PAZ
```

Red enters via **PhishingEmail** (bypasses firewalls — out-of-band SMTP delivery),
then pivots laterally toward the OZA/OZB impact targets.

### Mission Phases

The episode runs 500 steps, divided into three phases:

```
Step 0            ~167           ~333           500
  │────── Phase 0 ──────│── Phase 1 ──│── Phase 2 ──│
        (Preplanning)    (Mission A)   (Mission B)

Phase 0:  All zones equal low priority
Phase 1:  RZA + OZA elevated — penalties ×3-10 in that zone
Phase 2:  RZB + OZB elevated — penalties ×3-10 in that zone
```

Blue agents read the current phase from `obs[0]` and must adjust their firewall
policy each time it transitions.

### Red Attack Chain

Red follows a Finite State Machine (FSM) from initial foothold to Impact:

```
PhishingEmail → Discover → ServiceScan → Exploit → PrivEscalate → Impact
     (entry)     (recon)    (recon)      (session)   (root sess)   (damage)

Host states: U (Unknown) → K (Known) → S (Scanned) → E (Exploited)
                                                   → KE (Killed/Evicted) → retry
                                                   → P (Privilege) → D (Done)
```

`ExploitRemoteService` always drops `cmd.exe`/`cmd.sh` (density=0.9, unsigned).
`PrivilegeEscalate` always drops `escalate.exe`/`escalate.sh` — but fires **no events**.
These file signatures are the key detection signals used by BlueFlatWrapperV2.

### Reward Structure

Blue agents accumulate **negative** rewards (penalties) each step:

| Event | Phase 0 | Phase 1 (Zone A active) | Phase 2 (Zone B active) |
|---|---|---|---|
| Green local-work failure (LWF) | -1 | OZA: -10, RZA: -2 | OZB: -10, RZB: -2 |
| Green access-service failure (ASF) | -1 | OZA: -10, RZA: -1 | OZB: -10, RZB: -1 |
| Red Impact on OT service (RIA) | -10 | OZA: -10, RZA: -3 | OZB: -10, RZB: -3 |

A perfect defense scores **0**. SleepAgent (no actions) scores around **-6,488** per episode.

---

## EnterpriseHeuristicAgent v9

### Benchmark Results

All results: 100 episodes × 500 steps, `FiniteStateRedAgent`, seed=42.
Reward = mean per-agent reward per step × 500 (official `evaluation.py` format).

| Agent | Mean Reward | Std Dev | vs SleepAgent |
|---|---|---|---|
| SleepAgent (no actions) | -6,488 | ±1,391 | baseline |
| EnterpriseHeuristicAgent v7 | -221 | ±102 | 96.6% better |
| **EnterpriseHeuristicAgent v9** | **-214** | **±74** | **96.7% better** |

v9 is both more effective and **more consistent** than v7 (std dev drops from 102 to 74).
The tighter spread comes from inter-agent messaging reducing worst-case episodes.

### Core Strategy: Two Pillars

#### Pillar 1 — Decoy Saturation

Every non-router host runs `MAX_DECOYS=3` decoy services alongside 1 real service:

```
  Host with 3 decoys deployed:
  ┌────────────────────────────┐
  │  [Real service  ]  port 80 │  ← 1 in 4 chance red hits this
  │  [Decoy service ]  port 22 │  ← wastes red's 5-step Exploit
  │  [Decoy service ]  port 443│  ← wastes red's 5-step Exploit
  │  [Decoy service ]  port 8080│ ← wastes red's 5-step Exploit
  └────────────────────────────┘

  Result: 75% of red's blind exploit attempts fail and waste 4+ steps each.
  Red must DiscoverDeception first (2 steps, 50% miss rate) to learn PID layout.
```

Decoys are deployed in priority order: OZB servers → OZA servers → other servers → user hosts.
After every `Restore` (host reimaged), decoys are immediately redeployed.

#### Pillar 2 — Malfile Detection (BlueFlatWrapperV2)

`ExploitRemoteService` and `PrivilegeEscalate` always leave a high-density unsigned file
on the target host. `BlueFlatWrapperV2` adds one flag per host to the observation:

```
  Standard obs: [phase | subnet blocks... | messages]
  V2 obs:       [phase | subnet blocks... | messages | malfile_0 | malfile_1 | ...]
                                                         ▲
                                          1.0 if host has density≥0.9 unsigned file
                                          0.0 if clean (0% false positive rate)
```

This enables three detections that standard process/connection flags miss:

```
  Signal: conn=1, malfile=0, proc=0, has_decoy=True  →  Decoy hit! Skip Restore.
  Signal: conn=1, malfile=1                           →  Real exploit. Restore.
  Signal: malfile=1, conn=0, proc=0                   →  PrivEscalate (root session). Restore.
```

### Action Priority Flowchart

Each step, the agent works through priorities from highest to lowest:

```
  ┌──────────────────────────────────────────────────────────────────┐
  │ Every step, for each host (highest-priority host first):          │
  │                                                                  │
  │  P1: conn_flag AND (malfile OR proc_flag)?  ──YES──► RESTORE     │
  │      │                                                           │
  │      NO                                                          │
  │      ▼                                                           │
  │  P1b: conn_flag only AND has_decoy AND NOT peer.DECOYS_BYPASSED? │
  │      │                              ──YES──► SKIP (decoy hit)    │
  │      NO (conn + no decoy) ──────────────────► RESTORE (safety)   │
  │      ▼                                                           │
  │  P1c: malfile only (no conn, no proc)?  ──YES──► RESTORE         │
  │      │                    (PrivEscalate / root session)          │
  │      ▼                                                           │
  │  P2: comms_policy says "should block" but not blocked? ──► BLOCK │
  │      ▼                                                           │
  │  P3: blocked but comms_policy says "allow"? ──────────► ALLOW   │
  │      ▼                                                           │
  │  P4: proc_flag? ──► REMOVE (escalate to RESTORE if peer alert)  │
  │      ▼                                                           │
  │  P5: Restore pending? ──────────────────────────────► RESTORE    │
  │      ▼                                                           │
  │  P6: Host needs decoy redeployment after Restore? ──► DECOY     │
  │      ▼                                                           │
  │  P7: Any host missing a decoy? ─────────────────────► DECOY     │
  │      ▼                                                           │
  │  P8: ──────────────────────────────────────────────► SLEEP       │
  └──────────────────────────────────────────────────────────────────┘
```

---

## Inter-Agent Messaging Protocol (v9)

### Overview

CC4 gives each blue agent an **8-bit outgoing message** per step. Each agent receives
the 8-bit messages from its 4 peers in the observation vector (`obs[-32:]`, 4 × 8 bits).

v9 uses all 8 bits with **zero redundancy** — every bit carries independent information.

### Bit Layout

```
  Bit:  7    6    5    4    3    2    1    0
        │    │    │    │    │    │    │    │
        R    D   [C1  C0] [P1  P0] [T1  T0]
        │    │    └──┬──┘  └──┬──┘  └──┬──┘
        │    │     OPEN     RED      THREAT
     RESTORING  DECOYS   PATHS    HOST     LEVEL
               BYPASSED (0-3)   COUNT
                                (0-3)
```

| Bits | Field | Values |
|---|---|---|
| 0–1 | `THREAT_LEVEL` | 0 = clean · 1 = decoy hit · 2 = user session · 3 = root session |
| 2–3 | `OPEN_PATHS` | Number of required comms paths not yet blocked (saturates at 3) |
| 4–5 | `RED_HOST_COUNT` | Hosts with confirmed red presence in my zone (saturates at 3) |
| 6 | `DECOYS_BYPASSED` | Red has PID knowledge of my decoys (hit then real exploit seen) |
| 7 | `RESTORING` | A Restore action is currently in progress in my zone |

### Upstream Topology

Messages flow from the zone red enters first toward the impact targets:

```
  Phase 1:                          Phase 2:
  ┌───────┐   message    ┌───────┐  ┌───────┐   message    ┌───────┐
  │ RZA   │ ──────────► │ OZA   │  │ RZB   │ ──────────► │ OZB   │
  │agent_0│  (upstream) │agent_1│  │agent_2│  (upstream) │agent_3│
  └───────┘             └───────┘  └───────┘             └───────┘
       red enters here ──►                  red enters here ──►
       then pivots to OZA                   then pivots to OZB
```

### How Messages Affect Decisions

**1. Suppress false-safe decoy skips (Priority 1b)**

Normally, `conn + no_malfile + has_decoy` = decoy hit → skip Restore (save 5 steps).
But if the upstream peer reports `DECOYS_BYPASSED=1`, red may have learned the real
service's PID — the conn-only event could be a real exploit. Skip is suppressed:

```
  Upstream peer says DECOYS_BYPASSED=1?
    YES → treat conn-only as suspicious → do NOT skip Restore
    NO  → safe to skip (likely decoy hit)
```

**2. Escalate Remove → Restore threshold (Priority 4)**

When a process flag appears, the default response is `Remove` first (cheaper, 3 steps),
then `Restore` only if the flag persists after 2 more steps. Peer messages can lower
this threshold:

```
  ┌─────────────────────────────────────────────────────────┐
  │  Peer condition                │  Threshold              │
  ├─────────────────────────────────────────────────────────┤
  │  upstream_red_count >= 3       │  T3: Restore immediately│
  │  any_root OR upstream_threat≥2 │  T2: Restore after 1   │
  │  threat≥1 AND open_paths>0     │                         │
  │    AND decoys_bypassed         │  T2: Restore after 1   │
  │  (default)                     │  T1: Restore after 2   │
  └─────────────────────────────────────────────────────────┘
```

The intuition: if your neighbor is under heavy attack (3 red hosts) or red has already
escalated to root, waiting 2 steps for confirmation is too slow — Restore immediately.

### End-to-End Message Flow

```
  Step N:                          Step N+1:
  ┌──────────────────┐             ┌──────────────────────────────────────┐
  │ agent.get_action │             │ Next obs contains peer messages:     │
  │  returns:        │             │  obs[-32:] = [msg_0|msg_1|msg_2|msg_3]│
  │  (action_idx,    │──► env ──►  │                                      │
  │   8-bit msg)     │   .step()   │ agent._read_peer_messages() decodes  │
  └──────────────────┘   passes   │ and adjusts P1b/P4 thresholds        │
                         messages  └──────────────────────────────────────┘
                         to env
```

Full specification: `/docs/v9_messaging_protocol.md`

---

## Performance Optimizations

Three waves of behavior-safe optimizations deliver 10–20x faster training throughput
versus the original competition codebase.

### Wave 1 & 2

| Area | Change | Gain |
|---|---|---|
| Ray training | `num_rollout_workers=4, num_envs_per_worker=2`; fix episode length 100→500 | **6–8x throughput** |
| Scenario pool | `pool_size=8` amortises scenario rebuild cost across resets | **2–4x reset speed** |
| Observation pipeline | Pre-allocate float32 buffer; cache comms matrix; eliminate list-growth + triple `np.concatenate` | **30–50% obs time** |
| Topology caching | Pre-compute `wireless_neighbors`; cache `get_connected_agents`; early-exit subnet reassignment | **150–400 ms/episode** |
| GC pressure | `list(...)` shallow copy in Monitor; in-place `clear()` on Restore | **Gen-0 GC ~halved** |
| Import cleanup | `networkx` import moved to call site; dead agent classes removed from `__init__.py` | **~30 ms/worker cold start** |

### Wave 3

| Area | Change | Gain |
|---|---|---|
| In-place obs buffers | Pre-allocated buffer filled in-place; eliminates ~10 heap allocs/step | **3–5% obs time** |
| PID index | `get_session_from_pid` uses dirty-flag dict O(agents×sessions)→O(1) | Inner-loop cost |
| Host clone | `Process.clone()` uses `object.__new__` — bypasses `__init__`, ~80 fewer dict allocs/Restore | GC on Restore-heavy eps |
| Scenario constants | NACL dict, policy lists elevated to class-level | **20–30% reset time** |

**Measured throughput** (Wave 1–2, 20 eps × 500 steps): **80.8 steps/sec**.
See `/docs/speed_report.md` for full Wave 3 numbers.

---

## Simulation Bug Fixes

Ten defects in the original codebase were identified and corrected (2026-04-07).
See `/docs/simulation_audit_report.md` for the full audit.

### Critical

**FiniteStateRedAgent — three bugs:**
1. Missing `KD` state row in `state_transitions_probability` → `KeyError` crash when all hosts reached KD state. Fixed by adding a KD row matching the `K` state distribution.
2. Line 315 called `self._choose_action(...)` (method does not exist) → `AttributeError`. Fixed by correcting the typo to `_choose_host_and_action`.
3. Line 300 returned `Sleep()` (single value) but caller unpacks as `(host, action)` → `TypeError`. Fixed: `return None, Sleep()`.

> **Important:** The scenario generator defaults red to `SleepAgent`. Always pass
> `red_agent_class=FiniteStateRedAgent` to `EnterpriseScenarioGenerator` for valid results.

**PhishingEmail — firewall bypass (documented as intentional design):**
`PhishingEmail` uses `check_routable()` (physical link) not `blocking_host()` (firewall).
`BlockTrafficZone` cannot stop phishing delivery — this models out-of-band SMTP traversal.
An ADR comment was added documenting this is intentional. Blue agents cannot prevent initial
red entry; they can only limit lateral movement after the foothold is established.

**PhishingEmail — infinite loop:** The candidate-selection loop never removed non-routable
candidates, hanging indefinitely when all candidates were unreachable. Fixed with `pop(idx)`.

### Medium

**Remove — file removal not implemented:** `Remove` killed processes but left malware
files (`cmd.exe`, `escalate.sh`) on disk. Fixed: now filters `host.files` to remove
entries with `density >= 0.9 and not signed` after process kills.

**RestoreFromBackup — dangling sessions:** Only scanned `target_host.sessions` for
cleanup; pivoted-through sessions in `state.sessions` were left pointing to a restored
host. Fixed: now scans all of `state.sessions` by hostname.

**Host.restore() — staged events destroyed:** Clearing `old_process_creation` and
`old_network_connections` in `restore()` wiped events that `Monitor` had already staged
for the current observation. Fixed: only `process_creation` and `network_connections`
(incoming queues) are cleared; `old_*` lists are preserved for `BlueFlatWrapper` to read.

### Low / Design

**DiscoverDeception — TP/FP not mutually exclusive:** Two independent RNG draws could
simultaneously satisfy both the true-positive and false-positive conditions for the same
process. Fixed as a single `if/else` per process type.

**impact_count not reset by Restore (documented as intentional):** A successful `Impact`
scores a penalty that stands even after the host is restored. This is intentional — real-world
OT damage cannot be undone by rebooting. Comments added to document this design decision.

---

## Observation Vector

### BlueFlatWrapper (standard)

```
  Index:  0    1 ──── 27+2n   ...   -32 ──── -1
          │    │              │      │
        phase  subnet block   ...  messages (4×8 bits)
               (one per subnet)
```

Each subnet block: `[subnet_onehot(9) | blocked_mask(9) | comms_policy(9) | proc_flags(n) | conn_flags(n)]`

`comms_policy[i] = 1` means subnet `i` **should be blocked** from this agent's subnet
(inverted convention: 1 = block, 0 = allow).

### BlueFlatWrapperV2 (extended, used by v9)

```
  [... standard BlueFlatWrapper obs ...] + [malfile_host_0 | malfile_host_1 | ...]
                                                    ▲
                                  1.0 = host has density≥0.9 unsigned file
                                  0.0 = clean  (0% false positive rate)
```

Use `BlueFlatWrapperV2` for all v9 (and v6+) evaluations:

```python
from CybORG.Agents.Wrappers import BlueFlatWrapperV2
wrapped = BlueFlatWrapperV2(env)
```

---

## Running Evaluations

### Official submission format

```bash
python -c "
import sys; sys.path.insert(0, 'CybORG/Evaluation/submission')
from submission import Submission
from CybORG.Evaluation.evaluation import run_evaluation
run_evaluation(Submission, log_path='Results/v9/', max_eps=100, seed=42)
"
```

Scores saved to `Results/v9/scores.txt` and `Results/v9/summary.json`.

### Using evaluate_heuristic.py (native message passing)

```bash
python scripts/evaluate_heuristic.py --episodes 100 --steps 500 --seed 42
```

### Adding a new agent

1. Subclass `BaseAgent` in `CybORG/Agents/SimpleAgents/`.
2. Implement `get_action(observation, action_space)` returning `(action_idx, message_bits)`.
3. Register it with `EnterpriseScenarioGenerator(blue_agent_class=YourAgent)`.
4. Run the evaluation script above.

---

## Original Challenge Links

- **Official repository:** https://github.com/cage-challenge/cage-challenge-4
- **Tutorials:** https://cage-challenge.github.io/cage-challenge-4/
- **AAAI 2025 paper:** https://ojs.aaai.org/index.php/AAAI/article/view/35158
- **AI Magazine:** https://onlinelibrary.wiley.com/doi/full/10.1002/aaai.70021
- **Original leaderboard:** https://codalab.lisn.upsaclay.fr/competitions/17672

---

## Documentation

| File | Contents |
|---|---|
| `/docs/v9_messaging_protocol.md` | Full inter-agent messaging v9 specification |
| `/docs/simulation_audit_report.md` | 10 bug fixes: analysis and rationale |
| `/docs/attack_chain_analysis.md` | Red agent FSM state tables and attack chains |
| `/docs/speed_report.md` | Benchmark timing results (Waves 1–3) |
