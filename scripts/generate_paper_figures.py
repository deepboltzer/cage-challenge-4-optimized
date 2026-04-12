#!/usr/bin/env python3
"""Generate publication-quality figures for the MILCOM 2026 paper.

Runs experiments and creates IEEE-styled plots using SciencePlots.
Outputs PDF figures to docs/paper/figures/.

Usage:
    python scripts/generate_paper_figures.py                    # run all
    python scripts/generate_paper_figures.py --plots-only       # skip experiments, use cached data
    python scripts/generate_paper_figures.py --episodes 50      # override episode count
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

PAPER_DIR = Path(__file__).parent.parent / "docs" / "paper"
FIG_DIR = PAPER_DIR / "figures"
DATA_DIR = Path(__file__).parent.parent / "Results" / "paper_data"

PHASE_1_START = 167
PHASE_2_START = 334
MAX_STEPS = 500

# IEEE MILCOM color palette
COLORS = {
    "primary": "#003366",      # Dark navy
    "secondary": "#0066CC",    # Medium blue
    "accent1": "#CC3333",      # Red
    "accent2": "#339933",      # Green
    "accent3": "#FF9900",      # Orange
    "accent4": "#6633CC",      # Purple
    "light1": "#6699CC",       # Light blue
    "light2": "#99CC99",       # Light green
    "gray": "#666666",         # Medium gray
    "lightgray": "#CCCCCC",    # Light gray
}


def _get_phase(step: int) -> int:
    if step < PHASE_1_START:
        return 0
    elif step < PHASE_2_START:
        return 1
    return 2


# ═══════════════════════════════════════════════════════════════════════
# Data collection: run experiments
# ═══════════════════════════════════════════════════════════════════════

def _create_env(seed=42, max_steps=MAX_STEPS):
    from CybORG import CybORG
    from CybORG.Agents.Wrappers import BlueFlatWrapperV2
    from CybORG.Simulator.Scenarios import EnterpriseScenarioGenerator
    from CybORG.Agents.SimpleAgents.FiniteStateRedAgent import FiniteStateRedAgent
    from CybORG.Agents.SimpleAgents.EnterpriseGreenAgent import EnterpriseGreenAgent
    sg = EnterpriseScenarioGenerator(
        steps=max_steps, red_agent_class=FiniteStateRedAgent,
        green_agent_class=EnterpriseGreenAgent,
    )
    cyborg = CybORG(scenario_generator=sg, seed=seed)
    env = BlueFlatWrapperV2(env=cyborg)
    return cyborg, env


def _create_agents_v11a(env):
    from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV11a import make_heuristic_agents_v11a
    return make_heuristic_agents_v11a(env)


def _reset_episode(env, agents):
    obs_dict, _ = env.reset()
    subnet_hosts = getattr(env, "_cached_subnet_hosts", {})
    for name, ag in agents.items():
        ag.reset()
        ag.set_action_info(env.action_labels(name), env.action_mask(name), subnet_hosts)
    return obs_dict


def _step_env(env, agents, obs_dict):
    actions, messages = {}, {}
    for name, ag in agents.items():
        raw_obs = obs_dict.get(name, np.zeros(1))
        mask = env.action_mask(name)
        action_idx, msg = ag.get_action(raw_obs, np.array(mask, dtype=bool))
        actions[name] = action_idx
        messages[name] = msg
    obs_dict, rew_dict, term_dict, trunc_dict, _ = env.step(actions, messages=messages)
    return obs_dict, rew_dict, term_dict, trunc_dict, actions


def _get_state(env):
    return env.env.environment_controller.state


def _get_sim_controller(env):
    return env.env.environment_controller


def _get_service_reliability(state, hostname):
    host = state.hosts.get(hostname)
    if host is None:
        return {}
    return {sname: svc._percent_reliable for sname, svc in host.services.items()}


def _red_has_root(state, hostname):
    for agent_name, sessions in state.sessions.items():
        if "red" not in agent_name.lower():
            continue
        for sid, sess in sessions.items():
            if sess.hostname == hostname and sess.has_privileged_access():
                return True
    return False


def _get_blue_action_labels(actions, agents):
    result = {}
    for name, idx in actions.items():
        ag = agents.get(name)
        if ag and idx < len(ag._labels):
            result[name] = ag._labels[idx]
        else:
            result[name] = f"idx={idx}"
    return result


def collect_baseline_data(n_episodes=50, seed=42):
    """Collect per-episode and per-step reward data for V11a baseline."""
    print(f"\n{'='*70}")
    print(f"  Collecting V11a baseline data ({n_episodes} episodes, seed={seed})")
    print(f"{'='*70}")

    cyborg, env = _create_env(seed=seed)
    agents = _create_agents_v11a(env)

    episode_rewards = []
    step_rewards = []       # shape: (n_episodes, MAX_STEPS)
    phase_rewards = []      # shape: (n_episodes, 3)
    action_counts = []      # per-episode action type counts

    t0 = time.perf_counter()
    for ep in range(n_episodes):
        obs_dict = _reset_episode(env, agents)
        ep_reward = 0.0
        ep_step_rewards = []
        ep_phase_rew = [0.0, 0.0, 0.0]
        ep_actions = defaultdict(int)

        for step in range(MAX_STEPS):
            obs_dict, rew_dict, term_dict, trunc_dict, blue_actions = _step_env(
                env, agents, obs_dict
            )
            r = sum(rew_dict.values())
            ep_reward += r
            ep_step_rewards.append(r)
            ep_phase_rew[_get_phase(step)] += r

            # Count action types
            labels = _get_blue_action_labels(blue_actions, agents)
            for lbl in labels.values():
                atype = lbl.split(" ")[0] if " " in lbl else lbl
                ep_actions[atype] += 1

            if all(term_dict.get(n, False) or trunc_dict.get(n, False)
                   for n in env.possible_agents):
                ep_step_rewards.extend([0.0] * (MAX_STEPS - step - 1))
                break

        episode_rewards.append(ep_reward)
        step_rewards.append(ep_step_rewards)
        phase_rewards.append(ep_phase_rew)
        action_counts.append(dict(ep_actions))

        if (ep + 1) % 10 == 0:
            print(f"    ep {ep+1:3d}/{n_episodes}  reward={ep_reward:8.1f}  "
                  f"mean={np.mean(episode_rewards):8.1f}")

    elapsed = time.perf_counter() - t0
    print(f"    Completed in {elapsed:.1f}s")

    return {
        "episode_rewards": episode_rewards,
        "step_rewards": step_rewards,
        "phase_rewards": phase_rewards,
        "action_counts": action_counts,
        "seed": seed, "n_episodes": n_episodes,
    }


def collect_degradation_data(n_episodes=15, seed=42):
    """Collect detailed degradation visibility + timing data."""
    print(f"\n{'='*70}")
    print(f"  Collecting degradation data ({n_episodes} episodes, seed={seed})")
    print(f"{'='*70}")

    cyborg, env = _create_env(seed=seed)
    agents = _create_agents_v11a(env)

    # Visibility tracking
    total_events = 0
    invisible_events = 0
    visible_events = 0
    by_channel = {"conn": 0, "proc": 0, "malfile": 0}
    by_subnet = defaultdict(int)
    by_phase = defaultdict(int)

    # Timing tracking
    host_timelines = {}
    reliability_trajectories = []  # (step, mean_reliability) per episode

    for ep in range(n_episodes):
        obs_dict = _reset_episode(env, agents)
        state = _get_state(env)
        sim = _get_sim_controller(env)
        all_hosts = list(state.hosts.keys())

        prev_reliability = {h: _get_service_reliability(state, h) for h in all_hosts}
        ep_reliability = []

        for step in range(MAX_STEPS):
            obs_dict, rew_dict, term_dict, trunc_dict, blue_actions = _step_env(
                env, agents, obs_dict
            )
            state = _get_state(env)
            curr_reliability = {h: _get_service_reliability(state, h) for h in all_hosts}

            # Mean reliability across all services
            all_rels = []
            for h in all_hosts:
                for sname, val in curr_reliability[h].items():
                    all_rels.append(val)
            ep_reliability.append(np.mean(all_rels) if all_rels else 100.0)

            # Detect degradation events
            from CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV11a import (
                EnterpriseHeuristicAgentV11a,
            )
            for h in all_hosts:
                prev_r = prev_reliability.get(h, {})
                curr_r = curr_reliability.get(h, {})
                for sname in curr_r:
                    prev_val = prev_r.get(sname, 100)
                    curr_val = curr_r[sname]
                    if curr_val < prev_val:
                        total_events += 1
                        phase = _get_phase(step)
                        by_phase[phase] += 1

                        # Subnet
                        subnet = "unknown"
                        for sn_name in ["contractor", "admin", "office",
                                        "operational_zone_a", "operational_zone_b",
                                        "restricted_zone_a", "restricted_zone_b",
                                        "public_access"]:
                            if sn_name in h:
                                subnet = sn_name
                                break
                        by_subnet[subnet] += 1

                        # This is invisible (no blue observation signals for DegradeServices)
                        invisible_events += 1

                        # Check if coincidentally an alert was present
                        # (from other red actions, not from degradation itself)

                # Track host timelines for timing analysis
                has_root = _red_has_root(state, h)
                key = (ep, h)
                if key not in host_timelines:
                    host_timelines[key] = {
                        "first_root": None, "first_degrade": None,
                        "first_restore": None, "degrade_count": 0,
                        "never_restored": True,
                    }
                tl = host_timelines[key]
                if has_root and tl["first_root"] is None:
                    tl["first_root"] = step
                for sname in curr_r:
                    if curr_r[sname] < prev_r.get(sname, 100):
                        tl["degrade_count"] += 1
                        if tl["first_degrade"] is None:
                            tl["first_degrade"] = step

                labels = _get_blue_action_labels(blue_actions, agents)
                for lbl in labels.values():
                    if "Restore" in lbl and h in lbl:
                        if tl["first_restore"] is None:
                            tl["first_restore"] = step
                            tl["never_restored"] = False

            prev_reliability = curr_reliability

            if all(term_dict.get(n, False) or trunc_dict.get(n, False)
                   for n in env.possible_agents):
                ep_reliability.extend([ep_reliability[-1]] * (MAX_STEPS - step - 1))
                break

        reliability_trajectories.append(ep_reliability)
        print(f"    ep {ep+1:3d}/{n_episodes}  degrade_events={total_events}")

    # Compute timing gaps
    gaps_root_to_degrade = []
    gaps_root_to_restore = []
    degraded_never_restored = 0
    total_degraded_hosts = 0

    for key, tl in host_timelines.items():
        if tl["first_degrade"] is not None:
            total_degraded_hosts += 1
            if tl["first_root"] is not None:
                gaps_root_to_degrade.append(tl["first_degrade"] - tl["first_root"])
            if tl["first_restore"] is not None:
                gaps_root_to_restore.append(tl["first_restore"] - tl["first_root"]
                                            if tl["first_root"] is not None else 999)
            if tl["never_restored"]:
                degraded_never_restored += 1

    return {
        "total_events": total_events,
        "invisible_events": invisible_events,
        "visible_events": visible_events,
        "by_subnet": dict(by_subnet),
        "by_phase": dict(by_phase),
        "gaps_root_to_degrade": gaps_root_to_degrade,
        "gaps_root_to_restore": gaps_root_to_restore,
        "degraded_never_restored": degraded_never_restored,
        "total_degraded_hosts": total_degraded_hosts,
        "reliability_trajectories": [t[:MAX_STEPS] for t in reliability_trajectories],
        "n_episodes": n_episodes, "seed": seed,
    }


def collect_countermeasure_data(n_episodes=50, seed=42):
    """Run countermeasure experiments (3 and 4) and collect per-episode data."""
    print(f"\n{'='*70}")
    print(f"  Collecting countermeasure comparison data ({n_episodes} eps, seed={seed})")
    print(f"{'='*70}")

    from scripts.degrade_experiment import (
        _run_episodes, _create_agents_v11a as _factory_v11a,
        _create_agents_v11a_proactive_oz,
    )
    import CybORG.Agents.SimpleAgents.EnterpriseHeuristicAgentV11a as v11a_mod

    original_fn = v11a_mod._is_active_oz_server

    # 1. Baseline
    print("\n  --- V11a Baseline ---")
    v11a_mod._is_active_oz_server = original_fn
    baseline = _run_episodes(n_episodes, seed, _factory_v11a, "baseline")

    # 2. Proactive OZ Restore
    print("\n  --- Proactive OZ Restore ---")
    v11a_mod._is_active_oz_server = original_fn
    proactive = _run_episodes(
        n_episodes, seed,
        lambda env: _create_agents_v11a_proactive_oz(env, 15),
        "proactive_oz"
    )

    # 3. Expanded flag_age=0 (all OZ hosts)
    print("\n  --- Expanded flag_age=0 ---")
    def _patched(hostname, phase):
        if phase == 1 and "operational_zone_a" in hostname:
            return True
        if phase == 2 and "operational_zone_b" in hostname:
            return True
        return False
    v11a_mod._is_active_oz_server = _patched
    expanded_flag = _run_episodes(n_episodes, seed, _factory_v11a, "expanded_flag")

    # 4. Combined
    print("\n  --- Combined (proactive + expanded flag) ---")
    v11a_mod._is_active_oz_server = _patched
    combined = _run_episodes(
        n_episodes, seed,
        lambda env: _create_agents_v11a_proactive_oz(env, 15),
        "combined"
    )

    v11a_mod._is_active_oz_server = original_fn

    return {
        "baseline": baseline,
        "proactive_oz": proactive,
        "expanded_flag_age": expanded_flag,
        "combined": combined,
        "seed": seed, "n_episodes": n_episodes,
    }


def collect_cross_seed_data(n_episodes=30, seeds=(42, 123, 7)):
    """Run V11a across multiple seeds for robustness analysis."""
    print(f"\n{'='*70}")
    print(f"  Collecting cross-seed data ({n_episodes} eps, seeds={seeds})")
    print(f"{'='*70}")

    from scripts.degrade_experiment import _run_episodes, _create_agents_v11a as _fac

    results = {}
    for s in seeds:
        print(f"\n  --- Seed {s} ---")
        results[s] = _run_episodes(n_episodes, s, _fac, f"seed_{s}")

    return {"seeds": {str(s): r for s, r in results.items()},
            "n_episodes": n_episodes}


# ═══════════════════════════════════════════════════════════════════════
# Plot generation
# ═══════════════════════════════════════════════════════════════════════

def setup_plotting():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import scienceplots  # noqa: F401
    plt.style.use(["science", "ieee", "no-latex"])
    plt.rcParams.update({
        "font.size": 8,
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "legend.fontsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
    })
    return plt


def fig3_reward_analysis(plt, baseline_data, countermeasure_data, save=True):
    """Figure 3: 2x2 — Reward analysis and countermeasure comparison.

    (a) Cumulative reward trajectory over 500 steps
    (b) Per-phase reward breakdown
    (c) Countermeasure box plots
    (d) Effect sizes (forest plot)
    """
    from scipy import stats as sp_stats

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.0))

    # ── (a) Cumulative reward trajectory ──
    ax = axes[0, 0]
    step_rewards = np.array(baseline_data["step_rewards"])
    cumulative = np.cumsum(step_rewards, axis=1)
    mean_cum = np.mean(cumulative, axis=1)
    mean_traj = np.mean(cumulative, axis=0)
    std_traj = np.std(cumulative, axis=0)

    steps = np.arange(MAX_STEPS)
    ax.plot(steps, mean_traj, color=COLORS["primary"], linewidth=1.2, label="Mean")
    ax.fill_between(steps, mean_traj - std_traj, mean_traj + std_traj,
                    alpha=0.2, color=COLORS["secondary"])

    # Phase boundaries
    for ps, lbl in [(PHASE_1_START, "Phase 1"), (PHASE_2_START, "Phase 2")]:
        ax.axvline(ps, color=COLORS["accent1"], linestyle="--", linewidth=0.7, alpha=0.7)
        ax.text(ps + 3, ax.get_ylim()[0] * 0.05, lbl,
                fontsize=6, color=COLORS["accent1"], rotation=90, va="bottom")

    ax.set_xlabel("Step")
    ax.set_ylabel("Cumulative Reward")
    ax.set_title("(a) Reward Trajectory")
    ax.legend(loc="lower left", framealpha=0.8)

    # ── (b) Per-phase reward breakdown ──
    ax = axes[0, 1]
    phase_rewards = np.array(baseline_data["phase_rewards"])
    phase_means = np.mean(phase_rewards, axis=0)
    phase_stds = np.std(phase_rewards, axis=0)
    phase_labels = ["Phase 0\n(steps 0–166)", "Phase 1\n(steps 167–333)",
                    "Phase 2\n(steps 334–499)"]
    colors_phase = [COLORS["secondary"], COLORS["accent1"], COLORS["accent3"]]

    bars = ax.bar(range(3), phase_means, yerr=phase_stds, capsize=3,
                  color=colors_phase, edgecolor="black", linewidth=0.5, alpha=0.85)
    ax.set_xticks(range(3))
    ax.set_xticklabels(phase_labels, fontsize=6)
    ax.set_ylabel("Mean Reward")
    ax.set_title("(b) Reward by Mission Phase")

    # Add value labels
    for bar, m, s in zip(bars, phase_means, phase_stds):
        ax.text(bar.get_x() + bar.get_width() / 2, m - s - 15,
                f"{m:.0f}", ha="center", va="top", fontsize=6, fontweight="bold")

    # ── (c) Countermeasure comparison (box plots) ──
    ax = axes[1, 0]
    cm = countermeasure_data
    data_list = [cm["baseline"], cm["proactive_oz"],
                 cm["expanded_flag_age"], cm["combined"]]
    labels_cm = ["V11a\nBaseline", "Proactive\nOZ Restore",
                 "Expanded\nFlag-Age", "Combined"]
    colors_cm = [COLORS["primary"], COLORS["accent2"],
                 COLORS["accent3"], COLORS["accent4"]]

    bp = ax.boxplot(data_list, patch_artist=True, widths=0.6,
                    medianprops=dict(color="black", linewidth=1.2),
                    flierprops=dict(marker="o", markersize=2, alpha=0.4))
    for patch, c in zip(bp["boxes"], colors_cm):
        patch.set_facecolor(c)
        patch.set_alpha(0.7)
    ax.set_xticklabels(labels_cm, fontsize=6)
    ax.set_ylabel("Episode Reward")
    ax.set_title("(c) Countermeasure Comparison")

    # Add means as diamonds
    means = [np.mean(d) for d in data_list]
    for i, m in enumerate(means):
        ax.plot(i + 1, m, "D", color="white", markersize=4,
                markeredgecolor="black", markeredgewidth=0.8, zorder=5)

    # ── (d) Effect sizes (forest plot) ──
    ax = axes[1, 1]
    baseline_arr = np.array(cm["baseline"])
    experiments = [
        ("Proactive\nOZ Restore", cm["proactive_oz"]),
        ("Expanded\nFlag-Age", cm["expanded_flag_age"]),
        ("Combined", cm["combined"]),
    ]

    y_positions = list(range(len(experiments)))
    for i, (label, data) in enumerate(experiments):
        data_arr = np.array(data)
        delta = data_arr.mean() - baseline_arr.mean()
        pooled_std = np.sqrt((baseline_arr.std()**2 + data_arr.std()**2) / 2)
        d = delta / pooled_std if pooled_std > 0 else 0

        # 95% CI for Cohen's d (approximate)
        n1, n2 = len(baseline_arr), len(data_arr)
        se_d = np.sqrt((n1 + n2) / (n1 * n2) + d**2 / (2 * (n1 + n2)))
        ci_lo, ci_hi = d - 1.96 * se_d, d + 1.96 * se_d

        # t-test
        t_stat, p_val = sp_stats.ttest_ind(baseline_arr, data_arr, equal_var=False)

        color = COLORS["accent1"] if p_val < 0.05 else COLORS["gray"]
        ax.errorbar(d, i, xerr=[[d - ci_lo], [ci_hi - d]],
                    fmt="o", color=color, markersize=5, capsize=3,
                    linewidth=1.2, markeredgecolor="black", markeredgewidth=0.5)
        ax.text(ci_hi + 0.05, i, f"p={p_val:.3f}", va="center",
                fontsize=6, color=color)

    ax.axvline(0, color="black", linestyle="-", linewidth=0.8)
    ax.axvspan(-0.2, 0.2, alpha=0.1, color=COLORS["lightgray"])
    ax.set_yticks(y_positions)
    ax.set_yticklabels([e[0] for e in experiments], fontsize=6)
    ax.set_xlabel("Cohen's $d$ (effect size)")
    ax.set_title("(d) Effect Sizes vs. Baseline")
    ax.text(0, -0.6, "negligible", ha="center", fontsize=5, color=COLORS["gray"],
            style="italic")

    plt.tight_layout()
    if save:
        fig.savefig(FIG_DIR / "fig3_reward_analysis.pdf")
        fig.savefig(FIG_DIR / "fig3_reward_analysis.png")
        print(f"  Saved fig3_reward_analysis.pdf/png")
    return fig


def fig4_degradation_analysis(plt, degrade_data, baseline_data, save=True):
    """Figure 4: 2x2 — DegradeServices information asymmetry analysis.

    (a) Degradation events by subnet
    (b) Service reliability trajectory over episode
    (c) Timing gaps (root → degrade → restore)
    (d) Degradation by mission phase + restoration rate
    """
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.0))

    # ── (a) Degradation events by subnet ──
    ax = axes[0, 0]
    subnet_data = degrade_data["by_subnet"]
    # Clean up subnet names
    name_map = {
        "contractor": "Contractor",
        "admin": "Admin",
        "office": "Office",
        "operational_zone_a": "OZ-A",
        "operational_zone_b": "OZ-B",
        "restricted_zone_a": "RZ-A",
        "restricted_zone_b": "RZ-B",
        "public_access": "PAZ",
        "unknown": "Unknown",
    }
    subnets = sorted(subnet_data.keys(), key=lambda x: -subnet_data[x])
    counts = [subnet_data[s] for s in subnets]
    clean_names = [name_map.get(s, s) for s in subnets]
    total = sum(counts)
    pcts = [c / total * 100 for c in counts]

    colors_sub = []
    for s in subnets:
        if s == "contractor":
            colors_sub.append(COLORS["accent1"])
        elif "operational" in s:
            colors_sub.append(COLORS["accent3"])
        else:
            colors_sub.append(COLORS["secondary"])

    bars = ax.barh(range(len(subnets)), pcts, color=colors_sub,
                   edgecolor="black", linewidth=0.5, alpha=0.85)
    ax.set_yticks(range(len(subnets)))
    ax.set_yticklabels(clean_names, fontsize=6)
    ax.set_xlabel("Share of Degradation Events (%)")
    ax.set_title("(a) Degradation by Subnet")
    ax.invert_yaxis()

    # Add percentage labels
    for bar, pct in zip(bars, pcts):
        if pct > 5:
            ax.text(bar.get_width() - 1, bar.get_y() + bar.get_height() / 2,
                    f"{pct:.1f}%", ha="right", va="center", fontsize=6,
                    fontweight="bold", color="white")

    # Mark "No Blue Coverage" for contractor
    for i, s in enumerate(subnets):
        if s == "contractor":
            ax.annotate("No blue\ncoverage", xy=(pcts[i], i),
                        xytext=(pcts[i] + 8, i + 0.3),
                        fontsize=5, color=COLORS["accent1"],
                        arrowprops=dict(arrowstyle="->", color=COLORS["accent1"],
                                        lw=0.7))

    # ── (b) Service reliability trajectory ──
    ax = axes[0, 1]
    trajectories = np.array(degrade_data["reliability_trajectories"])
    mean_rel = np.mean(trajectories, axis=0)
    std_rel = np.std(trajectories, axis=0)
    steps = np.arange(len(mean_rel))

    ax.plot(steps, mean_rel, color=COLORS["primary"], linewidth=1.0, label="Mean")
    ax.fill_between(steps, mean_rel - std_rel, mean_rel + std_rel,
                    alpha=0.15, color=COLORS["secondary"])

    # Phase boundaries
    for ps in [PHASE_1_START, PHASE_2_START]:
        ax.axvline(ps, color=COLORS["accent1"], linestyle="--", linewidth=0.6, alpha=0.5)

    ax.set_xlabel("Step")
    ax.set_ylabel("Mean Service Reliability (%)")
    ax.set_title("(b) Reliability Degradation Over Time")
    ax.set_ylim(bottom=max(0, mean_rel.min() - 10))

    # ── (c) Timing gaps ──
    ax = axes[1, 0]
    gaps_rd = degrade_data["gaps_root_to_degrade"]
    gaps_rr = degrade_data["gaps_root_to_restore"]

    gap_data = []
    gap_labels = []
    gap_colors = []

    if gaps_rd:
        gap_data.append(gaps_rd)
        gap_labels.append("Root →\nDegrade")
        gap_colors.append(COLORS["accent1"])
    if gaps_rr:
        gap_data.append(gaps_rr)
        gap_labels.append("Root →\nRestore")
        gap_colors.append(COLORS["accent2"])

    if gap_data:
        vp = ax.violinplot(gap_data, showmeans=True, showmedians=True)
        for i, body in enumerate(vp["bodies"]):
            body.set_facecolor(gap_colors[i])
            body.set_alpha(0.6)
        if "cmeans" in vp:
            vp["cmeans"].set_color("black")
        if "cmedians" in vp:
            vp["cmedians"].set_color(COLORS["accent1"])
            vp["cmedians"].set_linewidth(1.5)
        ax.set_xticks(range(1, len(gap_data) + 1))
        ax.set_xticklabels(gap_labels, fontsize=6)

    ax.set_ylabel("Steps")
    ax.set_title("(c) Attack-to-Response Timing Gaps")

    # Add stats text
    if gaps_rd:
        ax.text(0.98, 0.95,
                f"Root→Degrade: μ={np.mean(gaps_rd):.1f}, med={np.median(gaps_rd):.0f}\n"
                f"Root→Restore: μ={np.mean(gaps_rr):.1f}, med={np.median(gaps_rr):.0f}",
                transform=ax.transAxes, fontsize=5, va="top", ha="right",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                          edgecolor=COLORS["lightgray"], alpha=0.9))

    # ── (d) Phase breakdown + restoration rate ──
    ax = axes[1, 1]
    phase_data = degrade_data["by_phase"]
    phases = [0, 1, 2]
    phase_counts = [phase_data.get(p, 0) for p in phases]
    phase_names = ["Phase 0", "Phase 1", "Phase 2"]
    colors_ph = [COLORS["secondary"], COLORS["accent1"], COLORS["accent3"]]

    ax2 = ax.twinx()

    x = np.arange(3)
    width = 0.35

    bars1 = ax.bar(x - width / 2, phase_counts, width,
                   color=colors_ph, edgecolor="black", linewidth=0.5,
                   alpha=0.8, label="Degrade events")

    # Restoration rate
    never_restored = degrade_data["degraded_never_restored"]
    total_degraded = degrade_data["total_degraded_hosts"]
    restored_pct = ((total_degraded - never_restored) / total_degraded * 100
                    if total_degraded > 0 else 0)
    never_pct = 100 - restored_pct

    # Show as annotation instead of second bar set
    ax.text(0.02, 0.95,
            f"Degraded hosts: {total_degraded}\n"
            f"Never restored: {never_restored} ({never_pct:.0f}%)\n"
            f"Restored: {total_degraded - never_restored} ({restored_pct:.0f}%)",
            transform=ax.transAxes, fontsize=6, va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                      edgecolor=COLORS["lightgray"], alpha=0.9))

    ax.set_xticks(x)
    ax.set_xticklabels(phase_names, fontsize=7)
    ax.set_ylabel("Degradation Events")
    ax.set_title("(d) Degradation by Phase & Restoration")
    ax2.set_yticks([])

    plt.tight_layout()
    if save:
        fig.savefig(FIG_DIR / "fig4_degradation_analysis.pdf")
        fig.savefig(FIG_DIR / "fig4_degradation_analysis.png")
        print(f"  Saved fig4_degradation_analysis.pdf/png")
    return fig


def fig5_robustness(plt, cross_seed_data, baseline_data, save=True):
    """Figure 5: 1x2 — Robustness and statistical validation.

    (a) Cross-seed reward distributions
    (b) Episode reward histogram with fitted normal
    """
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8))

    # ── (a) Cross-seed comparison ──
    ax = axes[0]
    seeds_data = cross_seed_data["seeds"]
    seed_keys = sorted(seeds_data.keys(), key=int)
    data_list = [seeds_data[k] for k in seed_keys]
    seed_labels = [f"Seed {k}" for k in seed_keys]
    colors_seeds = [COLORS["primary"], COLORS["secondary"], COLORS["accent2"]]

    bp = ax.boxplot(data_list, patch_artist=True, widths=0.5,
                    medianprops=dict(color="black", linewidth=1.5),
                    flierprops=dict(marker="o", markersize=2, alpha=0.4))
    for patch, c in zip(bp["boxes"], colors_seeds[:len(data_list)]):
        patch.set_facecolor(c)
        patch.set_alpha(0.7)

    # Add individual points (jittered)
    for i, data in enumerate(data_list):
        jitter = np.random.default_rng(42).normal(0, 0.06, len(data))
        ax.scatter(np.full(len(data), i + 1) + jitter, data,
                   s=6, alpha=0.3, color=colors_seeds[i % len(colors_seeds)],
                   zorder=3, edgecolors="none")

    ax.set_xticklabels(seed_labels, fontsize=7)
    ax.set_ylabel("Episode Reward")
    ax.set_title("(a) Cross-Seed Robustness")

    # Add means
    for i, data in enumerate(data_list):
        m = np.mean(data)
        ax.plot(i + 1, m, "D", color="white", markersize=5,
                markeredgecolor="black", markeredgewidth=0.8, zorder=5)
        ax.text(i + 1 + 0.3, m, f"μ={m:.0f}", fontsize=6, va="center")

    # Cross-seed stats
    all_means = [np.mean(d) for d in data_list]
    ax.text(0.02, 0.02, f"Cross-seed σ = {np.std(all_means):.1f}",
            transform=ax.transAxes, fontsize=6, va="bottom",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="lightyellow",
                      edgecolor=COLORS["lightgray"]))

    # ── (b) Reward distribution histogram ──
    ax = axes[1]
    rewards = np.array(baseline_data["episode_rewards"])
    n_bins = min(20, max(8, len(rewards) // 3))

    ax.hist(rewards, bins=n_bins, density=True, alpha=0.7,
            color=COLORS["primary"], edgecolor="black", linewidth=0.5,
            label=f"V11a (n={len(rewards)})")

    # Fit normal distribution
    from scipy import stats as sp_stats
    mu, sigma = rewards.mean(), rewards.std()
    x_fit = np.linspace(rewards.min() - 50, rewards.max() + 50, 200)
    pdf = sp_stats.norm.pdf(x_fit, mu, sigma)
    ax.plot(x_fit, pdf, color=COLORS["accent1"], linewidth=1.2, linestyle="--",
            label=f"Normal fit\nμ={mu:.0f}, σ={sigma:.0f}")

    # Shapiro-Wilk test
    if len(rewards) <= 5000:
        w_stat, w_p = sp_stats.shapiro(rewards)
        ax.text(0.02, 0.95,
                f"Shapiro-Wilk: W={w_stat:.3f}, p={w_p:.3f}",
                transform=ax.transAxes, fontsize=5, va="top",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                          edgecolor=COLORS["lightgray"]))

    ax.set_xlabel("Episode Reward")
    ax.set_ylabel("Density")
    ax.set_title("(b) Reward Distribution")
    ax.legend(loc="upper left", fontsize=6, framealpha=0.8)

    plt.tight_layout()
    if save:
        fig.savefig(FIG_DIR / "fig5_robustness.pdf")
        fig.savefig(FIG_DIR / "fig5_robustness.png")
        print(f"  Saved fig5_robustness.pdf/png")
    return fig


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Generate MILCOM 2026 paper figures")
    parser.add_argument("--episodes", type=int, default=30,
                        help="Episodes per experiment (default: 30)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--plots-only", action="store_true",
                        help="Skip experiments, load cached data")
    args = parser.parse_args()

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    data_file = DATA_DIR / f"paper_data_s{args.seed}_n{args.episodes}.json"

    if args.plots_only and data_file.exists():
        print(f"Loading cached data from {data_file}")
        with open(data_file) as f:
            all_data = json.load(f)
    else:
        print(f"Running experiments (episodes={args.episodes}, seed={args.seed})")
        t0 = time.perf_counter()

        baseline = collect_baseline_data(n_episodes=args.episodes, seed=args.seed)
        degrade = collect_degradation_data(n_episodes=min(15, args.episodes), seed=args.seed)
        countermeasures = collect_countermeasure_data(n_episodes=args.episodes, seed=args.seed)
        cross_seed = collect_cross_seed_data(n_episodes=args.episodes,
                                             seeds=(42, 123, 7))

        elapsed = time.perf_counter() - t0
        print(f"\nAll experiments completed in {elapsed:.0f}s ({elapsed/60:.1f} min)")

        all_data = {
            "baseline": baseline,
            "degradation": degrade,
            "countermeasures": countermeasures,
            "cross_seed": cross_seed,
        }

        # Save data (convert numpy to lists)
        def _to_json(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, dict):
                return {k: _to_json(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_to_json(v) for v in obj]
            return obj

        with open(data_file, "w") as f:
            json.dump(_to_json(all_data), f, indent=2)
        print(f"Saved data to {data_file}")

    # Generate plots
    print(f"\nGenerating figures...")
    plt = setup_plotting()

    fig3_reward_analysis(plt, all_data["baseline"], all_data["countermeasures"])
    fig4_degradation_analysis(plt, all_data["degradation"], all_data["baseline"])
    fig5_robustness(plt, all_data["cross_seed"], all_data["baseline"])

    print(f"\nAll figures saved to {FIG_DIR}/")
    print("Files: fig3_reward_analysis.pdf, fig4_degradation_analysis.pdf, fig5_robustness.pdf")


if __name__ == "__main__":
    main()
