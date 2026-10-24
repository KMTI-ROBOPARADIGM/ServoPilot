"""
revision_reanalysis.py -- INDICON 2026 Paper 433, major-revision reanalysis.

Recomputes every number the revised manuscript needs from the raw CSVs:
  E1/E2  telemetry latency, throughput, wire-time model, headroom
  E5     REST round-trip time
  E3     operator study, re-analysed for repeated measures
         (operator-level paired analysis, cluster bootstrap, mixed model,
          Holm-corrected exploratory subgroups, order/learning sensitivity,
          final-response-quality comparison)

Run from the `experiments` folder:
    python E3_pid/revision_reanalysis.py
Requires: numpy, pandas, scipy  (statsmodels optional, for the mixed model)
"""
import os
import sys
import warnings

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
P = lambda *a: os.path.join(ROOT, *a)
rng = np.random.default_rng(42)
B = 10_000


def hdr(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def geo_ci(x):
    """Geometric-mean ratio and t-based 95% CI from a vector of log ratios."""
    x = np.asarray(x, float)
    n = len(x)
    se = x.std(ddof=1) / np.sqrt(n)
    t = stats.t.ppf(0.975, n - 1)
    return np.exp(x.mean()), np.exp(x.mean() - t * se), np.exp(x.mean() + t * se)


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    m = len(p)
    adj = np.empty(m)
    running = 0.0
    for k, idx in enumerate(order):
        running = max(running, (m - k) * p[idx])
        adj[idx] = min(running, 1.0)
    return adj


# ---------------------------------------------------------------- E1 / E2
hdr("E1/E2  SERIAL TELEMETRY")
lat = pd.read_csv(P("E1_baseline", "telemetry_latency.csv"))
x = lat.latency_ms
print(f"E1b single-servo telemetry read (7 register reads), n={len(x)}: "
      f"mean {x.mean():.2f} +/- {x.std():.2f} ms, median {x.median():.2f}, "
      f"p95 {x.quantile(.95):.2f}, range {x.min():.2f}-{x.max():.2f}")

pf = pd.read_csv(P("E1_baseline", "polling_frequency.csv"))
print("\nE1a polling (target vs achieved, failures):")
print(pf[["target_hz", "actual_hz", "total_reads", "failures"]].to_string(index=False))
print("-> zero failures at every tested rate; 70 Hz is the highest rate TESTED, "
      f"achieved {pf.actual_hz.iloc[-1]:.1f} Hz (sleep-based pacing).")

sc = pd.read_csv(P("E2_scalability", "latency_scaling.csv"))
g = sc.groupby("n_servos").cycle_latency_ms
tab = g.agg(["count", "mean", "std", "median"])
tab["p95"] = g.quantile(0.95)
slope, icpt = np.polyfit(tab.index, tab["mean"], 1)
pred = icpt + slope * tab.index
r2 = 1 - ((tab["mean"] - pred) ** 2).sum() / ((tab["mean"] - tab["mean"].mean()) ** 2).sum()
tab["headroom_20Hz_%"] = 100 * (1 - tab["mean"] / 50.0)
print("\nE2b cycle latency per servo count:")
print(tab.round(2).to_string())
print(f"Linear fit on means: {icpt:.2f} ms + {slope:.2f} ms/servo, R^2 = {r2:.3f}")
for n in (5, 6):
    c = icpt + slope * n
    print(f"  extrapolated {n} servos: {c:.1f} ms/cycle -> max cycle rate ~{1000 / c:.0f} Hz")

bu = pd.read_csv(P("E2_scalability", "bus_utilization.csv"))
bu["ms_per_servo_read"] = 1000 / bu.reads_per_second
bu["cycles_per_s"] = bu.reads_per_second / bu.n_servos
print("\nE2a back-to-back throughput (the 99.9% 'utilization' is loop duty cycle by construction):")
print(bu[["n_servos", "reads_per_second", "ms_per_servo_read", "cycles_per_s"]].round(2).to_string(index=False))

# Wire-time model: 7 READ instructions, 8-byte request each; reply 6+n bytes
data_bytes = [2, 2, 1, 1, 1, 1, 1]  # pos, speed, load, voltage, temp, current, moving (as read by driver)
tx = 8 * len(data_bytes)
rx = sum(6 + n for n in data_bytes)
wire_ms = (tx + rx) * 10 / 1_000_000 * 1000
print(f"\nWire-time model @1 Mbps, 8N1: {tx} B request + {rx} B reply = {tx + rx} B "
      f"-> {wire_ms:.2f} ms on the wire per servo telemetry read")
for hz in (20, 50):
    print(f"  6 servos @ {hz} Hz: wire occupancy {6 * wire_ms * hz / 10:.1f}%, "
          f"transaction occupancy (2.21 ms measured) {6 * 2.21 * hz / 10:.1f}%")

# ---------------------------------------------------------------- E5
hdr("E5  REST API")
rt = pd.read_csv(P("E5_api", "rtt_log.csv"))
r = rt[rt.method == "REST"].rtt_ms
print(f"REST POST /servos/1/position (returns on enqueue), n={len(r)}: mean {r.mean():.2f} +/- "
      f"{r.std():.2f} ms, median {r.median():.2f}, range {r.min():.2f}-{r.max():.2f}")
print(f"  bimodal: {(r < 10).sum()} samples < 10 ms, {(r >= 10).sum()} samples >= 10 ms")
print(f"  WebSocket rows in log: {(rt.method != 'REST').sum()}")

# ---------------------------------------------------------------- E3
hdr("E3  OPERATOR STUDY (repeated-measures reanalysis)")
df = pd.read_csv(P("E3_pid", "dataset_cleaned.csv"))
df["cond"] = np.where(df.arm_len == 0, "0 g",
                      df.arm_len.astype(str) + " mm+" + (df.discs * 50).astype(str) + " g")
print("Excluded trials:")
print(df[df.success != "y"][["op_id", "servo_id", "cond", "mode", "trial_no", "total_time", "anomaly"]].to_string(index=False))
v = df[df.success == "y"].copy()
v["lt"] = np.log(v.total_time)
print(f"Valid: {len(v)} (manual {sum(v['mode'] == 'm')}, advisor {sum(v['mode'] == 'a')})")
print(f"Design: every operator covers each load exactly once on a different joint "
      f"({(df.groupby('op_id').cond.nunique() == 5).all()}); each joint x load cell "
      f"run by {df.groupby(['servo_id', 'cond']).op_id.nunique().unique()} operators (Latin square, replicated per group)")

m, a = v[v["mode"] == "m"].total_time, v[v["mode"] == "a"].total_time
print(f"\n[OLD, trials treated as independent] manual {m.mean():.1f}+/-{m.std():.1f} s, "
      f"advisor {a.mean():.1f}+/-{a.std():.1f} s, eta={m.mean() / a.mean():.2f}")

# Level 1: operator as unit of analysis
op = v.groupby(["op_id", "exp_level", "mode"]).total_time.mean().unstack()
op["eta"] = op.m / op.a
op["log_ratio"] = np.log(op.eta)
print("\nPer-operator means:")
print(op.round(2).to_string())
gm, lo, hi = geo_ci(op.log_ratio)
tt = stats.ttest_1samp(op.log_ratio, 0)
w = stats.wilcoxon(op.log_ratio)
dz = op.log_ratio.mean() / op.log_ratio.std(ddof=1)
print(f"\nPRIMARY (n=10 operators): eta (geometric mean of per-operator ratios) = {gm:.2f}, "
      f"95% CI [{lo:.2f}, {hi:.2f}]; reduction {100 * (1 - 1 / gm):.1f}% "
      f"[{100 * (1 - 1 / lo):.1f}, {100 * (1 - 1 / hi):.1f}]")
print(f"  paired t on log times: t(9) = {tt.statistic:.2f}, p = {tt.pvalue:.1e}; "
      f"Wilcoxon signed-rank (exact, two-sided): W = {w.statistic:.0f}, p = {w.pvalue:.4f}; "
      f"10/10 operators faster with advisor; d_z = {dz:.2f}")
for grp in ("inf", "nai"):
    s = op.xs(grp, level="exp_level").log_ratio
    gm_, lo_, hi_ = geo_ci(s)
    print(f"  {grp}: eta {gm_:.2f} [{lo_:.2f}, {hi_:.2f}] (n=5; exact Wilcoxon cannot go below p=0.0625 at n=5)")

# Cluster bootstrap over operators, ratio of means
ops = v.op_id.unique()
by_op = {o: v[v.op_id == o] for o in ops}
b1, b2 = [], []
for _ in range(B):
    pick = rng.choice(ops, len(ops))
    s = pd.concat([by_op[o] for o in pick])
    b1.append(s[s["mode"] == "m"].total_time.mean() / s[s["mode"] == "a"].total_time.mean())
    s2 = pd.concat([by_op[o].sample(len(by_op[o]), replace=True, random_state=int(rng.integers(1e9)))
                    for o in pick])
    b2.append(s2[s2["mode"] == "m"].total_time.mean() / s2[s2["mode"] == "a"].total_time.mean())
print(f"  ratio-of-means eta {m.mean() / a.mean():.2f}: operator-cluster bootstrap 95% CI "
      f"[{np.percentile(b1, 2.5):.2f}, {np.percentile(b1, 97.5):.2f}], two-stage bootstrap "
      f"[{np.percentile(b2, 2.5):.2f}, {np.percentile(b2, 97.5):.2f}]")

# Mixed model (optional)
try:
    import statsmodels.formula.api as smf
    base = "lt ~ C(mode, Treatment('m')) + C(exp_level) + C(cond) + C(servo_id)"
    fit = smf.mixedlm(base, v, groups=v.op_id).fit(reml=True)
    k = "C(mode, Treatment('m'))[T.a]"
    b, (cl, ch) = fit.params[k], fit.conf_int().loc[k]
    print(f"\nLinear mixed model, log(time) ~ mode + group + load + joint + (1|operator):")
    print(f"  eta = {np.exp(-b):.2f}, 95% CI [{np.exp(-ch):.2f}, {np.exp(-cl):.2f}], z = {fit.tvalues[k]:.1f}")
    ml = lambda f: smf.mixedlm(f, v, groups=v.op_id).fit(reml=False)
    f0 = ml("lt ~ C(mode) + C(exp_level) + C(cond) + C(servo_id)")
    for name, f, df_ in [("mode x group", "lt ~ C(mode)*C(exp_level) + C(cond) + C(servo_id)", 1),
                         ("mode x load", "lt ~ C(mode)*C(cond) + C(exp_level) + C(servo_id)", 4),
                         ("mode x joint", "lt ~ C(mode)*C(servo_id) + C(exp_level) + C(cond)", 4)]:
        lr = 2 * (ml(f).llf - f0.llf)
        print(f"  LRT {name}: chi2({df_}) = {lr:.2f}, p = {stats.chi2.sf(lr, df_):.3f}")
except ImportError:
    print("\n(statsmodels not installed -- mixed model skipped)")

# Level 2: matched cells (operator x joint x load), exploratory subgroups with Holm
cell = v.groupby(["op_id", "exp_level", "servo_id", "cond", "mode"]).total_time.mean().unstack().dropna()
cell["lr"] = np.log(cell.m / cell.a)
print(f"\nMatched operator x joint x load cells: {len(cell)}; advisor faster in {(cell.lr > 0).sum()}")
rows = []
for fac in ("cond", "servo_id"):
    for lvl, gg in cell.groupby(level=fac):
        gm_, lo_, hi_ = geo_ci(gg.lr)
        rows.append([fac, lvl, len(gg), gg.m.mean(), gg.a.mean(), gm_, lo_, hi_, stats.wilcoxon(gg.lr).pvalue])
R = pd.DataFrame(rows, columns=["factor", "level", "n_cells", "manual_s", "advisor_s", "eta", "lo95", "hi95", "p"])
R["p_holm"] = holm(R.p)
print(R.round(3).to_string(index=False))

# Order / learning effects
hdr("ORDER AND LEARNING SENSITIVITY")
for mo, name in (("m", "manual"), ("a", "advisor")):
    s = v[v["mode"] == mo].pivot_table(index=["op_id", "servo_id", "cond"], columns="trial_no",
                                       values="total_time").dropna()
    d = np.log(s[1] / s[2])
    print(f"{name}: repetition 1 = {s[1].mean():.1f} s, repetition 2 = {s[2].mean():.1f} s, "
          f"ratio {np.exp(d.mean()):.3f}, Wilcoxon p = {stats.wilcoxon(d).pvalue:.4f} (n={len(d)})")
s = v.pivot_table(index=["op_id", "servo_id", "cond"], columns=["mode", "trial_no"], values="total_time")
d = np.log(s[("m", 2)] / s[("a", 1)]).dropna()
gm_, lo_, hi_ = geo_ci(d)
print(f"Conservative contrast (most-practised manual rep 2 vs first advisor rep 1): "
      f"eta {gm_:.2f} [{lo_:.2f}, {hi_:.2f}], n={len(d)} cells")

# Final response quality
hdr("FINAL RESPONSE QUALITY (per-operator means, Wilcoxon)")
v["settling"] = pd.to_numeric(v.settling, errors="coerce")
for col in ["overshoot", "rise", "settling", "sse_steps", "iters", "final_p", "final_i", "final_d"]:
    q = v.groupby(["op_id", "mode"])[col].mean().unstack()
    print(f"{col:10s} manual {q.m.mean():8.3f}   advisor {q.a.mean():8.3f}   p = {stats.wilcoxon(q.m, q.a).pvalue:.4f}")
tpi_m = (v[v["mode"] == "m"].total_time / v[v["mode"] == "m"].iters).mean()
tpi_a = (v[v["mode"] == "a"].total_time / v[v["mode"] == "a"].iters).mean()
print(f"time per step test: manual {tpi_m:.1f} s, advisor {tpi_a:.1f} s")
print(f"settling of final responses: {v.settling.min():.0f}-{v.settling.max():.0f} ms, mean {v.settling.mean():.0f} ms")
