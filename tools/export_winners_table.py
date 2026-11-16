#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出某一期「中标人 × 中标车型」明细表。

输出:
  downloads/<zcid>/auction_results_<zcid>.csv   完整明细（UTF-8 BOM，Excel 直接打开）
  downloads/<zcid>/auction_results_<zcid>.md    同内容 Markdown 表 + 汇总

用法:
  python3 tools/export_winners_table.py 2464
"""
import os
import sys
import csv
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_float(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def wan(v):
    f = to_float(v)
    return f"{f / 10000:.2f}" if f is not None else "—"


def main():
    zcid = int(sys.argv[1]) if len(sys.argv) > 1 else 2464
    d = os.path.join(DOWNLOADS_DIR, str(zcid))

    details = read_csv(os.path.join(d, "result_detail.csv"))
    profiles = read_csv(os.path.join(DOWNLOADS_DIR, "winner_profiles.csv"))

    # winner_profiles 已按 car_link 去重（前 7 位碰撞时取名次最好的候选），
    # 直接用它的 prefix / 次数 / 排名，避免再按 7 位前缀瞎猜。
    prof = {r["car_link"]: r for r in profiles if r.get("result_zcid") == str(zcid)}

    rows = []
    for r in details:
        pr = prof.get(r.get("car_link", ""), {})
        times = pr.get("winner_times", "")
        rows.append({
            "car_name": r.get("car_name", ""),
            "times": int(times) if str(times).isdigit() else None,
            "reg_time": (pr.get("winner_reg_time") or "").replace(": ", ":").replace(". ", "."),
            "full_code": pr.get("prefix", ""),
            "start_price": to_float(r.get("start_price")),
            "final_price": to_float(r.get("final_price")),
            "bracket": pr.get("price_bracket", ""),
            "court": r.get("court", ""),
            "status": r.get("status", ""),
            "item_no": r.get("item_no", ""),
            "rank": pr.get("winner_rank", ""),
            "total": pr.get("total_bidders", ""),
            "car_link": r.get("car_link", ""),
        })

    # 排序：摇号次数降序（强者在前），同次数按注册时间
    rows.sort(key=lambda x: (-(x["times"] or 0), x["reg_time"]))

    csv_path = os.path.join(d, f"auction_results_{zcid}.csv")
    fields = ["car_name", "times", "reg_time", "full_code", "start_price", "final_price",
              "bracket", "court", "status", "item_no", "rank", "total", "car_link"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    sold = [r for r in rows if r["final_price"]]
    matched = [r for r in rows if r["times"] is not None]
    times_list = [r["times"] for r in matched]
    brackets = Counter(r["bracket"] for r in sold if r["bracket"])
    ratio15 = sum(1 for r in sold if r["start_price"] and r["final_price"]
                  and abs(r["final_price"] / r["start_price"] - 1.5) < 0.005)

    lines = []
    lines.append(f"# {zcid} 期中标明细（中标人 × 中标车型）\n")
    lines.append(f"- 车辆总数：{len(rows)} 台，成交 {len(sold)} 台"
                 f"（成交价 = 起拍价 ×1.5 的占 {ratio15}/{len(sold)}）")
    lines.append(f"- 摇号次数匹配：{len(matched)}/{len(rows)} 条（按公示编码前 7 位匹配资格池）")
    if times_list:
        lines.append(f"- 中标者摇号次数：最低 {min(times_list)} 次，最高 {max(times_list)} 次，"
                     f"中位 {sorted(times_list)[len(times_list) // 2]} 次，"
                     f"平均 {sum(times_list) / len(times_list):.1f} 次")
    if brackets:
        dist = "、".join(f"{b} {n} 台" for b, n in
                         sorted(brackets.items(), key=lambda kv: int(kv[0].split("-")[0])))
        lines.append(f"- 成交档位（按顶格价）：{dist}")
    lines.append("")
    lines.append("| # | 摇号次数 | 注册时间 | 中标车型 | 起拍价(万) | 成交价(万) | 当时排名 | 法院 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        rank = f"{r['rank']}/{r['total']}" if r["rank"] and r["total"] else "—"
        lines.append(
            f"| {i} | {r['times'] if r['times'] is not None else '—'} | {r['reg_time'] or '—'} | "
            f"{r['car_name']} | {wan(r['start_price'])} | {wan(r['final_price'])} | {rank} | {r['court']} |"
        )

    md_path = os.path.join(d, f"auction_results_{zcid}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"✓ {csv_path}（{len(rows)} 行）")
    print(f"✓ {md_path}")
    print(f"  成交 {len(sold)} 台 · 次数匹配 {len(matched)} 条 · "
          f"次数区间 {min(times_list) if times_list else '-'}~{max(times_list) if times_list else '-'}")


if __name__ == "__main__":
    main()
