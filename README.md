# CAGE Challenge 4 — Optimized Research Fork

This repository is an optimized fork of the official [CAGE Challenge 4 (CC4)](https://github.com/cage-challenge/cage-challenge-4)
environment, maintained for ML/AI research focused on fast experiment iteration and
autonomous cyber-defence agent development. The simulation behavior — rewards,
observations, actions, and randomness — is preserved exactly; all changes are
purely performance-oriented.

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

See `/docs/optimization_master_plan.md` for the full item-by-item breakdown with file
paths, line numbers, and behavior-safety rationale. Detailed analysis by subsystem is in
`/docs/analysis_obs_pipeline.md`, `/docs/analysis_simloop.md`, and
`/docs/analysis_training_harness.md`.

---

## Performance Benchmarks

Measured throughput after Wave 1 and Wave 2 (20 episodes × 500 steps, seed=42,
`EnterpriseHeuristicAgent v5`): **80.8 steps/sec**, mean episode time 6,257 ms,
mean step time 12.37 ms. This is measured with full agent decision overhead included;
raw environment throughput is higher. See `/docs/speed_report.md` for latest numbers
including Wave 3 results when available.

**Known agent reward baselines** (100 episodes, 500 steps each, `FiniteStateRedAgent`):

| Agent | Mean Reward | Std Dev | Notes |
|---|---|---|---|
| SleepAgent (baseline) | -31,882 | — | Takes no action every step |
| EnterpriseHeuristicAgent v4 | -5,025 | 1,570 | 84.2% improvement over SleepAgent |

The heuristic v4 result was obtained with reactive-only strategy (no proactive Restores)
and communications-policy blocking enabled. See `/docs/` for strategy notes.

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
(100 episodes, 500 steps, `FiniteStateRedAgent`). Add your own results by running
`evaluation.py` and recording `reward_mean` and `reward_stdev` from `summary.json`.

| Rank | Agent | Mean Reward | Std Dev |
|---|---|---|---|
| — | SleepAgent | -31,882 | — |
| 1 | EnterpriseHeuristicAgent v4 | -5,025 | 1,570 |

Strategy notes for the heuristic agent:

- Reactive-only: only issues `Remove` or `Restore` in response to confirmed alerts;
  no proactive Restores.
- Communications policy: blocks inbound subnets when the mission policy indicates
  they should be blocked, reducing red lateral movement opportunities.
- No decoys deployed (marginal benefit observed in testing).

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
- **Per-subnet block** (one block per defended subnet): one-hot subnet ID,
  blocked-subnet mask, communication policy mask, malicious-process flags per host,
  malicious-network-connection flags per host
- **Message block** (4 × 8 bits from other blue agents)

In this fork the observation dtype is `float32` rather than the original `int64`,
eliminating a silent cast inside SB3 and halving memory bandwidth per observation.
The buffer is pre-allocated at `reset()` and filled in-place each step.

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
