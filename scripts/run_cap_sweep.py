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
    # 각 컬럼 폭 계산
    widths = {}
    for col in columns:
        widths[col] = max(len(col), max(len(fmt(r.get(col))) for r in rows))

    # 헤더
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    sep = "-+-".join("-" * widths[col] for col in columns)

    print("\n=== RowPolicy Sweep Summary ===")
    print(header)
    print(sep)

    # 행 출력
    for r in rows:
        line = " | ".join(fmt(r.get(col)).ljust(widths[col]) for col in columns)
        print(line)
    print()

# 1) OpenRowPolicy 실행
open_cfg = copy.deepcopy(base_cfg)
open_cfg["MemorySystem"]["Controller"]["RowPolicy"] = {
    "impl": "OpenRowPolicy"
}

run_cfg(
    open_cfg,
    CONFIG_DIR / "openrow.yaml",
    OUTPUT_DIR / "openrow.txt"
)

# 2) ClosedRowPolicy cap sweep 실행
for cap in [1, 2, 4, 8]:
    cfg = copy.deepcopy(base_cfg)
    cfg["MemorySystem"]["Controller"]["RowPolicy"] = {
        "impl": "ClosedRowPolicy",
        "cap": cap
    }

    run_cfg(
        cfg,
        CONFIG_DIR / f"closed_cap{cap}.yaml",
        OUTPUT_DIR / f"closed_cap{cap}.txt"
    )

# 3) 결과 파싱
cases = [
    ("Open", None, OUTPUT_DIR / "openrow.txt"),
    ("Closed", 1, OUTPUT_DIR / "closed_cap1.txt"),
    ("Closed", 2, OUTPUT_DIR / "closed_cap2.txt"),
    ("Closed", 4, OUTPUT_DIR / "closed_cap4.txt"),
    ("Closed", 8, OUTPUT_DIR / "closed_cap8.txt"),
]

rows = []
for policy, cap, path in cases:
    text = path.read_text()

    row = {
        "policy": policy,
        "cap": "-" if cap is None else cap,
        "avg_read_latency_0": parse_stat(text, "avg_read_latency_0"),
        "row_hits_0": parse_stat(text, "row_hits_0"),
        "row_misses_0": parse_stat(text, "row_misses_0"),
        "row_conflicts_0": parse_stat(text, "row_conflicts_0"),
        "memory_access_cycles_recorded_core_0": parse_stat(text, "memory_access_cycles_recorded_core_0"),
        "cycles_recorded_core_0": parse_stat(text, "cycles_recorded_core_0"),
        "num_close_reqs": parse_stat(text, "num_close_reqs"),
    }
    rows.append(row)

# 4) CSV 저장
csv_path = SUMMARY_DIR / "rowpolicy_summary.csv"
with open(csv_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

# 5) 그래프 저장
labels = [f"{r['policy']}-{r['cap']}" for r in rows]

plt.figure(figsize=(8, 4))
plt.bar(labels, [r["avg_read_latency_0"] for r in rows])
plt.ylabel("avg_read_latency_0")
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(SUMMARY_DIR / "avg_read_latency.png")
plt.close()

plt.figure(figsize=(8, 4))
plt.bar(labels, [r["row_hits_0"] for r in rows])
plt.ylabel("row_hits_0")
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(SUMMARY_DIR / "row_hits.png")
plt.close()

plt.figure(figsize=(8, 4))
plt.bar(labels, [0 if r["num_close_reqs"] is None else r["num_close_reqs"] for r in rows])
plt.ylabel("num_close_reqs")
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(SUMMARY_DIR / "num_close_reqs.png")
plt.close()

# 6) 터미널 표 출력
display_rows = []
for r in rows:
    display_rows.append({
        "policy": r["policy"],
        "cap": r["cap"],
        "row_hits": r["row_hits_0"],
        "row_misses": r["row_misses_0"],
        "row_conflicts": r["row_conflicts_0"],
        "avg_r_latency": r["avg_read_latency_0"],
        "mem_acc_cycles": r["memory_access_cycles_recorded_core_0"],
        "total_cycles": r["cycles_recorded_core_0"],
        "close_reqs": r["num_close_reqs"],
    })

print_table(
    display_rows,
    columns=[
        "policy",
        "cap",
        "row_hits",
        "row_misses",
        "row_conflicts",
        "avg_r_latency",
        "mem_acc_cycles",
        "total_cycles",
        "close_reqs",
    ]
)

print(f"CSV saved to: {csv_path}")
print(f"Plots saved in: {SUMMARY_DIR}")