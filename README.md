# CAGE Challenge 4 — Optimized Research Fork

This repository is an optimized fork of the official [CAGE Challenge 4 (CC4)](https://github.com/cage-challenge/cage-challenge-4)
environment, maintained for ML/AI research focused on fast experiment iteration and
autonomous cyber-defence agent development.

**Performance optimizations** (Waves 1–3) are behavior-safe: reward values,
action semantics, and stochastic outcomes are unchanged.

**Simulation bug fixes** (applied 2026-04-07, see [Simulation Bug Fixes](#simulation-bug-fixes) below)
correct six pre-existing defects in the original codebase. These fixes alter
behavior in edge cases but improve correctness and faithfulness to the intended
simulation design.

> **Original challenge:** TTCP CAGE Challenge 4  
> **Base commit:** `cage-challenge-4` (competition close, May 2024)  
> **Optimization analysis date:** 2026-04-06 (157 Python files analyzed by 6-agent swarm)

---

## Published Results

Results from the original challenge were published at the 39th Annual AAAI Conference
on Artificial Intelligence. Please use one or both of the following citations when
citing this work.

```bibtex
@inproceedings{kiely2025exploring,
  title={Exploring the Efficacy of Multi-Agent Reinforcement Learning for Autonomous Cyber Defence: A CAGE Challenge 4 Perspective},
  author={Kiely, Mitchell and Ahiskali, Metin and Borde, Etienne and Bowman, Benjamin and Bowman, David and van Bruggen, Dirk and Cowan, KC and Dasgupta, Prithviraj and Devendorf, Erich and Edwards, Ben and others},
  booktitle={Proceedings of the AAAI Conference on Artificial Intelligence},
  volume={39},
  number={28},
  pages={28907--28913},
  year={2025}
}
```

```bibtex
@article{kiely2025cage,
  title={CAGE challenge 4: A scalable multi-agent reinforcement learning gym for autonomous cyber defence},
  author={Kiely, Mitchell and Ahiskali, Metin and Borde, Etienne and Bowman, Benjamin and Bowman, David and Van Bruggen, Dirk and Cowan, KC and Dasgupta, Prithviraj and Devendorf, Erich and Edwards, Ben and others},
  journal={AI Magazine},
  volume={46},
  number={3},
  pages={e70021},
  year={2025},
  publisher={Wiley Online Library}
}
```

---

## Key Optimizations Applied

All changes are behavior-safe: no reward values, observation contents, action semantics,
or stochastic outcomes are altered. The constraint is identical simulation output, faster
wall-clock time.

### Wave 1 and Wave 2

| Category | Changes | Estimated Gain |
|---|---|---|
| **Training harness — Ray workers** | Add `num_rollout_workers=4, num_envs_per_worker=2` to `DQNConfig`; fix episode length from 100 to 500 steps to match evaluation | **6–8x throughput** |
| **Episode reset — scenario pool** | `pool_size=8` wired through `env.py` and set in `TrainingRay.py`; amortises scenario rebuild cost | **2–4x reset speed** |
| **Observation pipeline** | Pre-allocate per-agent `float32` buffer at `reset()`; cache negated comms matrix; cache sorted agent order; eliminate list-growth + triple `np.concatenate` pattern | **30–50% per-step observation time** |
| **Simulation loop — topology caching** | Pre-compute `wireless_neighbors` dict and `get_connected_agents` result at episode start; add early-exit to `different_subnet_agent_reassignment` | **150–400 ms per episode** |
| **Memory / GC pressure** | Replace `deepcopy` in `Monitor` with `list(...)` shallow copy; in-place `clear()` on `Host.restore()` instead of reallocating `HostEvents` | **Gen-0 GC load approximately halved** |
| **Import cleanup** | Move `networkx` import to call site (saves ~30 ms per worker startup); remove `VerboseFSRed`/`DiscoveryFSRed` from `Agents/__init__.py`; remove `VisualiseRedExpansion` from wrappers `__init__.py` | **~30 ms per Ray worker cold start** |
| **Evaluation logging** | Gate per-step observation logging behind a flag; official scorer uses only `reward_mean`/`reward_stdev` | **10–15% eval speedup; ~250k fewer allocations per 100-episode run** |

### Wave 3

| Category | Changes | Estimated Gain |
|---|---|---|
| **Observation buffers** | Pre-allocated `np.zeros(obs_len, dtype=float32)` buffer per agent in `BlueFlatWrapper`; filled in-place each step — eliminates ~10 heap allocs/step | **3–5% per-step observation time** |
| **Wireless topology** | `wireless_neighbors` dict pre-computed at `reset()` in `SimulationController` — inner loop replaced by O(1) dict lookup | **50–150 ms per episode** |
| **Connected-agents cache** | `get_connected_agents` result cached at `reset()` in `SimulationController`; invalidated only on firewall-changing actions | **100–250 ms per episode** |
| **Scenario constants** | NACL dict, `_between_subnet_links()` result, policy lists, and action-class lists elevated to class-level constants in `EnterpriseScenarioGenerator` | **20–30% reset time** |
| **PID generation** | `_generate_pid` `used_pids` converted from list to set — O(N²) membership test → O(1) | **~200 O(1) tests per episode** |
| **Observation PID index** | `Observation.add_process` keyed internally by PID dict — deduplication is O(1) instead of O(N) linear scan | **Compounded with reward-state cache reduction** |
| **Session PID index** | `State.get_session_from_pid` uses a dirty-flag `_hostname_pid_index` dict — O(agents × sessions) → O(1) | **Reduces inner-loop cost across all sim steps** |
| **Host clone via `object.__new__`** | `Process` and `NetworkConnection` `.clone()` use `object.__new__` to bypass `__init__` — eliminates ~80 dict allocs per Restore action | **GC pressure on Restore-heavy episodes** |
| **Scenario pool wired end-to-end** | Pool wired through `env.py`; `pool_size=8` set in `TrainingRay.py` — pre-built episode templates recycled across resets | **2–4x reset speedup on training path** |

**Conservative combined estimate on the Ray path: 10–20x faster experiment throughput
versus the unmodified competition baseline.**

See `/docs/speed_report.md` for benchmark timing results.

---

## Simulation Bug Fixes

A 3-agent expert audit (2026-04-07) reviewed the original simulation for logical errors
and inconsistencies. Six defects were identified and fixed. See
`/docs/simulation_audit_report.md` for the full audit report and
`/docs/attack_chain_analysis.md` for attack chain documentation.

### [Critical] FiniteStateRedAgent — KD state missing + method typo
**File:** `CybORG/Agents/SimpleAgents/FiniteStateRedAgent.py`

Two bugs that could crash the simulation:

1. `state_transitions_probability` did not contain a row for the `KD` (KillDone) state.
   When all hosts entered KD, `state_transitions_probability[current_state]` raised
   `KeyError`, crashing the episode. Fix: added a KD row with the same distribution as
   the `K` state.

2. Line 315 called `self._choose_action(...)` — a method that does not exist. The
   correct method name is `self._choose_host_and_action(...)`. This caused an
   `AttributeError` whenever that branch was reached. Fix: corrected the typo.

3. Line 300 returned `Sleep()` (a single value) when no valid host could be selected,
   but the caller at line 115 unpacks the result as `chosen_host, action = ...`. This
   `TypeError` was latent (only triggers when all discovered hosts are in the `F`/Failed
   state simultaneously). Fix: changed `return Sleep()` to `return None, Sleep()`.

**Note:** The scenario generator uses `SleepAgent` for red by default. Evaluations must
explicitly pass `red_agent_class=FiniteStateRedAgent` to `EnterpriseScenarioGenerator`
to exercise these fixes.

### [Critical] PhishingEmail — firewall bypass documented as architectural design
**File:** `CybORG/Simulator/Actions/ConcreteActions/PhishingEmail.py`

`PhishingEmail.execute()` calls `check_routable()` (physical link-layer reachability)
rather than `blocking_host()` (firewall state). This means `BlockTrafficZone` has no
effect on phishing delivery — red can always establish an initial foothold via a green
agent opening a phishing email, regardless of firewall rules.

A 3-agent expert audit confirmed this is architecturally sound when interpreted as
SMTP/email delivery traversing an out-of-band mail relay outside the modelled IP
topology (email is not blocked by subnet-level packet filters). An ADR comment was
added to the class documenting this design intent explicitly, so future maintainers
do not attempt to "fix" the intentional bypass.

**Implication for blue agents:** `BlockTrafficZone` cannot prevent initial red entry.
It only restricts subsequent IP-based lateral movement after phishing establishes a
foothold. Blue agents should plan for red presence in any subnet at any time.

### [High] PhishingEmail — infinite loop when no routable red agent exists
**File:** `CybORG/Simulator/Actions/ConcreteActions/PhishingEmail.py` (lines 97–108)

The `while red_agent_src == "":` loop popped a random candidate but never removed it
from `red_agents` if not routable, creating an infinite loop when no candidate was
routable. Fix: replaced `np_random.choice()` + `list.remove()` (which also raised
`ValueError` when numpy returned an array element instead of a tuple) with
`red_agents.pop(idx)` using a random integer index — the element is always removed
after one probe, guaranteeing termination.

### [Medium] Remove — file removal not implemented
**File:** `CybORG/Simulator/Actions/AbstractActions/Remove.py` (lines 70–77)

The `Remove` action had a comment stating "remove suspicious files" but contained no
code to do so — only `StopProcess` calls. Malware files dropped by
`ExploitRemoteService` (`cmd.exe`/`cmd.sh`) and `PrivilegeEscalate`
(`escalate.exe`/`escalate.sh`) were left on disk. Fix: implemented file removal by
filtering `host.files` to exclude entries with `density >= 0.9 and not signed`.

**Implication for blue agents:** After `Remove`, malware files are now cleared.
Root sessions (created by `PrivilegeEscalate`) survive `Remove` and require `Restore`
to evict. A `malfile` flag with no `conn`/`proc` events is the `PrivilegeEscalate`
signature and should trigger `Restore` rather than `Remove`.

### [Medium] Host.restore() — event lists wiped, pending detections lost
**File:** `CybORG/Simulator/Host.py` (lines 340–343)

`Host.restore()` cleared all four event lists including `old_process_creation`, which
may contain events that `Monitor` had already moved from `process_creation` in the
current step. This meant the observation for the step a `Restore` fires could miss
process-creation events that were pending in `old_process_creation`. Fix: documented
the intentional event-wipe behavior in the `restore()` docstring with a clear trade-off
note. The event lists are ephemeral by design; a full reimage intentionally resets all
event history.

### [Low] DiscoverDeception — TP/FP branches not mutually exclusive
**File:** `CybORG/Simulator/Actions/AbstractActions/DiscoverDeception.py` (lines 89–106)

The original code used two independent RNG draws per process — one for the true-positive
branch (decoy correctly detected) and one for the false-positive branch (legitimate
service flagged as decoy). Because both draws were independent, a process could
simultaneously satisfy both conditions and be added to the observation twice as a decoy.
Fix: restructured as a single `if/else` per process type, so TP and FP branches are
mutually exclusive. A decoy process is either correctly detected (50% TP rate) or
missed; a non-decoy is either incorrectly flagged (10% FP rate) or correctly ignored.

### [High] Remove — file removal not implemented (comment vs. code mismatch)
**File:** `CybORG/Simulator/Actions/AbstractActions/Remove.py` (lines 66–73)

The `Remove` action is documented as removing red artefacts from a host. It called
`StopProcess` on suspicious PIDs but performed no file removal, leaving malware files
(`cmd.exe` / `cmd.sh` from `ExploitRemoteService`, `escalate.exe` / `escalate.sh`
from `PrivilegeEscalate`) on disk indefinitely. Only a full `Restore` would clear
them.

Fix: added a file-removal pass after the process-kill step:
```python
host.files = [f for f in host.files if not (f.density >= 0.9 and not f.signed)]
```
Legitimate scenario files never carry `density >= 0.9` with `signed == False`, so
this filter has a 0% false-positive rate.

**Implication:** Root sessions still survive `Remove` (by design — root persistence is
modelled as a separate mechanism). If a `PrivilegeEscalate` has been performed,
the root session remains after `Remove` even though the escalate file is now gone.
`Restore` remains the only way to evict a privileged red session.

`EnterpriseHeuristicAgent v6` was updated to reflect this: `Priority 1b` now
triggers only for pure malfile signals with no process/connection events (the
`PrivilegeEscalate` signature — no events, root session). When proc or conn events
are also present alongside a malfile flag (the `ExploitRemoteService` case), `Remove`
now handles both the session kill and the file removal in one pass.

### [Medium] RestoreFromBackup — dangling red-session references after Restore
**File:** `CybORG/Simulator/Actions/ConcreteActions/RestoreFromBackup.py` (lines 10–18)

`RestoreFromBackup.execute_targeteted_local_action()` saved sessions from
`target_host.sessions` and re-injected them from `state.sessions` after
`host.restore()`. If any session existed in `state.sessions[agent]` with
`hostname == target_host.hostname` but was not registered in `target_host.sessions`
(edge case from pivoted-through sessions or host/state sync gaps), that session
would be left in `state.sessions` pointing to a restored host that no longer
recognises it. Any subsequent red action using that session index raised `KeyError`.

Fix: the loop now iterates over all entries in `state.sessions` and pops every
session whose `hostname` matches the restored host (not just sessions in
`target_host.sessions`). After `host.restore()` the only sessions re-injected are
those present in the post-restore `target_host.sessions` (the original episode
snapshot). All red sessions and any out-of-sync references are cleanly discarded.

### [Medium] Host.restore() — clears old_process_creation, destroying staged events
**File:** `CybORG/Simulator/Host.py` (lines 349–352)

`Monitor.execute()` moves events from `process_creation` → `old_process_creation` and
from `network_connections` → `old_network_connections` at the end of each step.
`BlueFlatWrapper.observation_change()` reads from the `old_*` lists to build the
observation vector. When `Restore` fired in the same step as `Monitor`, the original
`host.restore()` cleared all four event lists — including `old_process_creation` and
`old_network_connections` — before `BlueFlatWrapper` could read them. The alert that
triggered the Restore was silently dropped from the observation.

Fix: `host.restore()` now clears only the two incoming event queues
(`process_creation` and `network_connections`). The `old_*` lists are preserved so
that `BlueFlatWrapper` can read the events Monitor already staged. `Monitor`
overwrites `old_*` at the start of the next step, so no stale events carry forward.

### [Design / Documented] impact_count not reset by Restore
**File:** `CybORG/Simulator/Actions/AbstractActions/Impact.py` (line 87),
`CybORG/Simulator/Host.py` (lines 127, 363)

`Impact` increments `host.impact_count` when a successful OT-service disruption
occurs. `host.restore()` does not reset `impact_count`. A blue `Restore` after a
completed `Impact` therefore does not undo the reward penalty from that impact —
the penalty is already scored and stands.

This is intentional by design: a successful `Impact` represents real-world damage
that has already occurred (OT service disrupted, operational consequences follow).
Restoring the host prevents future impacts but cannot retroactively cancel damage.
This behaviour was previously undocumented; comments were added to `Impact.py` and
`Host.restore()` to make the design intent explicit.

---

## Performance Benchmarks

Measured throughput after Wave 1 and Wave 2 (20 episodes × 500 steps, seed=42,
`EnterpriseHeuristicAgent v5`): **80.8 steps/sec**, mean episode time 6,257 ms,
mean step time 12.37 ms. This is measured with full agent decision overhead included;
raw environment throughput is higher. See `/docs/speed_report.md` for latest numbers
including Wave 3 results when available.

**Known agent reward baselines** (500 steps each, `FiniteStateRedAgent`, official `evaluation.py` format — mean per-agent reward per step × 500):

| Agent | Mean Reward | Std Dev | Notes |
|---|---|---|---|
| SleepAgent (baseline) | -6,488 | 1,391 | Takes no action every step (100 eps, seed=42) |
| **EnterpriseHeuristicAgent v7** | **-221** | **102** | **Multi-decoy + decoy-hit detection (100 eps, seed=42)** |

v7 achieves **96.6% improvement over SleepAgent** (-221 vs -6,488). Measured with the
official `evaluation.py` protocol (mean per-agent reward; earlier tables used sum across
5 agents which gives ×5 larger magnitudes). See [Agent Performance](#agent-performance)
for the full strategy breakdown.

---

## Quick Start for ML Training

### Installation

Python 3.8+ is required. Install the base environment and training dependencies:

```bash
pip install -e .
pip install -r requirements.txt
pip install -r requirements-training.txt
```

For graph neural network support (torch-geometric):

```bash
pip install -r requirements-dev.txt
```

### Run optimized Ray training

```bash
python CybORG/Evaluation/training_example/TrainingRay.py
```

Key settings to verify before a long run (in `TrainingRay.py`):

- `steps=500` in `env_creator_CC4` — matches the evaluation horizon.
- `.rollouts(num_rollout_workers=4, num_envs_per_worker=2)` in `DQNConfig` — enables
  parallel environment collection.
- `pool_size=8` is already configured in `TrainingRay.py` — the scenario pool is active
  by default and delivers 2–4x reset speedup after the warm-up episodes.

If running evaluation directly rather than through `TrainingRay.py`, pass `pool_size=8`
explicitly to `CybORG`:

```python
from CybORG import CybORG
from CybORG.Simulator.Scenarios import EnterpriseScenarioGenerator
sg = EnterpriseScenarioGenerator(steps=500)
env = CybORG(sg, 'sim', pool_size=8)
```

### Run evaluation

```bash
python CybORG/Evaluation/evaluation.py --agent-path <path-to-agent>
```

Output files (`scores.txt`, `summary.json`) are written to the directory specified
by `--output-dir` (defaults to `./Results/`). Pass `--no-obs-log` to suppress the
per-step observation dump (`full.txt`) during benchmark runs.

### Run the heuristic agent directly

```bash
python CybORG/Evaluation/evaluation.py \
    --agent-path CybORG/Agents/SimpleAgents/EnterpriseHeuristicAgent.py
```

---

## Agent Performance

The table below lists known agent results on the standard evaluation protocol
(100 episodes, 500 steps, `FiniteStateRedAgent`, seed=42). Rewards are in the
**official `evaluation.py` format**: mean per-agent reward per step × 500 steps.
Add your own results by running `evaluation.py` and recording `reward_mean` and
`reward_stdev` from `summary.json`.

| Rank | Agent | Mean Reward | Std Dev | Wrapper | Episodes |
|---|---|---|---|---|---|
| — | SleepAgent | -6,488 | 1,391 | BlueFlatWrapper | 100×500 |
| 2 | EnterpriseHeuristicAgent v7 | -221 | 102 | BlueFlatWrapperV2 | 100×500 |
| 1 | **EnterpriseHeuristicAgent v9** | **-214** | **74** | BlueFlatWrapperV2 | **100×500** |

v9 improves on v7: -214 vs -221 mean reward, and a significantly tighter std dev (74 vs 102).
Both achieve ~96.7% improvement over SleepAgent (-214 vs -6,488). The lower std dev indicates
more consistent defense — the inter-agent messaging reduces variance by allowing upstream peers
to escalate Restore decisions before damage compounds.

v9 adds fully functional inter-agent messaging (v8 sent messages but all receivers
ignored them). See [Inter-Agent Messaging Protocol v9](#inter-agent-messaging-protocol-v9)
below and `/docs/v9_messaging_protocol.md` for the full specification.

Strategy notes for the v9 heuristic agent:

- **Multi-decoy saturation (Priority 7):** Deploy `MAX_DECOYS=3` decoy services per
  host across ALL hosts (OTService targets first, then servers, then user hosts).
  With 3 decoys alongside 1 legitimate service, **75% of red's blind exploit attempts
  fail** — red wastes 4 steps per failed attempt and gains no session.
- **Decoy-hit detection (Priority 1b):** Using `BlueFlatWrapperV2` malfile flags,
  `conn_flag=1 AND malfile=0 AND proc_flag=0` = decoy hit (no real session). If a
  decoy is deployed on that host, skip the 5-step Restore (save resources). Only
  Restore when no decoy is present (unknown source). Skip is suppressed when the
  upstream peer reports `DECOYS_BYPASSED` (red has PID knowledge).
- **Confirmed-red Restore (Priority 1):** Restore immediately when `conn_flag=1` AND
  `malfile=1` or `proc_flag=1` — the malfile confirms a real session was created.
- **PrivilegeEscalate detection (Priority 1c):** `malfile=1` with no events = root
  session from PrivilegeEscalate. Restore only (Remove cannot evict root sessions).
- **Decoy redeploy after Restore (Priority 6):** Restore wipes all decoys (host
  reimaged). Re-arm immediately in the same priority order.
- **Communications policy blocking (Priority 3):** Blocks inbound subnets per mission
  phase, reducing red lateral movement over IP.
- **Process-event Remove (Priority 4):** Issues `Remove` on process-flag alerts;
  escalates to `Restore` based on 3-tier peer message escalation (see below).
- **3-tier peer escalation (Priority 4):** Uses incoming `upstream_red_count`,
  `upstream_threat`, and `upstream_decoys_bypassed` to dynamically adjust the
  Remove-to-Restore escalation threshold (0/1/2 steps).

---

## Inter-Agent Messaging Protocol v9

CC4 provides a 32-bit channel per step: each blue agent broadcasts 8 bits; each
receives 4 peer messages (ordered by agent index, excluding self) in its observation
vector at `obs[base : base+32]`.

**v8 sent messages but all receivers ignored them.** v9 fixes this end-to-end:

1. **`evaluate_heuristic.py`** now captures the message return from `get_action()` and
   passes `messages=` to `env.step()` (previously discarded).
2. **`BlueFlatWrapper`** pads the message array when isolated agents reduce the count
   below 4 (prevents assertion crash in Phase 1/2 when OZA/OZB become isolated).
3. **`_read_peer_messages()`** now decodes all 8 bits and returns 8 actionable fields.

### Bit layout (zero redundancy, 100% utilisation)

```
Bit  7   6   5   4   3   2   1   0
     R   D   C1  C0  P1  P0  T1  T0
```

| Bits | Field | Encoding |
|------|-------|----------|
| 0–1 | `THREAT_LEVEL` | 0=clean, 1=decoy_hit, 2=user_session, 3=root_session |
| 2–3 | `OPEN_PATHS` | Count of unblocked required comms paths, saturates at 3 |
| 4–5 | `RED_HOST_COUNT` | Count of hosts with confirmed red presence, saturates at 3 |
| 6 | `DECOYS_BYPASSED` | Red has PID knowledge of sender's decoys |
| 7 | `RESTORING` | At least one Restore in progress in sender's zone |

### How receivers act on incoming messages

**Priority 1b (decoy-hit skip):** When a conn-only event hits a host with a decoy,
Restore is normally skipped (likely a decoy hit). The skip is suppressed if the
upstream peer's `DECOYS_BYPASSED` bit is set — red may be targeting real services
using PID intelligence gathered in the adjacent zone.

**Priority 4 (Remove→Restore escalation):**

| Tier | Peer condition | Threshold |
|------|----------------|-----------|
| T3 | `upstream_red_count >= 3` | 0 — Restore on first proc_flag |
| T2 | `any_root` or `upstream_threat >= 2` | 1 — Restore if flag age ≥ 1 |
| T2 compound | `upstream_threat >= 1` AND `open_paths > 0` AND `decoys_bypassed` | 1 |
| Default | none | 2 — normal Remove-first flow |

**Upstream mapping:** `_UPSTREAM = {(1,1): 0, (2,3): 2}` — in Phase 1 agent_0 (RZA)
is upstream of agent_1 (OZA); in Phase 2 agent_2 (RZB) is upstream of agent_3 (OZB).

Full specification: `/docs/v9_messaging_protocol.md`

---

## Scenario and Environment Details

### Network layout

CC4 uses a segmented enterprise network with four sub-networks:

- **Deployed Network A and B** — each with a Restricted Zone and an Operational Zone
- **HQ Network** — Public Access Zone, Admin Zone, Office Network
- **Contractor Network** — single UAV control zone (undefended)

Zone sizes are randomised per episode: 1–6 servers and 3–10 user hosts per zone,
each with 1–5 services.

### Mission phases

The episode progresses linearly through three phases:

1. **Phase 1 (pre-planning):** all zones have equal low priority.
2. **Phase 2A (Mission A active):** Restricted/Operational Zone A elevated to high
   priority; large penalty multipliers apply in that zone.
3. **Phase 2B (Mission B active):** same as 2A but for Zone B.

Mission phase transitions affect the reward structure and the legal communication
policy. Blue agents receive the current policy in their observation vector and can
open or close firewall connections between zones.

### Reward structure

Blue agents accumulate negative rewards (penalties) when:

- A green agent cannot complete local work or reach a service.
- A green agent accesses a compromised service (red has presence on that host).
- A red agent executes the `Impact` action on a host.

Penalty magnitudes increase during active mission phases for the relevant zone.
Full reward tables are in the [original challenge documentation](https://cage-challenge.github.io/cage-challenge-4/).

### Observation vector

Each blue agent receives a flat binary vector constructed by `BlueFlatWrapper`:

- **Mission phase** (1 element, values 0/1/2)
- **Per-subnet block** (one block per defended subnet): one-hot subnet ID (9),
  blocked-subnet mask (9), communication policy mask (9), malicious-process flags
  per host (n), malicious-network-connection flags per host (n)
- **Message block** (4 × 8 bits from other blue agents)

Block size per subnet: `27 + 2 × n_hosts` (variable; padded to `MAX_HOSTS=16` per
subnet in fixed-length mode). `comms_policy[i] = 1` means subnet `i` **should be
blocked** from communicating with this agent's subnet (inverted adjacency convention).

In this fork the observation dtype is `float32` rather than the original `int64`,
eliminating a silent cast inside SB3 and halving memory bandwidth per observation.
The buffer is pre-allocated at `reset()` and filled in-place each step.

#### BlueFlatWrapperV2 (extended observation)

`CybORG/Agents/Wrappers/BlueFlatWrapperV2.py` extends `BlueFlatWrapper` by appending
`M` malicious-file flags at the end of the observation vector, where `M` is the total
number of actual hosts across all defended subnets:

```
[...standard BlueFlatWrapper obs...] + [malfile_flag_host_0, malfile_flag_host_1, ...]
```

A `malfile_flag` is `1.0` if any file on that host has `density >= 0.9` and
`signed == False` (the fingerprint of malware dropped by `ExploitRemoteService` and
`PrivilegeEscalate`). Green agents never drop high-density unsigned files, giving a
**0% false positive rate**. This catches:

- All `PrivilegeEscalate` drops (`escalate.exe` / `escalate.sh`).
- The 5% "silent exploit" case where `ExploitRemoteService` succeeds but generates no
  process-creation event (stochastic suppression in the original scenario).

`Remove` (after the B1 bug fix) now also clears malware files. A malfile flag with
no accompanying process/connection events is therefore the `PrivilegeEscalate`
signature (root session, no events) and should trigger `Restore` directly.

Use `BlueFlatWrapperV2` when evaluating `EnterpriseHeuristicAgent v9` (or v6+):

```python
from CybORG.Agents.Wrappers import BlueFlatWrapperV2
wrapped = BlueFlatWrapperV2(env)
```

### Actions

| Team | Key actions |
|---|---|
| Blue | `Monitor`, `Analyse`, `DeployDecoy`, `Remove`, `Restore`, `BlockTraffic`, `AllowTraffic` |
| Red | `DiscoverRemoteSystems`, `AggressiveServiceDiscovery`, `StealthServiceDiscovery`, `ExploitNetworkServices`, `PrivilegeEscalate`, `Impact`, `DegradeServices`, `DiscoverDeception`, `Withdraw` |
| Green | `GreenAccessService`, `GreenLocalWork` |

Actions have variable time durations (1–5 ticks). An agent must wait until its
current action completes before selecting the next one.

---

## Original Challenge Links

- **Official repository:** https://github.com/cage-challenge/cage-challenge-4
- **Installation and tutorials:** https://cage-challenge.github.io/cage-challenge-4/
- **AAAI 2025 paper:** https://ojs.aaai.org/index.php/AAAI/article/view/35158
- **AI Magazine paper:** https://onlinelibrary.wiley.com/doi/full/10.1002/aaai.70021
- **Original leaderboard:** https://codalab.lisn.upsaclay.fr/competitions/17672

---

## Contributing and Research Extensions

### Adding a new blue agent

1. Subclass `BaseAgent` (or implement the PettingZoo agent interface directly).
2. Place the file in `CybORG/Agents/SimpleAgents/` or create a subdirectory under
   `CybORG/Agents/` for more complex architectures.
3. Implement `get_action(observation, action_space)` returning a valid action index.
4. Run evaluation:

```bash
python CybORG/Evaluation/evaluation.py \
    --agent-path CybORG/Agents/SimpleAgents/YourAgent.py
```

### Running ablation experiments

The scenario generator exposes `steps`, `num_servers`, and `seed` parameters.
To fix the network topology across runs for controlled comparison:

```python
from CybORG.Simulator.Scenarios import EnterpriseScenarioGenerator
sg = EnterpriseScenarioGenerator(steps=500, seed=42)
```

Pass the generator to `CybORG` and wrap with `BlueEnterpriseWrapper` +
`BlueFlatWrapper` for the standard observation/action interface.

### Remaining optimization opportunities

All major hot paths identified in the initial swarm analysis have been addressed across
Waves 1–3. The primary remaining opportunities are:

- **Scenario pool tuning** — `pool_size=8` is a conservative default. Profiling on
  your hardware may show gains from larger pool sizes (16–32) if reset time remains
  a bottleneck relative to step time.
- **Cython / Numba acceleration of the inner step loop** — the Python interpreter
  overhead in `SimulationController._step` and `BlueFlatWrapper.observation_change`
  is now the dominant cost. A Cython extension or `@numba.njit` kernel for the
  observation assembly loop is the most productive next-level target.

Bug reports and pull requests are welcome. Please include before/after timing from
`cProfile` or `line_profiler` when submitting performance-related changes.

### Documentation index

| Document | Contents |
|---|---|
| `/docs/speed_report.md` | Benchmark timing results (Wave 1–3) |
| `/docs/simulation_audit_report.md` | Simulation bug audit: 10 fixes applied (2026-04-07) |
| `/docs/attack_chain_analysis.md` | Red agent attack chain analysis with FSM state tables |
| `/docs/v9_messaging_protocol.md` | Inter-agent messaging protocol v9 specification |
