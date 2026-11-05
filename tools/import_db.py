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

# ── 品牌提取表（与 webapp/app.py KNOWN_BRANDS 对齐：含车型级词条）──
KNOWN_BRANDS = [
    "梅赛德斯-奔驰", "梅赛德斯奔驰", "奔驰", "宝马", "MINI", "迷你",
    "奥迪", "大众汽车", "大众", "丰田", "本田", "别克", "北京现代", "现代",
    "福特", "日产", "东风日产", "尼桑", "沃尔沃",
    "保时捷", "路虎", "揽胜运动", "揽胜", "捷豹",
    "雷克萨斯", "凯迪拉克", "雪佛兰", "标致", "雪铁龙",
    "马自达", "起亚", "三菱", "斯巴鲁", "英菲尼迪", "讴歌",
    "红旗", "比亚迪", "蔚来", "小鹏", "理想", "特斯拉", "拓速乐",
    "长安", "长城", "哈弗", "魏派", "WEY", "吉利", "领克",
    "奇瑞", "江淮", "奔腾", "中华", "荣威", "名爵", "传祺",
    "五菱", "宝骏", "东风", "一汽", "北汽", "北京汽车", "北京", "绅宝",
    "DS", "smart",
    "劳斯莱斯", "宾利", "法拉利", "玛莎拉蒂", "阿斯顿马丁", "迈凯伦",
    "帕纳美拉", "埃尔法", "皇冠",
    "霸道", "酷路泽", "陆地巡洋舰", "巡洋舰",
    "神行者", "发现", "极光", "牧马人", "大切诺基", "指南者", "大捷龙",
    "萨博", "欧宝", "金龙", "金杯", "福田", "新凯",
    "北斗星", "天籁", "夏利", "思威", "帕萨特", "宝来",
    "福克斯", "波罗", "捷达", "桑塔纳", "朗逸", "速腾",
    "迈腾", "高尔夫", "途观", "途安", "途锐", "辉腾",
    "凯越", "英朗", "君威", "君越", "林荫大道",
    "雅阁", "飞度", "锋范", "思域", "奥德赛",
    "凯美瑞", "卡罗拉", "汉兰达", "普拉多",
    "骐达", "轩逸", "逍客", "奇骏",
    "赛欧", "科鲁兹", "迈锐宝", "探界者", "昂科雷",
    "索纳塔", "伊兰特", "途胜",
    "胜达", "唯雅诺", "弈鸥", "凯尊", "凯宴", "博斯特", "迈凯",
    "索兰托", "傲虎", "森林人", "欧蓝德", "迈特威",
    "BMW", "尼桑",
]

# ── 品牌归一化（webapp BRAND_NORMALIZE 拉平映射链 + 合并重复项）──
BRAND_NORMALIZE = {
    "大众汽车": "大众",
    "梅赛德斯奔驰": "梅赛德斯-奔驰",
    "奔驰": "梅赛德斯-奔驰",
    "唯雅诺": "梅赛德斯-奔驰",
    "北京汽车": "北京",
    "北京现代": "现代",
    "迷你": "MINI",
    "东风日产": "日产",
    "尼桑": "日产",
    "揽胜运动": "路虎",
    "揽胜": "路虎",
    "神行者": "路虎",
    "发现": "路虎",
    "极光": "路虎",
    "陆地巡洋舰": "丰田", "巡洋舰": "丰田", "酷路泽": "丰田",
    "霸道": "丰田", "普拉多": "丰田", "凯美瑞": "丰田", "卡罗拉": "丰田",
    "汉兰达": "丰田", "RAV4": "丰田", "埃尔法": "丰田", "皇冠": "丰田",
    "雅阁": "本田", "思域": "本田", "CR-V": "本田", "奥德赛": "本田",
    "飞度": "本田", "锋范": "本田", "思威": "本田",
    "帕萨特": "大众", "迈腾": "大众", "速腾": "大众", "朗逸": "大众",
    "高尔夫": "大众", "途观": "大众", "途安": "大众", "途锐": "大众",
    "辉腾": "大众", "宝来": "大众", "捷达": "大众", "桑塔纳": "大众",
    "波罗": "大众", "迈特威": "大众", "弈鸥": "大众",
    "福克斯": "福特",
    "BMW": "宝马",
    "天籁": "日产", "轩逸": "日产", "骐达": "日产", "逍客": "日产", "奇骏": "日产",
    "凯越": "别克", "英朗": "别克", "君威": "别克", "君越": "别克",
    "GL8": "别克", "林荫大道": "别克", "昂科雷": "别克",
    "赛欧": "雪佛兰", "科鲁兹": "雪佛兰", "迈锐宝": "雪佛兰", "探界者": "雪佛兰",
    "索纳塔": "现代", "伊兰特": "现代", "途胜": "现代", "ix35": "现代", "胜达": "现代",
    "索兰托": "起亚", "凯尊": "起亚",
    "牧马人": "Jeep", "大切诺基": "Jeep", "指南者": "Jeep",
    "大捷龙": "克莱斯勒",
    "欧蓝德": "三菱", "傲虎": "斯巴鲁", "森林人": "斯巴鲁",
    "拓速乐": "特斯拉",
    "凯宴": "保时捷", "博斯特": "保时捷", "帕纳美拉": "保时捷", "迈凯": "保时捷",
}


def extract_brand(car_name):
    """从车名提取品牌（与 webapp/app.py 逻辑一致：先剥车牌号，再按长度优先匹配已知品牌）"""
    name = (car_name or "").strip()
    # Case 1: 车名含「牌」→ 提取车牌号与「牌」之间的品牌词
    m = re.search(r"(?:车牌号为)?京[0-9A-Za-z]+([\u4e00-\u9fffA-Za-z-]+)牌", name)
    if m:
        b = m.group(1).strip()
        if b and len(b) <= 20:
            return BRAND_NORMALIZE.get(b, b)
    # Case 2: 已知品牌按长度优先匹配
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if b in name:
            return BRAND_NORMALIZE.get(b, b)
    return "其他"


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
def build_cars(zcids, out_dir):
    """合并各期 result_detail + car_details_llm + mileage（按 car_link）。
    历史期次无详情时，从 winners 生成 source=winner_only 的占位记录。"""
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

            # 读三表
            details = _read_csv_dict(detail_csv)
            llms = {r["car_link"]: r for r in _read_csv_dict(llm_csv)}
            mileages = {r["car_link"]: r for r in _read_csv_dict(mileage_csv)}

            for row in details:
                link = row.get("car_link", "")
                if not link or link in written_links:
                    continue
                llm = llms.get(link, {})
                ml = mileages.get(link, {})
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
                    "source": "detail",
                }
                w.write(json.dumps(doc, ensure_ascii=False) + "\n")
                written_links.add(link)
                count += 1

    # 历史期次占位（无 result_detail 的期次，从 winners 生成）
    winner_csv = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")
    if os.path.exists(winner_csv):
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


def main():
    parser = argparse.ArgumentParser(description="CSV → 云数据库 JSONL 导入工具")
    parser.add_argument("--zcid", action="append", help="只导入指定期次（可多次），默认全部")
    parser.add_argument("--out", default="downloads/export", help="输出目录")
    args = parser.parse_args()

    out_dir = os.path.join(BASE_DIR, args.out)
    os.makedirs(out_dir, exist_ok=True)

    zcids = [int(z) for z in args.zcid] if args.zcid else []
    print(f"输出目录: {out_dir}")
    print(f"期次范围: {'全部' if not zcids else zcids}")

    build_pool_all(zcids, out_dir)
    build_winners(zcids, out_dir)
    build_cars(zcids, out_dir)

    print(f"\n完成。将 {out_dir} 下的 .jsonl 文件通过 云开发控制台 → 数据库 → 导入 上传。")


if __name__ == "__main__":
    main()
