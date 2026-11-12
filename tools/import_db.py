#!/usr/bin/env python3
"""
数据导入工具：把本地 CSV 数据管道产物转换为微信云数据库可导入的 JSONL 文件。

用法:
  python3 tools/import_db.py                      # 全量导入（所有期次）
  python3 tools/import_db.py --zcid 2400          # 增量导入指定期次（下次发牌后跑这个）
  python3 tools/import_db.py --out data_export    # 指定输出目录（默认 downloads/export）

输出（每个集合一个 .jsonl 文件，通过云开发控制台 → 数据库 → 导入）:
  pool_all.jsonl      全量资格池（精确排名用）
  cars.jsonl          跨期全部车辆（筛选用）
  winners.jsonl       中拍者画像（趋势/档位统计用）

字段与 docs/API_CONTRACT.md 完全对应。
"""

import os
import sys
import csv
import json
import re
import argparse
from collections import OrderedDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")

# ── 品牌提取（唯一实现在 tools/brand.py，webapp 与导入工具共用）──
try:
    from tools.brand import extract_brand  # 以项目根目录运行时
except ImportError:  # 以 tools/ 为脚本目录直接运行时
    from brand import extract_brand


def normalize_fuel(val):
    """燃料类型归并：电→纯电；混合动力/汽油电/电混合动力→油电混合"""
    s = (val or "").strip()
    if not s:
        return ""
    if "纯电" in s or s == "电":
        return "纯电"
    if "混合" in s or "油电" in s or "插电" in s or "汽油电" in s:
        return "油电混合"
    if "电动" in s:
        return "纯电"
    if "汽油" in s:
        return "汽油"
    if "柴油" in s:
        return "柴油"
    return s


def normalize_reg_time(rt):
    """归一化 reg_time: "2011-01-29 20: 04: 34. 627" → "2011-01-29 20:04:34.627"
    移除冒号和点号后的空格，保证字典序 == 时间序。"""
    if not rt:
        return ""
    cleaned = re.sub(r":\s", ":", rt)
    cleaned = re.sub(r"\.\s", ".", cleaned)
    return cleaned.strip()


def to_num(val, cast=float):
    """安全转数字，空/非法返回 None"""
    if val is None or str(val).strip() == "":
        return None
    try:
        return cast(val)
    except (ValueError, TypeError):
        return None


# ── 期次名映射（zcid → period）──
PERIOD_MAP = {
    2464: "202611期", 2400: "202606期", 2238: "202512期", 2041: "202506期",
    1897: "202411期", 1694: "202402期", 1609: "202310期",
    1533: "202306期", 1417: "202302期", 1064: "202211期",
    725: "202206期", 640: "202202期", 532: "202111期",
    413: "202106期", 378: "202102期", 331: "202011期",
}


def period_of(zcid):
    return PERIOD_MAP.get(int(zcid), f"{zcid}期")


# ══════════════════════════════════════════════
# 1. pool_all — 全量资格池（精确排名）
# ══════════════════════════════════════════════
def build_pool_all(zcids, out_dir):
    src = os.path.join(DOWNLOADS_DIR, "merged_gsxx.csv")
    if not os.path.exists(src):
        print(f"✗ 缺少 {src}，先运行 pipeline 步骤3")
        return 0

    zcids = set(int(z) for z in zcids)
    out = os.path.join(out_dir, "pool_all.jsonl")
    count = 0
    with open(src, "r", encoding="utf-8-sig") as f, open(out, "w", encoding="utf-8") as w:
        for row in csv.DictReader(f):
            zcid = to_num(row.get("zcid"), int)
            if zcid is None or (zcids and zcid not in zcids):
                continue
            doc = {
                "full_code": row.get("full_code", ""),
                "prefix": row.get("prefix", ""),
                "times": to_num(row.get("times"), int),
                "reg_time": normalize_reg_time(row.get("reg_time", "")),
                "zcid": zcid,
            }
            w.write(json.dumps(doc, ensure_ascii=False) + "\n")
            count += 1
    print(f"✓ pool_all: {count} 行 → {out}")
    return count


# ══════════════════════════════════════════════
# 2. winners — 中拍者画像
# ══════════════════════════════════════════════
def build_winners(zcids, out_dir):
    src = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")
    if not os.path.exists(src):
        print(f"✗ 缺少 {src}，先运行 pipeline 步骤5")
        return 0

    zcids = set(int(z) for z in zcids)
    out = os.path.join(out_dir, "winners.jsonl")
    count = 0
    with open(src, "r", encoding="utf-8-sig") as f, open(out, "w", encoding="utf-8") as w:
        for row in csv.DictReader(f):
            zcid = to_num(row.get("result_zcid"), int)
            if zcid is None or (zcids and zcid not in zcids):
                continue
            doc = {
                "car_link": row.get("car_link", ""),
                "result_zcid": zcid,
                "car_name": row.get("car_name", ""),
                "brand": extract_brand(row.get("car_name", "")),
                "start_price": to_num(row.get("start_price")),
                "final_price": to_num(row.get("final_price")),
                "limit_price": to_num(row.get("limit_price")),
                "price_bracket": row.get("price_bracket", ""),
                "winner_times": to_num(row.get("winner_times"), int),
                "winner_reg_time": normalize_reg_time(row.get("winner_reg_time", "")),
                "winner_rank": to_num(row.get("winner_rank"), int),
                "total_bidders": to_num(row.get("total_bidders"), int),
            }
            w.write(json.dumps(doc, ensure_ascii=False) + "\n")
            count += 1
    print(f"✓ winners: {count} 行 → {out}")
    return count


# ══════════════════════════════════════════════
# 3. cars — 跨期全部车辆
# ══════════════════════════════════════════════
def build_cars(zcids, out_dir, include_winner_only=False):
    """合并各期 result_detail + car_details_llm + mileage + limit_prices（按 car_link）。
    默认只写当前期；历史期次仅在 include_winner_only=True 时从 winners 生成占位记录。"""
    zcids = set(int(z) for z in zcids)
    out = os.path.join(out_dir, "cars.jsonl")
    written_links = set()
    count = 0

    with open(out, "w", encoding="utf-8") as w:
        for zcid_dir in sorted(os.listdir(DOWNLOADS_DIR)):
            if not zcid_dir.isdigit():
                continue
            zcid = int(zcid_dir)
            if zcids and zcid not in zcids:
                continue
            d = os.path.join(DOWNLOADS_DIR, zcid_dir)

            detail_csv = os.path.join(d, "result_detail.csv")
            llm_csv = os.path.join(d, "car_details_llm.csv")
            mileage_csv = os.path.join(d, "mileage.csv")
            limit_csv = os.path.join(d, "limit_prices.csv")

            # 读四表
            details = _read_csv_dict(detail_csv)
            llms = {r["car_link"]: r for r in _read_csv_dict(llm_csv)}
            mileages = {r["car_link"]: r for r in _read_csv_dict(mileage_csv)}
            limits = {r["car_link"]: r for r in _read_csv_dict(limit_csv)}

            for row in details:
                link = row.get("car_link", "")
                if not link or link in written_links:
                    continue
                llm = llms.get(link, {})
                ml = mileages.get(link, {})
                lm = limits.get(link, {})
                car_name = row.get("car_name", "") or llm.get("car_name", "")
                doc = {
                    "car_link": link,
                    "car_name": car_name,
                    "zcid": zcid,
                    "period": period_of(zcid),
                    "item_no": row.get("item_no", "") or llm.get("item_no", ""),
                    "court": row.get("court", "") or llm.get("court", ""),
                    "start_price": to_num(row.get("start_price")) or to_num(llm.get("start_price")),
                    "final_price": to_num(row.get("final_price")) or to_num(llm.get("final_price")),
                    "limit_price": to_num(lm.get("limit_price")),
                    "brand": extract_brand(car_name),
                    "has_license": llm.get("has_license", ""),
                    "has_registration": llm.get("has_registration", ""),
                    "has_plate": llm.get("has_plate", ""),
                    "has_key": llm.get("has_key", ""),
                    "use_type": llm.get("use_type", ""),
                    "fuel_type": normalize_fuel(llm.get("fuel_type", "")),
                    "emission_standard": llm.get("emission_standard", ""),
                    "violation_count": to_num(llm.get("violation_count"), int),
                    "violation_points": to_num(llm.get("violation_points"), int),
                    "violation_fine": to_num(llm.get("violation_fine")),
                    "is_mortgaged": llm.get("is_mortgaged", ""),
                    "parking_fee": to_num(llm.get("parking_fee")),
                    "repair_fee": to_num(llm.get("repair_fee")),
                    "total_extra_fee": to_num(llm.get("total_extra_fee")),
                    "deposit": to_num(llm.get("deposit")),
                    "mileage_km": to_num(ml.get("mileage_km"), int),
                    "preview_location": llm.get("preview_location", ""),
                    "first_reg_date": llm.get("first_reg_date", ""),
                    "inspection_expiry": llm.get("inspection_expiry", ""),
                    "vehicle_model": llm.get("vehicle_model", ""),
                    "source": "detail" if llm else "detail_partial",
                }
                w.write(json.dumps(doc, ensure_ascii=False) + "\n")
                written_links.add(link)
                count += 1

    # 历史期次占位（默认关闭：历史数据只用于推荐）
    winner_csv = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")
    if include_winner_only and os.path.exists(winner_csv):
        seen = set()
        with open(winner_csv, "r", encoding="utf-8-sig") as f, open(out, "a", encoding="utf-8") as w:
            for row in csv.DictReader(f):
                zcid = to_num(row.get("result_zcid"), int)
                link = row.get("car_link", "")
                if zcid is None or (zcids and zcid not in zcids):
                    continue
                if link in written_links or link in seen:
                    continue
                seen.add(link)
                doc = {
                    "car_link": link,
                    "car_name": row.get("car_name", ""),
                    "zcid": zcid,
                    "period": period_of(zcid),
                    "item_no": "",
                    "court": "",
                    "start_price": to_num(row.get("start_price")),
                    "final_price": to_num(row.get("final_price")),
                    "limit_price": None,
                    "brand": extract_brand(row.get("car_name", "")),
                    "has_license": "", "has_registration": "", "has_plate": "", "has_key": "",
                    "use_type": "", "fuel_type": "", "emission_standard": "",
                    "violation_count": None, "violation_points": None, "violation_fine": None,
                    "is_mortgaged": "", "parking_fee": None, "repair_fee": None,
                    "total_extra_fee": None, "deposit": None, "mileage_km": None,
                    "preview_location": "", "first_reg_date": "", "inspection_expiry": "",
                    "vehicle_model": "", "source": "winner_only",
                }
                w.write(json.dumps(doc, ensure_ascii=False) + "\n")
                count += 1

    print(f"✓ cars: {count} 行 → {out}")
    return count


def _read_csv_dict(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def get_all_zcids():
    return sorted(
        int(d) for d in os.listdir(DOWNLOADS_DIR)
        if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))
    )


def get_latest_pool_zcid(all_zcids):
    """最新一期有 gsxx_{zcid}.csv 的期次（排名基准）。"""
    for zcid in sorted(all_zcids, reverse=True):
        if os.path.exists(os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.csv")):
            return zcid
    return max(all_zcids) if all_zcids else 2400


def main():
    parser = argparse.ArgumentParser(description="CSV → 云数据库 JSONL 导入工具")
    parser.add_argument("--zcid", action="append", help="兼容旧参数：只导入指定期次（可多次）")
    parser.add_argument("--current-zcid", type=int, help="当前在售期次（cars 只导入这一期）")
    parser.add_argument("--pool-zcid", type=int, help="排名资格池期次（默认最新有 gsxx 的期次）")
    parser.add_argument("--all-pool", action="store_true", help="导入全部期次资格池（默认只导最新池）")
    parser.add_argument("--include-history-cars", action="store_true",
                        help="兼容旧行为：把历史中拍车也写入 cars（默认关闭）")
    parser.add_argument("--out", default="downloads/export", help="输出目录")
    args = parser.parse_args()

    out_dir = os.path.join(BASE_DIR, args.out)
    os.makedirs(out_dir, exist_ok=True)

    all_zcids = get_all_zcids()
    current_zcid = args.current_zcid or max(all_zcids)
    pool_zcid = args.pool_zcid or get_latest_pool_zcid(all_zcids)

    if args.zcid:
        # 旧参数：限定范围
        requested = [int(z) for z in args.zcid]
        pool_zcids = [] if args.all_pool else [pool_zcid]
        winner_zcids = [z for z in requested if z != current_zcid]
        car_zcids = [z for z in requested if z == current_zcid]
    else:
        pool_zcids = [] if args.all_pool else [pool_zcid]
        winner_zcids = [z for z in all_zcids if z != current_zcid]
        car_zcids = [current_zcid]

    print(f"输出目录: {out_dir}")
    print(f"当前在售期次: {current_zcid}")
    print(f"排名资格池: {'全部' if args.all_pool else pool_zcid}")
    print(f"历史中拍期次: {winner_zcids[0]}–{winner_zcids[-1]}（{len(winner_zcids)} 期）"
          if winner_zcids else "历史中拍期次: 无")

    counts = {}
    counts["pool_all"] = build_pool_all(pool_zcids, out_dir)
    counts["winners"] = build_winners(winner_zcids, out_dir)
    counts["cars"] = build_cars(
        car_zcids, out_dir, include_winner_only=args.include_history_cars
    )

    manifest = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "current_zcid": current_zcid,
        "pool_zcid": None if args.all_pool else pool_zcid,
        "winner_zcids": winner_zcids,
        "counts": counts,
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n完成。{manifest_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\n将 {out_dir} 下的 .json 文件通过 云开发控制台 → 数据库 → 导入 上传。")


if __name__ == "__main__":
    main()
