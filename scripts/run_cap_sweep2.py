import yaml
import copy
import subprocess
import re
import csv
from pathlib import Path
import matplotlib.pyplot as plt

BASE_FILE = Path("example_config.yaml")
EXP_DIR = Path("experiments/rowpolicy_sweep")
CONFIG_DIR = EXP_DIR / "configs"
OUTPUT_DIR = EXP_DIR / "outputs"
SUMMARY_DIR = EXP_DIR / "summary"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

with open(BASE_FILE, "r") as f:
    base_cfg = yaml.safe_load(f)

# 이번 단계에서는 trace 2개만 사용
TRACE_LIST = [
    "example_inst.trace",
    "example_rh_physaddr.trace",
    "example_prac_attacker.trace",
]

def trace_tag(trace_name: str) -> str:
    # 파일명에서 .trace 제거해서 태그로 사용
    return Path(trace_name).stem

def run_cfg(cfg, yaml_path, out_path):
    with open(yaml_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    subprocess.run(
        f"./ramulator2 -f {yaml_path} > {out_path} 2>&1",
        shell=True,
        check=True
    )

def parse_stat(text, key):
    m = re.search(rf"^\s*{re.escape(key)}:\s*([^\n]+)", text, re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value

def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)

def print_table(rows, columns):
    widths = {}
    for col in columns:
        widths[col] = max(len(col), max(len(fmt(r.get(col))) for r in rows))

    header = " | ".join(col.ljust(widths[col]) for col in columns)
    sep = "-+-".join("-" * widths[col] for col in columns)

    print("\n=== Trace x RowPolicy Sweep Summary ===")
    print(header)
    print(sep)

    for r in rows:
        line = " | ".join(fmt(r.get(col)).ljust(widths[col]) for col in columns)
        print(line)
    print()

# -------------------------------
# 1) 실행: trace x policy x cap
# -------------------------------
for trace_name in TRACE_LIST:
    tag = trace_tag(trace_name)

    # OpenRowPolicy
    open_cfg = copy.deepcopy(base_cfg)
    open_cfg["Frontend"]["traces"] = [trace_name]
    open_cfg["MemorySystem"]["Controller"]["RowPolicy"] = {
        "impl": "OpenRowPolicy"
    }

    run_cfg(
        open_cfg,
        CONFIG_DIR / f"{tag}_openrow.yaml",
        OUTPUT_DIR / f"{tag}_openrow.txt"
    )

    # ClosedRowPolicy cap sweep
    for cap in [1, 2, 4, 8]:
        cfg = copy.deepcopy(base_cfg)
        cfg["Frontend"]["traces"] = [trace_name]
        cfg["MemorySystem"]["Controller"]["RowPolicy"] = {
            "impl": "ClosedRowPolicy",
            "cap": cap
        }

        run_cfg(
            cfg,
            CONFIG_DIR / f"{tag}_closed_cap{cap}.yaml",
            OUTPUT_DIR / f"{tag}_closed_cap{cap}.txt"
        )

# -------------------------------
# 2) 결과 파싱
# -------------------------------
cases = []
for trace_name in TRACE_LIST:
    tag = trace_tag(trace_name)

    cases.append((trace_name, "Open", None, OUTPUT_DIR / f"{tag}_openrow.txt"))
    for cap in [1, 2, 4, 8]:
        cases.append((trace_name, "Closed", cap, OUTPUT_DIR / f"{tag}_closed_cap{cap}.txt"))

rows = []
for trace_name, policy, cap, path in cases:
    text = path.read_text()

    row = {
        "trace": trace_tag(trace_name),
        "policy": policy,
        "cap": "-" if cap is None else cap,
        "num_read_reqs_0": parse_stat(text, "num_read_reqs_0"),
        "avg_read_latency_0": parse_stat(text, "avg_read_latency_0"),
        "row_hits_0": parse_stat(text, "row_hits_0"),
        "row_misses_0": parse_stat(text, "row_misses_0"),
        "row_conflicts_0": parse_stat(text, "row_conflicts_0"),
        "memory_access_cycles_recorded_core_0": parse_stat(text, "memory_access_cycles_recorded_core_0"),
        "cycles_recorded_core_0": parse_stat(text, "cycles_recorded_core_0"),
        "num_close_reqs": parse_stat(text, "num_close_reqs"),
    }
    rows.append(row)

# -------------------------------
# 3) CSV 저장
# -------------------------------
csv_path = SUMMARY_DIR / "trace_rowpolicy_summary.csv"
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

# -------------------------------
# 4) 그래프 저장
# trace별 avg_read_latency 비교
# -------------------------------
for trace_name in TRACE_LIST:
    tag = trace_tag(trace_name)
    subset = [r for r in rows if r["trace"] == tag]

    labels = [f"{r['policy']}-{r['cap']}" for r in subset]

    plt.figure(figsize=(8, 4))
    plt.bar(labels, [r["avg_read_latency_0"] for r in subset])
    plt.ylabel("avg_read_latency_0")
    plt.title(f"{tag}: avg_read_latency")
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(SUMMARY_DIR / f"{tag}_avg_read_latency.png")
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.bar(labels, [r["row_hits_0"] for r in subset])
    plt.ylabel("row_hits_0")
    plt.title(f"{tag}: row_hits")
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(SUMMARY_DIR / f"{tag}_row_hits.png")
    plt.close()

# -------------------------------
# 5) 터미널 표 출력
# -------------------------------
display_rows = []
for r in rows:
    display_rows.append({
        "trace": r["trace"],
        "policy": r["policy"],
        "cap": r["cap"],
        "reads": r["num_read_reqs_0"],
        "row_hits": r["row_hits_0"],
        "row_misses": r["row_misses_0"],
        "row_conflicts": r["row_conflicts_0"],
        "avg_r_lat": r["avg_read_latency_0"],
        "mem_acc_cycles": r["memory_access_cycles_recorded_core_0"],
        "total_cycles": r["cycles_recorded_core_0"],
        "close_reqs": r["num_close_reqs"],
    })

print_table(
    display_rows,
    columns=[
        "trace",
        "policy",
        "cap",
        "reads",
        "row_hits",
        "row_misses",
        "row_conflicts",
        "avg_r_lat",
        "mem_acc_cycles",
        "total_cycles",
        "close_reqs",
    ]
)

print(f"CSV saved to: {csv_path}")
print(f"Plots saved in: {SUMMARY_DIR}")