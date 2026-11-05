#!/usr/bin/env python3
"""解析 MinerU 输出的 gsxx_331.md 为 CSV"""

import os
import re
import csv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_PATH = os.path.join(BASE_DIR, "downloads/331/gsxx_331/auto/gsxx_331.md")
CSV_PATH = os.path.join(BASE_DIR, "downloads/331/gsxx_331.csv")


def parse_md(filepath):
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    for m in re.finditer(
        r'<tr><td>(\d{9})\*+</td><td>(\d+)</td><td>([^<]+)</td></tr>',
        content,
    ):
        prefix = m.group(1)
        full_code = prefix + "****"
        records.append({
            "full_code": full_code,
            "prefix": prefix,
            "times": int(m.group(2)),
            "reg_time": m.group(3).strip(),
        })
    return records


def main():
    records = parse_md(MD_PATH)
    print(f"解析到 {len(records)} 条记录")

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["full_code", "prefix", "times", "reg_time"])
        writer.writeheader()
        writer.writerows(records)

    print(f"已写入: {CSV_PATH}")
    print(f"前3条:")
    for r in records[:3]:
        print(f"  {r['full_code']}  {r['times']}次  {r['reg_time']}")


if __name__ == "__main__":
    main()
