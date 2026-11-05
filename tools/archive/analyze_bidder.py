#!/usr/bin/env python3
"""
竞拍成功率分析工具。

用户输入自己的摇号次数和注册时间，工具会：
1. 在当前最新期次 (2400) 中算出用户的排名
2. 遍历所有历史中拍记录，找出每期中排名 ±10 以内的人中了什么车
3. 按价格 5万/档 给出成功率和车型举例

用法:
  python3 tools/analyze_bidder.py --times 85 --reg_time "2011-01-17 08: 51: 18. 077"

注册时间格式: "2011-01-17 08: 51: 18. 077"（冒号后带空格，与 CSV 一致）
"""

import os
import csv
import sys
import argparse
import math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")

GSXX_CURRENT = os.path.join(DOWNLOADS_DIR, "2400", "gsxx_2400.csv")
WINNER_PROFILES = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")
RANK_WINDOW = 10  # ±10 排名窗口（在 2400 期中的绝对排名范围）


def parse_reg_time(rt):
    """解析 reg_time 为可排序的元组 (日期, 规范化时间)"""
    rt = rt.strip()
    parts = rt.split()
    date_part = parts[0] if parts else ""
    time_part = parts[1] if len(parts) > 1 else "00: 00: 00. 000"
    time_clean = time_part.replace(": ", ":").replace(". ", ".")
    return date_part, time_clean


def compute_rank(times, reg_time, gsxx_path):
    """
    在 gsxx CSV 中计算给定用户会排第几。
    排名规则: (times DESC, reg_time ASC)
    返回 (rank, total_bidders)
    """
    rows = []
    with open(gsxx_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return None, 0

    total = len(rows)
    user_times = int(times)
    user_key = parse_reg_time(reg_time)

    # 统计有多少人比用户更强
    # 更强 = times 更大, 或 times 相同且 reg_time 更早
    better = 0
    for r in rows:
        rt = int(r["times"])
        rr = parse_reg_time(r["reg_time"])
        if rt > user_times or (rt == user_times and rr < user_key):
            better += 1

    return better + 1, total


def bracket_sort_key(bracket_str):
    """按分档起始金额排序，如 '5-10万' -> 5"""
    try:
        return int(bracket_str.split("-")[0])
    except (ValueError, IndexError):
        return 9999


def main():
    parser = argparse.ArgumentParser(description="竞拍成功率分析工具")
    parser.add_argument("--times", required=True, help="用户当前摇号次数 (如 85)")
    parser.add_argument(
        "--reg_time",
        required=True,
        help="用户注册时间，格式: '2011-01-17 08: 51: 18. 077'",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=RANK_WINDOW,
        help=f"排名窗口大小 (默认 {RANK_WINDOW})",
    )
    args = parser.parse_args()

    # ── Step 1: 计算用户在 2400 期的排名 ──
    print("=" * 72)
    print("  竞拍成功率分析")
    print("=" * 72)

    print(f"\n用户信息: 次数={args.times}, 注册时间={args.reg_time}")

    rank, total = compute_rank(args.times, args.reg_time, GSXX_CURRENT)
    if rank is None:
        print("\n错误: gsxx_2400.csv 不存在或为空")
        sys.exit(1)

    window = args.window
    low_abs = max(1, rank - window)
    high_abs = rank + window
    user_pct = rank / total * 100
    pct_low = math.floor(low_abs / total * 100)
    pct_high = math.ceil(high_abs / total * 100)

    print(f"\n在 2400 期 (最近期次) 中的排名: {rank} / {total}")
    print(f"  即前 {user_pct:.2f}%")
    print(f"排名窗口 (±{window} 绝对排名):")
    print(f"  绝对排名: {low_abs} ~ {high_abs}")
    print(f"  百分比区间: {pct_low}% ~ {pct_high}% (n向下取整, m向上取整)")

    if not os.path.exists(WINNER_PROFILES):
        print(f"\n错误: {WINNER_PROFILES} 不存在，请先运行 tools/build_winner_profiles.py")
        sys.exit(1)

    winners = []
    with open(WINNER_PROFILES, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            winners.append(row)

    print(f"\n历史中拍记录总数: {len(winners)}")

    bracket_data = {}
    for w in winners:
        bracket = w["price_bracket"]
        if bracket not in bracket_data:
            bracket_data[bracket] = {"total": 0, "matched": []}
        bracket_data[bracket]["total"] += 1

        w_pct = int(w["winner_rank"]) / int(w["total_bidders"]) * 100
        if pct_low <= w_pct <= pct_high:
            bracket_data[bracket]["matched"].append(w)

    # ── Step 4: 输出 ──
    print(f"\n{'=' * 72}")
    print(f"  按价格区间分析 (历史中拍排名百分比在 {pct_low}%~{pct_high}% 内的)")
    print(f"{'=' * 72}")

    has_any_match = any(d["matched"] for d in bracket_data.values())

    if not has_any_match:
        print(f"\n  (无百分比排名在窗口内的历史中拍记录)")
    else:
        print(
            f"  {'价格区间':<12} {'总数':>6} {'窗口内':>6} {'成功率':>8}  {'车型举例'}"
        )
        print(f"  {'-' * 72}")

        for bracket in sorted(bracket_data.keys(), key=bracket_sort_key):
            d = bracket_data[bracket]
            total_b = d["total"]
            matched = d["matched"]
            rate = len(matched) / total_b * 100 if total_b > 0 else 0

            example = ""
            if matched:
                # 取百分比最接近的一条作为例子
                best = min(matched, key=lambda x: abs(
                    int(x["winner_rank"]) / int(x["total_bidders"]) * 100 - user_pct
                ))
                example = best["car_name"]

            print(
                f"  {bracket:<12} {total_b:>6} {len(matched):>6} {rate:>7.1f}%  {example}"
            )

    # ── Step 5: 详情列表 ──
    print(f"\n{'=' * 72}")
    print(f"  推荐竞价车型详情 (排名百分比 {pct_low}%~{pct_high}% 内的历史中拍)")
    print(f"{'=' * 72}")

    any_detail = False
    for bracket in sorted(bracket_data.keys(), key=bracket_sort_key):
        d = bracket_data[bracket]
        matched = d["matched"]
        if not matched:
            continue

        any_detail = True
        # 按百分比接近度排序
        matched.sort(key=lambda x: abs(
            int(x["winner_rank"]) / int(x["total_bidders"]) * 100 - user_pct
        ))

        print(f"\n  [{bracket}] — {len(matched)} 辆 / 共 {d['total']} 辆")
        print(f"  {'-' * 68}")
        for m in matched[:5]:
            r_pct = int(m["winner_rank"]) / int(m["total_bidders"]) * 100
            print(f"    {m['car_name']}")
            print(f"    起拍价: {m['start_price']} 元")
            print(f"    成交价: {m['final_price']} 元")
            print(f"    当时排名: {m['winner_rank']}/{m['total_bidders']} (前{r_pct:.2f}%, {m['result_zcid']}期)")
            print(f"    链接: {m['car_link']}")
            print()

    if not any_detail:
        print(f"\n  (无符合条件的历史记录)")

    # ── 总结 ──
    print(f"{'=' * 72}")
    total_all = sum(d["total"] for d in bracket_data.values())
    total_matched = sum(len(d["matched"]) for d in bracket_data.values())
    print(f"  总结:")
    print(f"    历史中拍总记录:   {total_all}")
    print(f"    排名窗口内:       {total_matched}")
    print(f"    全局成功率:       {total_matched / total_all * 100:.1f}%" if total_all > 0 else "    N/A")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
