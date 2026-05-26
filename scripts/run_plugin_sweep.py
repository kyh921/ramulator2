import yaml
import copy
import subprocess
import re
import csv
from pathlib import Path
import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

BASE_FILE = REPO_ROOT / "example_config.yaml"
EXP_DIR = REPO_ROOT / "experiments" / "plugin_sweep"
CONFIG_DIR = EXP_DIR / "configs"
OUTPUT_DIR = EXP_DIR / "outputs"
SUMMARY_DIR = EXP_DIR / "summary"
PLOT_DIR = SUMMARY_DIR / "plots"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
PLOT_DIR.mkdir(parents=True, exist_ok=True)

with open(BASE_FILE, "r") as f:
    base_cfg = yaml.safe_load(f)

TRACE_LIST = [
    "example_inst.trace",
    "example_rh_physaddr.trace",
    "example_prac_attacker.trace",
]

CAP_LIST = [1, 2, 4, 8]
BANK_OPEN_THRESHOLD = 10


def trace_tag(trace_name: str) -> str:
    return Path(trace_name).stem


def run_cfg(cfg, yaml_path, out_path):
    with open(yaml_path, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    subprocess.run(
        f"{REPO_ROOT / 'ramulator2'} -f {yaml_path} > {out_path} 2>&1",
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


def parse_gbank_stats(text):
    """
    num_opening_cmds_gbank0: 12
    num_opening_cmds_gbank1: 0
    ...
    형태를 전부 dict로 추출
    """
    matches = re.findall(r"^\s*num_opening_cmds_gbank(\d+):\s*([^\n]+)", text, re.MULTILINE)
    result = {}
    for idx, value in matches:
        key = f"gbank{idx}"
        try:
            result[key] = int(value.strip())
        except ValueError:
            try:
                result[key] = float(value.strip())
            except ValueError:
                result[key] = value.strip()
    return result


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

    print("\n=== Plugin Sweep Summary ===")
    print(header)
    print(sep)

    for r in rows:
        line = " | ".join(fmt(r.get(col)).ljust(widths[col]) for col in columns)
        print(line)
    print()


def attach_plugin(cfg):
    cfg["MemorySystem"]["Controller"]["plugins"] = [
        {
            "ControllerPlugin": {
                "impl": "ActCounterStats",
                "bank_open_threshold": BANK_OPEN_THRESHOLD
            }
        }
    ]


# ------------------------------------------------
# 1) 실행: trace x policy x cap
# ------------------------------------------------
cases = []

for trace_name in TRACE_LIST:
    tag = trace_tag(trace_name)

    # OpenRowPolicy
    open_cfg = copy.deepcopy(base_cfg)
    open_cfg["Frontend"]["traces"] = [trace_name]
    open_cfg["MemorySystem"]["Controller"]["RowPolicy"] = {
        "impl": "OpenRowPolicy"
    }
    attach_plugin(open_cfg)

    open_yaml = CONFIG_DIR / f"{tag}_openrow.yaml"
    open_out = OUTPUT_DIR / f"{tag}_openrow.txt"

    run_cfg(open_cfg, open_yaml, open_out)
    cases.append((trace_name, "Open", None, open_out))

    # ClosedRowPolicy cap sweep
    for cap in CAP_LIST:
        cfg = copy.deepcopy(base_cfg)
        cfg["Frontend"]["traces"] = [trace_name]
        cfg["MemorySystem"]["Controller"]["RowPolicy"] = {
            "impl": "ClosedRowPolicy",
            "cap": cap
        }
        attach_plugin(cfg)

        yaml_path = CONFIG_DIR / f"{tag}_closed_cap{cap}.yaml"
        out_path = OUTPUT_DIR / f"{tag}_closed_cap{cap}.txt"

        run_cfg(cfg, yaml_path, out_path)
        cases.append((trace_name, "Closed", cap, out_path))


# ------------------------------------------------
# 2) 결과 파싱
# ------------------------------------------------
rows = []
gbank_rows = []

for trace_name, policy, cap, out_path in cases:
    text = out_path.read_text()

    row = {
        "trace": trace_tag(trace_name),
        "policy": policy,
        "cap": "-" if cap is None else cap,
        "reads": parse_stat(text, "num_read_reqs_0"),
        "row_hits": parse_stat(text, "row_hits_0"),
        "row_misses": parse_stat(text, "row_misses_0"),
        "row_conflicts": parse_stat(text, "row_conflicts_0"),
        "read_nonhits": parse_stat(text, "read_row_nonhits_0"),
        "opening_cmds": parse_stat(text, "num_opening_cmds"),
        "hot_bank_events": parse_stat(text, "num_hot_bank_events"),
        "avg_r_lat": parse_stat(text, "avg_read_latency_0"),
        "mem_acc_cycles": parse_stat(text, "memory_access_cycles_recorded_core_0"),
        "total_cycles": parse_stat(text, "cycles_recorded_core_0"),
        "close_reqs": parse_stat(text, "num_close_reqs"),
    }
    rows.append(row)

    gbank_stats = parse_gbank_stats(text)
    gbank_row = {
        "trace": trace_tag(trace_name),
        "policy": policy,
        "cap": "-" if cap is None else cap,
    }
    gbank_row.update(gbank_stats)
    gbank_rows.append(gbank_row)


# ------------------------------------------------
# 3) CSV 저장
# ------------------------------------------------
summary_csv = SUMMARY_DIR / "plugin_summary.csv"
with open(summary_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

# gbank CSV는 key 수가 case마다 같다는 가정
all_gbank_keys = set()
for r in gbank_rows:
    all_gbank_keys.update(r.keys())

# trace/policy/cap이 앞쪽에 오게 정렬
ordered_gbank_keys = ["trace", "policy", "cap"] + sorted(
    [k for k in all_gbank_keys if k not in {"trace", "policy", "cap"}],
    key=lambda x: int(x.replace("gbank", "")) if x.startswith("gbank") else x
)

gbank_csv = SUMMARY_DIR / "plugin_gbank_summary.csv"
with open(gbank_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=ordered_gbank_keys)
    writer.writeheader()
    writer.writerows(gbank_rows)


# ------------------------------------------------
# 4) 간단 표 출력
# ------------------------------------------------
print_table(
    rows,
    columns=[
        "trace",
        "policy",
        "cap",
        "reads",
        "row_hits",
        "row_misses",
        "row_conflicts",
        "read_nonhits",
        "opening_cmds",
        "hot_bank_events",
        "avg_r_lat",
        "close_reqs",
    ]
)


# ------------------------------------------------
# 5) 그래프 저장
# ------------------------------------------------
# (A) trace별 opening_cmds 비교
for trace_name in TRACE_LIST:
    tag = trace_tag(trace_name)
    subset = [r for r in rows if r["trace"] == tag]

    labels = [f"{r['policy']}-{r['cap']}" for r in subset]

    plt.figure(figsize=(8, 4))
    plt.bar(labels, [r["opening_cmds"] for r in subset])
    plt.ylabel("num_opening_cmds")
    plt.title(f"{tag}: opening commands")
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(PLOT_DIR / f"{tag}_opening_cmds.png")
    plt.close()

    plt.figure(figsize=(8, 4))
    plt.bar(labels, [r["hot_bank_events"] for r in subset])
    plt.ylabel("num_hot_bank_events")
    plt.title(f"{tag}: hot bank events")
    plt.xticks(rotation=30)
    plt.tight_layout()
    plt.savefig(PLOT_DIR / f"{tag}_hot_bank_events.png")
    plt.close()


# (B) case별 gbank bar chart 저장
for gbank_row in gbank_rows:
    trace = gbank_row["trace"]
    policy = gbank_row["policy"]
    cap = gbank_row["cap"]

    gbank_items = [(k, v) for k, v in gbank_row.items() if k.startswith("gbank")]
    gbank_items.sort(key=lambda x: int(x[0].replace("gbank", "")))

    labels = [k for k, _ in gbank_items]
    values = [v for _, v in gbank_items]

    plt.figure(figsize=(12, 4))
    plt.bar(labels, values)
    plt.ylabel("opening count")
    plt.title(f"{trace} | {policy} | cap={cap} | gbank opening distribution")
    plt.xticks(rotation=90)
    plt.tight_layout()
    plt.savefig(PLOT_DIR / f"{trace}_{policy}_cap{cap}_gbank_dist.png")
    plt.close()


print(f"Summary CSV saved to: {summary_csv}")
print(f"GBank CSV saved to:   {gbank_csv}")
print(f"Plots saved in:       {PLOT_DIR}")