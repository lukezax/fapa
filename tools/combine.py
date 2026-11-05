#!/usr/bin/env python3
"""
将竞价结果合并到 merged_gsxx 中，以 merged_gsxx 为主表。

匹配: merged_gsxx.prefix 前7位 = result_detail.code

一人多条结果时展开为多行，无结果时结果列为空。

输出: downloads/combined.csv
"""

import os
import csv
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
OUTPUT_PATH = os.path.join(DOWNLOADS_DIR, "combined.csv")


def get_known_zcids():
    return sorted([int(d) for d in os.listdir(DOWNLOADS_DIR) if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))])


KNOWN_ZCIDS = get_known_zcids()

detail_fields = [
    "car_name", "car_link", "item_no", "court",
    "start_price", "code", "buyer", "status", "final_price",
    "result_zcid",
]
gsxx_fields = [
    "full_code", "prefix", "times", "latest_times",
    "reg_time", "zcid", "period",
]
all_fields = gsxx_fields + detail_fields


def read_merged_gsxx():
    path = os.path.join(DOWNLOADS_DIR, "merged_gsxx.csv")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["prefix7"] = row["prefix"][:7]
            rows.append(row)
    return rows


def read_all_details():
    idx = defaultdict(list)
    for zcid in KNOWN_ZCIDS:
        d = str(zcid)
        path = os.path.join(DOWNLOADS_DIR, d, "result_detail.csv")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["result_zcid"] = d
                idx[row["code"]].append(row)
    return idx


def main():
    print("读取 merged_gsxx.csv...")
    gsxx_rows = read_merged_gsxx()
    print(f"  {len(gsxx_rows)} 条\n")

    print("读取 result_detail.csv...")
    detail_idx = read_all_details()
    detail_total = sum(len(v) for v in detail_idx.values())
    print(f"  {detail_total} 条竞价结果, {len(detail_idx)} 个唯一7位编码\n")

    # 统计每个 7 位前缀有多少人共享（用于判断是否需要精确期次匹配）
    prefix7_count = {}
    for person in gsxx_rows:
        p7 = person["prefix7"]
        prefix7_count[p7] = prefix7_count.get(p7, 0) + 1

    matched_people = 0
    matched_rows = 0
    unmatched = 0
    output = []

    for person in gsxx_rows:
        p7 = person["prefix7"]
        results = detail_idx.get(p7, [])
        pzcid = int(person["zcid"])
        is_ambiguous = prefix7_count[p7] > 1

        if not results:
            row = {k: person.get(k, "") for k in gsxx_fields}
            for k in detail_fields:
                row[k] = ""
            output.append(row)
            unmatched += 1
            continue

        if is_ambiguous:
            # 多人共享同一 7 位前缀，必须精确期次匹配
            valid = [r for r in results if int(r["result_zcid"]) == pzcid]
        else:
            # 唯一匹配，放宽条件
            valid = [r for r in results if int(r["result_zcid"]) <= pzcid]

        if not valid:
            row = {k: person.get(k, "") for k in gsxx_fields}
            for k in detail_fields:
                row[k] = ""
            output.append(row)
            unmatched += 1
            continue

        matched_people += 1
        for r in valid:
            row = {k: person.get(k, "") for k in gsxx_fields}
            for k in detail_fields:
                row[k] = r.get(k, "")
            output.append(row)
            matched_rows += 1

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields)
        writer.writeheader()
        writer.writerows(output)

    print(f"合并完成:")
    print(f"  merged_gsxx 总人数:   {len(gsxx_rows)}")
    print(f"  有匹配中拍记录:       {matched_people} 人")
    print(f"  最终输出行数:         {len(output)}")
    print(f"  未匹配:               {unmatched} 行")
    print(f"  中拍展开:             {matched_rows} 行")
    print(f"\n输出: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
