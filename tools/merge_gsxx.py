#!/usr/bin/env python3
"""
合并所有期次的 gsxx CSV、去重、计算 latest_times。

用法:
  python3 tools/merge_gsxx.py                # 合并所有已有 CSV
  python3 tools/merge_gsxx.py --out FILE     # 指定输出路径

去重策略: 按摇号编码前9位去重，保留 zcid 最大（最新期次）的记录

输出列: full_code, prefix, times, latest_times, reg_time, zcid, period
  - latest_times = times + 从该期次到今天经过的6月和12月个数
"""

import os
import sys
import re
import csv
import argparse
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def get_known_zcids():
    return sorted([int(d) for d in os.listdir(DOWNLOADS_DIR) if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))])


KNOWN_ZCIDS = get_known_zcids()

PERIOD_NAMES = {
    2400: "202606期", 2238: "202512期", 2041: "202506期",
    1897: "202411期", 1694: "202402期", 1609: "202310期",
    1533: "202306期", 1417: "202302期", 1064: "202211期",
    725: "202206期", 640: "202202期", 532: "202111期",
    413: "202106期", 378: "202102期", 331: "202011期",
}

TODAY = date.today()


def compute_latest_times(times_str, period_str):
    """
    times 加上从该期次到今日之间经过的 6.26 和 12.26 事件个数。
    例: 202402期, today=2026-07-13, 经过 2024-6-26 2024-12-26 2025-6-26 2025-12-26 2026-6-26 → +5
    """
    times = int(times_str)
    m = re.search(r'(\d{4})(\d{2})', period_str)
    if not m:
        return times
    py, pm = int(m.group(1)), int(m.group(2))
    period_date = date(py, pm, 1)
    extra = 0
    for y in range(py, TODAY.year + 1):
        for month, day in ((6, 26), (12, 26)):
            event = date(y, month, day)
            if event > period_date and event <= TODAY:
                extra += 1
    return times + extra


def read_gsxx_csv(zcid):
    csv_path = os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.csv")
    if not os.path.exists(csv_path):
        return None, f"gsxx_{zcid}.csv 不存在，跳过"
    records = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['zcid'] = str(zcid)
            row['period'] = PERIOD_NAMES.get(zcid, f"zcid={zcid}")
            records.append(row)
    return records, None


def merge_all():
    all_records = []
    stats = {}
    for zcid in KNOWN_ZCIDS:
        records, err = read_gsxx_csv(zcid)
        if err:
            print(f"  [{PERIOD_NAMES.get(zcid, zcid)}] ⚠ {err}")
            continue
        all_records.extend(records)
        stats[str(zcid)] = len(records)
        print(f"  [{PERIOD_NAMES.get(zcid, zcid)}] ✓ {len(records)} 条")
    return all_records, stats


def dedup(records):
    """按 prefix 去重，仅跨期去重（保留 zcid 最大的记录）。

    同一期次内 prefix 重复是**不同的申请人**（9 位前缀相同的不同摇号编码，
    如 full_code 尾部被掩码为 **** 的两条记录），必须全部保留。
    只有跨期（不同 zcid）的 prefix 相同才视为同一人，保留最新期次。
    两遍扫描 O(n)：先求每个 prefix 的最高 zcid，再过滤保留该期次全部记录。"""
    max_zcid = {}
    for r in records:
        p = r['prefix']
        z = int(r['zcid'])
        if z > max_zcid.get(p, 0):
            max_zcid[p] = z
    return [r for r in records if int(r['zcid']) == max_zcid.get(r['prefix'], 0)]


def main():
    parser = argparse.ArgumentParser(description="合并所有 gsxx CSV 并去重")
    parser.add_argument("--out", default=None,
                        help="输出路径，默认 downloads/merged_gsxx.csv")
    args = parser.parse_args()

    print("合并 gsxx CSV 文件...\n")
    records, stats = merge_all()

    if not records:
        print("\n错误: 没有任何 CSV 可合并。请先运行 tools/parse_gsxx.py all")
        sys.exit(1)

    total_all = len(records)
    print(f"\n合并前总计: {total_all} 条")

    # 先去重
    before_dedup = len(records)
    deduped = dedup(records)
    after_dedup = len(deduped)
    print(f"按 prefix 去重 (保留 zcid 最大):")
    print(f"  去重后: {after_dedup} 条 (去掉 {before_dedup - after_dedup} 条重复)")

    # 再计算 latest_times
    for r in deduped:
        r['latest_times'] = compute_latest_times(r['times'], r['period'])

    # 按期次统计
    print(f"\n按期次统计:")
    print(f"  {'期次':<12} {'条数':>6}")
    for zcid in KNOWN_ZCIDS:
        count = stats.get(str(zcid), 0)
        if count:
            print(f"  {PERIOD_NAMES.get(zcid, str(zcid)):<12} {count:>6}")
    print(f"  {'合计':<12} {total_all:>6}")

    # 输出
    out_path = args.out or os.path.join(DOWNLOADS_DIR, "merged_gsxx.csv")
    fieldnames = ['full_code', 'prefix', 'times', 'latest_times', 'reg_time', 'zcid', 'period']
    with open(out_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(deduped)

    print(f"\n✓ 输出: {out_path}")
    print(f"  {after_dedup} 条唯一的摇号编码 (latest_times 已计算)")


if __name__ == "__main__":
    main()
