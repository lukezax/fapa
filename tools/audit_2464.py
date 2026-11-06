#!/usr/bin/env python3
"""
2464 期数据审计 + 合并落盘。

用法:
  python3 tools/audit_2464.py            # 校验并输出 audit.json / cars_2464.csv
  python3 tools/audit_2464.py --zcid 2464

输出:
  downloads/{zcid}/audit.json     数据质量审计
  downloads/{zcid}/cars_2464.csv  result_detail + llm + mileage + limit 合并表
"""

import os
import sys
import csv
import json
import re
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")

try:
    from tools.brand import extract_brand
except ImportError:
    from brand import extract_brand

PERIOD_MAP = {2464: "202611期"}


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    zcid = sys.argv[sys.argv.index("--zcid") + 1] if "--zcid" in sys.argv else "2464"
    d = os.path.join(DOWNLOADS_DIR, zcid)

    details = read_csv(os.path.join(d, "result_detail.csv"))
    llms = {r["car_link"]: r for r in read_csv(os.path.join(d, "car_details_llm.csv"))}
    mileages = {r["car_link"]: r for r in read_csv(os.path.join(d, "mileage.csv"))}
    limits = {r["car_link"]: r for r in read_csv(os.path.join(d, "limit_prices.csv"))}

    survey_dir = os.path.join(d, "survey_texts")
    survey_files = set(os.listdir(survey_dir)) if os.path.isdir(survey_dir) else set()

    audit = {"zcid": int(zcid)}
    links = [r.get("car_link", "") for r in details]
    audit["detail_rows"] = len(details)
    audit["detail_unique_links"] = len(set(links))
    audit["duplicate_links"] = len(links) - len(set(links))

    missing_txt = []
    llm_ok = 0
    mileage_rows = 0
    mileage_found = 0
    outliers = []
    km_counter = Counter()
    empty_court = 0
    bad_price = 0

    merged = []
    for row in details:
        link = row.get("car_link", "")
        slug = link.rstrip("/").split("/")[-1].replace(".html", "")
        llm = llms.get(link, {})
        ml = mileages.get(link, {})
        lm = limits.get(link, {})

        if f"{slug}.txt" not in survey_files:
            missing_txt.append(link)
        if llm.get("has_license") or llm.get("use_type"):
            llm_ok += 1
        if ml.get("mileage_km"):
            mileage_rows += 1
            km = float(ml["mileage_km"])
            km_counter[int(km)] += 1
            if not (5000 <= km <= 400000):
                outliers.append({"car_link": link, "mileage_km": km})
        if not (row.get("court") or llm.get("court")):
            empty_court += 1
        try:
            if float(row.get("start_price") or 0) <= 0:
                bad_price += 1
        except ValueError:
            bad_price += 1

        car_name = row.get("car_name", "") or llm.get("car_name", "")
        merged.append({
            "car_link": link,
            "car_name": car_name,
            "zcid": int(zcid),
            "period": PERIOD_MAP.get(int(zcid), f"{zcid}期"),
            "item_no": row.get("item_no", "") or llm.get("item_no", ""),
            "court": row.get("court", "") or llm.get("court", ""),
            "start_price": row.get("start_price", ""),
            "limit_price": lm.get("limit_price", ""),
            "final_price": row.get("final_price", ""),
            "status": row.get("status", ""),
            "brand": extract_brand(car_name),
            "has_license": llm.get("has_license", ""),
            "has_registration": llm.get("has_registration", ""),
            "has_plate": llm.get("has_plate", ""),
            "has_key": llm.get("has_key", ""),
            "use_type": llm.get("use_type", ""),
            "fuel_type": llm.get("fuel_type", ""),
            "emission_standard": llm.get("emission_standard", ""),
            "violation_count": llm.get("violation_count", ""),
            "violation_points": llm.get("violation_points", ""),
            "violation_fine": llm.get("violation_fine", ""),
            "is_mortgaged": llm.get("is_mortgaged", ""),
            "parking_fee": llm.get("parking_fee", ""),
            "repair_fee": llm.get("repair_fee", ""),
            "total_extra_fee": llm.get("total_extra_fee", ""),
            "deposit": llm.get("deposit", ""),
            "mileage_km": ml.get("mileage_km", ""),
            "vlm_status": ml.get("vlm_status", ""),
            "preview_location": llm.get("preview_location", ""),
            "first_reg_date": llm.get("first_reg_date", ""),
            "inspection_expiry": llm.get("inspection_expiry", ""),
            "vehicle_model": llm.get("vehicle_model", ""),
        })

    vlm_status = Counter(m.get("vlm_status", "") for m in mileages.values())
    audit["survey_txt"] = len([f for f in survey_files if f.endswith(".txt")])
    audit["missing_survey_txt"] = missing_txt
    audit["llm_rows_with_data"] = llm_ok
    audit["mileage_rows"] = len(mileages)
    audit["mileage_found"] = mileage_rows
    audit["mileage_found_rate"] = round(mileage_rows / len(details) * 100, 1) if details else 0
    audit["vlm_status_counter"] = dict(vlm_status)
    audit["mileage_outliers"] = outliers
    audit["repeated_mileage_top"] = [
        {"km": km, "count": n} for km, n in km_counter.most_common(10) if n > 1
    ]
    audit["empty_court"] = empty_court
    audit["bad_start_price"] = bad_price

    merged_path = os.path.join(d, "cars_2464.csv")
    if merged:
        with open(merged_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
            writer.writeheader()
            writer.writerows(merged)

    audit_path = os.path.join(d, "audit.json")
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(json.dumps(audit, ensure_ascii=False, indent=2)[:2000])
    print(f"\n合并表: {merged_path}")
    print(f"审计:   {audit_path}")


if __name__ == "__main__":
    main()
