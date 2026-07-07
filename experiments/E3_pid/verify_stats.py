"""
verify_stats.py - Compute all statistics from dataset_cleaned.csv
and verify against checkpoint values used in research_pap_v4.tex.

Run:  python verify_stats.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np
from scipy import stats

CSV = "dataset_cleaned.csv"
df = pd.read_csv(CSV)

# ─── TOTAL COUNTS ───────────────────────────────────────────
total = len(df)
dns = df[df["success"] == "n"]
dns_count = len(dns)
valid = df[df["success"] == "y"].copy()
valid_count = len(valid)
print(f"TOTAL TRIALS: {total}")
print(f"DNS EVENTS:   {dns_count}  ({dns_count/total*100:.1f}%)")
print(f"VALID TRIALS: {valid_count}")
print()

# ─── DNS DETAILS ────────────────────────────────────────────
print("DNS EVENT DETAILS:")
for _, row in dns.iterrows():
    print(f"  {row['op_id']}, Servo {row['servo_id']}, "
          f"mode={row['mode']}, "
          f"arm_len={row['arm_len']}mm, discs={row['discs']}, "
          f"anomaly={row['anomaly']}")
print()

# ─── OPERATOR COUNTS ───────────────────────────────────────
ops = df["op_id"].unique()
print(f"OPERATORS: {len(ops)}")
inf_ops = [o for o in ops if o.startswith("inf")]
nai_ops = [o for o in ops if o.startswith("nai")]
print(f"  Informed: {len(inf_ops)} — {sorted(inf_ops)}")
print(f"  Naive:    {len(nai_ops)} — {sorted(nai_ops)}")
print()

# ─── LOAD CONDITIONS ────────────────────────────────────────
valid["condition"] = valid.apply(
    lambda r: f"{int(r['arm_len'])}mm+{int(r['discs']*50)}g"
              if r["arm_len"] > 0 else "Baseline (0g)", axis=1)
print(f"LOAD CONDITIONS: {sorted(valid['condition'].unique())}")
print(f"SERVO JOINTS:    {sorted(valid['servo_id'].unique())}")
print()

# ─── SPLIT BY MODE ──────────────────────────────────────────
manual = valid[valid["mode"] == "m"]
advisor = valid[valid["mode"] == "a"]
print(f"VALID MANUAL:  {len(manual)}")
print(f"VALID ADVISOR: {len(advisor)}")
print()

# ─── OVERALL STATISTICS ────────────────────────────────────
man_mean = manual["total_time"].mean()
man_std  = manual["total_time"].std(ddof=1)
adv_mean = advisor["total_time"].mean()
adv_std  = advisor["total_time"].std(ddof=1)
eta = man_mean / adv_mean
reduction = (1 - adv_mean / man_mean) * 100

# Cohen's d (pooled SD)
n1, n2 = len(manual), len(advisor)
pooled_sd = np.sqrt(((n1-1)*man_std**2 + (n2-1)*adv_std**2) / (n1+n2-2))
d = (man_mean - adv_mean) / pooled_sd

# Mann-Whitney U
u_stat, p_two = stats.mannwhitneyu(manual["total_time"],
                                    advisor["total_time"],
                                    alternative="greater")
# Z approximation
n_total = n1 + n2
mu_u = n1 * n2 / 2
sigma_u = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
z_val = (u_stat - mu_u) / sigma_u
r_eff = z_val / np.sqrt(n_total)

print("═══ OVERALL ═══")
print(f"  Manual:    {man_mean:.1f} ± {man_std:.1f}s  (n={n1})")
print(f"  Advisor:   {adv_mean:.1f} ± {adv_std:.1f}s  (n={n2})")
print(f"  η = {eta:.2f},  Reduction = {reduction:.1f}%,  Cohen's d = {d:.2f}")
print(f"  Mann-Whitney: U={u_stat:.1f}, Z={z_val:.2f}, p={p_two:.2e}, r={r_eff:.3f}")
print()

# ─── 95% BOOTSTRAP CI FOR η ────────────────────────────────
rng = np.random.default_rng(42)
n_boot = 10000
man_vals = manual["total_time"].values
adv_vals = advisor["total_time"].values
boot_etas = []
for _ in range(n_boot):
    bm = rng.choice(man_vals, size=len(man_vals), replace=True)
    ba = rng.choice(adv_vals, size=len(adv_vals), replace=True)
    boot_etas.append(bm.mean() / ba.mean())
boot_etas = np.array(boot_etas)
ci_lo, ci_hi = np.percentile(boot_etas, [2.5, 97.5])
print(f"  95% Bootstrap CI for η: [{ci_lo:.2f}, {ci_hi:.2f}]")
print()

# ─── BY EXPERIENCE GROUP ───────────────────────────────────
for grp_name, grp_prefix in [("INFORMED", "inf"), ("NAIVE", "nai")]:
    gm = manual[manual["exp_level"] == grp_prefix]
    ga = advisor[advisor["exp_level"] == grp_prefix]
    gm_mean = gm["total_time"].mean()
    gm_std  = gm["total_time"].std(ddof=1)
    ga_mean = ga["total_time"].mean()
    ga_std  = ga["total_time"].std(ddof=1)
    g_eta = gm_mean / ga_mean
    g_red = (1 - ga_mean / gm_mean) * 100
    gn1, gn2 = len(gm), len(ga)
    g_pooled = np.sqrt(((gn1-1)*gm_std**2 + (gn2-1)*ga_std**2) / (gn1+gn2-2))
    g_d = (gm_mean - ga_mean) / g_pooled

    g_u, g_p = stats.mannwhitneyu(gm["total_time"], ga["total_time"],
                                   alternative="greater")
    g_mu = gn1 * gn2 / 2
    g_sig = np.sqrt(gn1 * gn2 * (gn1 + gn2 + 1) / 12)
    g_z = (g_u - g_mu) / g_sig
    g_r = g_z / np.sqrt(gn1 + gn2)

    print(f"═══ {grp_name} (n={gn1} manual, {gn2} advisor) ═══")
    print(f"  Manual:  {gm_mean:.1f} ± {gm_std:.1f}s")
    print(f"  Advisor: {ga_mean:.1f} ± {ga_std:.1f}s")
    print(f"  η = {g_eta:.2f}, Reduction = {g_red:.1f}%, Cohen's d = {g_d:.2f}")
    print(f"  U={g_u:.1f}, Z={g_z:.2f}, p={g_p:.2e}, r={g_r:.3f}")
    print()

# ─── BY LOAD CONDITION ─────────────────────────────────────
print("═══ BY LOAD CONDITION ═══")
cond_order = ["Baseline (0g)", "50mm+50g", "50mm+100g", "100mm+50g", "100mm+100g"]
for cond in cond_order:
    cm = manual[manual.apply(
        lambda r: (f"{int(r['arm_len'])}mm+{int(r['discs']*50)}g"
                   if r["arm_len"] > 0 else "Baseline (0g)") == cond, axis=1)]
    ca = advisor[advisor.apply(
        lambda r: (f"{int(r['arm_len'])}mm+{int(r['discs']*50)}g"
                   if r["arm_len"] > 0 else "Baseline (0g)") == cond, axis=1)]
    if len(cm) == 0 or len(ca) == 0:
        continue
    cm_mean = cm["total_time"].mean()
    ca_mean = ca["total_time"].mean()
    c_eta = cm_mean / ca_mean
    c_red = (1 - ca_mean / cm_mean) * 100
    _, c_p = stats.mannwhitneyu(cm["total_time"], ca["total_time"],
                                 alternative="greater")
    print(f"  {cond:20s}  Manual={cm_mean:.1f}s  Advisor={ca_mean:.1f}s  "
          f"η={c_eta:.2f}  Red={c_red:.0f}%  p={c_p:.4f}")
print()

# ─── BY SERVO JOINT ────────────────────────────────────────
print("═══ BY SERVO JOINT ═══")
joint_names = {1: "Base", 2: "Shoulder", 3: "Elbow",
               4: "Wrist-pitch", 5: "Wrist-roll"}
for sid in range(1, 6):
    sm = manual[manual["servo_id"] == sid]
    sa = advisor[advisor["servo_id"] == sid]
    sm_mean = sm["total_time"].mean()
    sa_mean = sa["total_time"].mean()
    s_eta = sm_mean / sa_mean
    s_red = (1 - sa_mean / sm_mean) * 100
    print(f"  Servo {sid} ({joint_names[sid]:12s}):  "
          f"Manual={sm_mean:.1f}s  Advisor={sa_mean:.1f}s  "
          f"η={s_eta:.2f}  Red={s_red:.0f}%")
print()

# ─── SETTLING TIME ──────────────────────────────────────────
# Only valid trials with numeric settling
settling = valid["settling"].copy()
settling_numeric = pd.to_numeric(settling, errors="coerce").dropna()
print("═══ SETTLING TIME ═══")
print(f"  Valid settling values: {len(settling_numeric)}")
print(f"  Range: {settling_numeric.min():.0f}–{settling_numeric.max():.0f}ms")
print(f"  Mean:  {settling_numeric.mean():.0f}ms")
within_750 = (settling_numeric <= 750).sum()
print(f"  Within 750ms: {within_750}/{len(settling_numeric)} "
      f"({within_750/len(settling_numeric)*100:.0f}%)")
print()

# ─── PAIRING STRUCTURE ANALYSIS ─────────────────────────────
print("═══ PAIRING STRUCTURE ═══")
# Check how many unique (servo_id, condition) cells each operator covers
valid_copy = valid.copy()
valid_copy["cell"] = valid_copy.apply(
    lambda r: (r["servo_id"], r["arm_len"], r["discs"]), axis=1)
for op in sorted(valid_copy["op_id"].unique()):
    op_data = valid_copy[valid_copy["op_id"] == op]
    cells_m = set(op_data[op_data["mode"] == "m"]["cell"].unique())
    cells_a = set(op_data[op_data["mode"] == "a"]["cell"].unique())
    print(f"  {op}: {len(cells_m)} manual cells, {len(cells_a)} advisor cells, "
          f"{len(op_data)} total trials")

# Check coverage: how many operators cover each (servo, condition) cell
print("\n  Cell coverage (min operators per cell):")
all_cells = valid_copy.groupby(["servo_id", "arm_len", "discs", "mode"]).agg(
    n_ops=("op_id", "nunique"),
    n_trials=("total_time", "count")
).reset_index()
print(f"  Unique cells: {len(all_cells)}")
print(f"  Min ops per cell: {all_cells['n_ops'].min()}")
print(f"  Max ops per cell: {all_cells['n_ops'].max()}")
print()
print("DONE — All statistics computed from CSV ground truth.")
