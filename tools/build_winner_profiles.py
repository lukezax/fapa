#!/usr/bin/env python3
"""
对每一条中拍记录，找到该中拍人在其赢得期次内当时的排名、次数和注册时间。
输出: downloads/winner_profiles.csv
"""

import os
import csv
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
COMBINED_PATH = os.path.join(DOWNLOADS_DIR, "combined.csv")
OUTPUT_PATH = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")


def parse_reg_time(rt):
    """解析 reg_time 为可排序的元组 (日期, 规范化时间)"""
    rt = rt.strip()
    parts = rt.split()
    date_part = parts[0] if parts else ""
    time_part = parts[1] if len(parts) > 1 else "00: 00: 00. 000"
    # 去掉冒号后的空格，使得时间字符串可直接按字典序比较
    time_clean = time_part.replace(": ", ":").replace(". ", ".")
    return date_part, time_clean


def price_bracket(limit_price_str):
    """将顶格价（最高限价／实际成交价）映射到 5 万元档位。

    口径说明：档位一律按顶格价划分，与小程序出价口径（直接顶格）一致。
    历史数据显示成交价恒为起拍价 ×1.5（5406/5407 条），故起拍价口径会整体偏低约一档。
    """
    try:
        price = float(limit_price_str)
    except (ValueError, TypeError):
        return "未知"
    bracket_start = int(price // 50000) * 50000
    return f"{bracket_start // 10000}-{bracket_start // 10000 + 5}万"


def load_and_rank_gsxx(zcid):
    """
    读取 gsxx_{zcid}.csv，按 (times DESC, reg_time ASC) 排序，
    返回: (prefix -> (rank, times, reg_time) 字典, 总人数)
    """
    gsxx_path = os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.csv")
    if not os.path.exists(gsxx_path):
        return None, 0

    rows = []
    with open(gsxx_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return None, 0

    # 按 (次数降序, 注册时间升序) 排序
    rows.sort(key=lambda r: (-int(r["times"]), parse_reg_time(r["reg_time"])))

    # 构建 prefix -> (rank, times, reg_time) 索引
    # 同一个期次内极少数 prefix 重复（见备注），只保留第一条
    idx = {}
    for i, r in enumerate(rows):
        p = r["prefix"]
        if p not in idx:
            idx[p] = (i + 1, r["times"], r["reg_time"])

    return idx, len(rows)


def main():
    print("读取 combined.csv 中拍记录...")
    winners = []
    with open(COMBINED_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rz = row.get("result_zcid", "").strip()
            if rz:
                winners.append(row)

    print(f"  中拍记录总数: {len(winners)}")
    if not winners:
        print("  没有找到中拍记录，退出")
        sys.exit(0)

    # 按 result_zcid 分组，同一个期次的 gsxx 只加载排序一次
    by_period = defaultdict(list)
    for w in winners:
        by_period[w["result_zcid"]].append(w)

    print(f"  涉及期次: {sorted(by_period.keys(), key=int)}\n")

    output_rows = []
    stats_found = 0
    stats_not_found = 0
    stats_period_errors = 0

    for result_zcid in sorted(by_period.keys(), key=int):
        group = by_period[result_zcid]
        idx, total = load_and_rank_gsxx(result_zcid)
        if idx is None:
            print(f"  ⚠  跳过期次 {result_zcid}（gsxx 文件不存在或为空），{len(group)} 条记录无法处理")
            stats_period_errors += len(group)
            continue

        for w in group:
            prefix = w["prefix"]
            start_price = w.get("start_price", "0")
            # 顶格价 = 实际成交价（历史恒为起拍价 ×1.5）；缺失时按 1.5 兜底
            final_price = (w.get("final_price") or "").strip()
            limit_price = final_price
            if not limit_price:
                try:
                    limit_price = f"{float(start_price) * 1.5:.2f}"
                except (ValueError, TypeError):
                    limit_price = ""
            bracket = price_bracket(limit_price)

            if prefix in idx:
                rank, winner_times, winner_reg_time = idx[prefix]
                output_rows.append({
                    "prefix": prefix,
                    "result_zcid": result_zcid,
                    "car_name": w.get("car_name", ""),
                    "car_link": w.get("car_link", ""),
                    "start_price": start_price,
                    "final_price": w.get("final_price", ""),
                    "limit_price": limit_price,
                    "price_bracket": bracket,
                    "winner_times": winner_times,
                    "winner_reg_time": winner_reg_time,
                    "winner_rank": rank,
                    "total_bidders": total,
                })
                stats_found += 1
            else:
                stats_not_found += 1

    # 写入输出
    fieldnames = [
        "prefix", "result_zcid", "car_name", "car_link",
        "start_price", "final_price", "limit_price", "price_bracket",
        "winner_times", "winner_reg_time", "winner_rank", "total_bidders",
    ]
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\n结果统计:")
    print(f"  找到中拍排名 (写入文件): {stats_found}")
    print(f"  未找到匹配记录:          {stats_not_found}")
    print(f"  期次文件缺失跳过:        {stats_period_errors}")
    print(f"  输出文件:                {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
