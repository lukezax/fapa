import os
import csv
import math
import sys
import re
from collections import Counter, defaultdict

import flask

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def get_latest_zcid():
    zcids = [int(d) for d in os.listdir(DOWNLOADS_DIR) if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))]
    return str(max(zcids)) if zcids else "2400"


def get_all_zcids():
    return sorted([d for d in os.listdir(DOWNLOADS_DIR) if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))], key=int, reverse=True)


LATEST_ZCID = get_latest_zcid()
GSXX_PATH = os.path.join(DOWNLOADS_DIR, LATEST_ZCID, f"gsxx_{LATEST_ZCID}.csv")
WINNER_PATH = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")

app = flask.Flask(__name__)

# ── Brand known list and extraction ──
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

BRAND_NORMALIZE = {
    "大众汽车": "大众",
    "梅赛德斯奔驰": "梅赛德斯-奔驰",
    "北京汽车": "北京",
    "揽胜运动": "揽胜",
    "陆地巡洋舰": "丰田",
    "巡洋舰": "丰田",
    "霸道": "丰田",
    "普拉多": "丰田",
    "凯美瑞": "丰田",
    "卡罗拉": "丰田",
    "汉兰达": "丰田",
    "RAV4": "丰田",
    "埃尔法": "丰田",
    "雅阁": "本田",
    "思域": "本田",
    "CR-V": "本田",
    "奥德赛": "本田",
    "飞度": "本田",
    "锋范": "本田",
    "思威": "本田",
    "帕萨特": "大众",
    "迈腾": "大众",
    "速腾": "大众",
    "朗逸": "大众",
    "高尔夫": "大众",
    "途观": "大众",
    "途安": "大众",
    "途锐": "大众",
    "辉腾": "大众",
    "宝来": "大众",
    "捷达": "大众",
    "桑塔纳": "大众",
    "波罗": "大众",
    "福克斯": "福特",
    "BMW": "宝马",
    "尼桑": "日产",
    "天籁": "日产",
    "轩逸": "日产",
    "骐达": "日产",
    "逍客": "日产",
    "奇骏": "日产",
    "凯越": "别克",
    "英朗": "别克",
    "君威": "别克",
    "君越": "别克",
    "GL8": "别克",
    "林荫大道": "别克",
    "昂科雷": "别克",
    "赛欧": "雪佛兰",
    "科鲁兹": "雪佛兰",
    "迈锐宝": "雪佛兰",
    "探界者": "雪佛兰",
    "索纳塔": "现代",
    "伊兰特": "现代",
    "途胜": "现代",
    "ix35": "现代",
    "胜达": "现代",
    "索兰托": "起亚",
    "凯尊": "起亚",
    "神行者": "路虎",
    "发现": "路虎",
    "极光": "路虎",
    "揽胜": "路虎",
    "牧马人": " Jeep",
    "大切诺基": " Jeep",
    "指南者": " Jeep",
    "大捷龙": "克莱斯勒",
    "欧蓝德": "三菱",
    "傲虎": "斯巴鲁",
    "森林人": "斯巴鲁",
    "拓速乐": "特斯拉",
    "凯宴": "保时捷",
    "博斯特": "保时捷",
    "帕纳美拉": "保时捷",
    "迈凯": "保时捷",
    "唯雅诺": "奔驰",
    "迈特威": "大众",
    "弈鸥": "大众",
}


def extract_brand(name):
    name = name.strip()
    # Case 1: has 牌 → extract text between license plate and 牌
    m = re.search(r"(?:车牌号为)?京[0-9A-Za-z]+([\u4e00-\u9fffA-Za-z-]+)牌", name)
    if m:
        b = m.group(1).strip()
        if b and len(b) <= 20:
            return BRAND_NORMALIZE.get(b, b)
    # Case 2: check known brands in name
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if b in name:
            nb = BRAND_NORMALIZE.get(b, b)
            return nb
    return "其他"


# ── Time parsing ──
def parse_reg_time(rt):
    rt = rt.strip()
    parts = rt.split()
    date_part = parts[0] if parts else ""
    time_part = parts[1] if len(parts) > 1 else "00:00:00.000"
    time_clean = time_part.replace(": ", ":").replace(". ", ".")
    return date_part, time_clean


def normalise_reg_time_input(raw):
    s = raw.strip().replace("T", " ")
    parts = s.split()
    if len(parts) < 2:
        parts.append("00:00:00.000")
    date_part = parts[0]
    time_part = parts[1]
    if "." not in time_part:
        time_part += ".000"
    time_part = time_part.replace(":", ": ")
    if ". " not in time_part:
        time_part = time_part.replace(".", ". ")
    return f"{date_part} {time_part}"


# ── Data loading ──
def load_data():
    gsxx_rows = []
    with open(GSXX_PATH, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gsxx_rows.append(row)

    winner_rows = []
    with open(WINNER_PATH, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            wt = int(row["winner_times"])
            wr = parse_reg_time(row["winner_reg_time"])
            row["_times"] = wt
            row["_reg_key"] = wr
            row["_pct"] = wt / int(row["total_bidders"])  # winner's percentile by times alone
            row["_brand"] = extract_brand(row["car_name"])
            winner_rows.append(row)

    return gsxx_rows, winner_rows


gsxx_pool, winner_pool = load_data()
GSXX_TOTAL = len(gsxx_pool)


def compute_rank(times, reg_time):
    user_times = int(times)
    user_key = parse_reg_time(reg_time)
    better = 0
    for r in gsxx_pool:
        rt = int(r["times"])
        rr = parse_reg_time(r["reg_time"])
        if rt > user_times or (rt == user_times and rr < user_key):
            better += 1
    return better + 1


def bracket_sort_key(b):
    try:
        return int(b.split("-")[0])
    except (ValueError, IndexError):
        return 9999


# ── Trend data ──
def build_trends():
    periods_order = get_all_zcids()
    pd_data = {}
    for z in periods_order:
        total = 0
        brackets_cnt = Counter()
        for w in winner_pool:
            if w["result_zcid"] == z:
                total = int(w["total_bidders"])
                break
        for w in winner_pool:
            if w["result_zcid"] == z:
                brackets_cnt[w["price_bracket"]] += 1
        pd_data[z] = {
            "zcid": z,
            "total": total,
            "winners": sum(brackets_cnt.values()),
            "brackets": dict(brackets_cnt),
        }
    return pd_data


trend_data = build_trends()


@app.route("/")
def index():
    return flask.render_template("index.html")


@app.route("/api/calculate", methods=["POST"])
def calculate():
    data = flask.request.get_json()
    if not data:
        return {"error": "请求体为空"}, 400

    times = data.get("times")
    reg_time = data.get("reg_time")
    window = int(data.get("window", 10))

    if not times or not reg_time:
        return {"error": "请填写次数和注册时间"}, 400

    try:
        reg_normalised = normalise_reg_time_input(reg_time)
        rank = compute_rank(times, reg_normalised)
    except Exception as e:
        return {"error": f"参数错误: {e}"}, 400

    user_pct = rank / GSXX_TOTAL * 100

    low_abs = max(1, rank - window)
    high_abs = rank + window
    pct_low = math.floor(low_abs / GSXX_TOTAL * 100)
    pct_high = math.ceil(high_abs / GSXX_TOTAL * 100)

    bracket_stats = {}
    for w in winner_pool:
        bk = w["price_bracket"]
        if bk not in bracket_stats:
            bracket_stats[bk] = {
                "total": 0, "pct_list": [],
                "final_prices": [], "deal_ratios": [],
                "brands": Counter(), "peer_matches": [],
            }
        d = bracket_stats[bk]
        d["total"] += 1
        w_pct = int(w["winner_rank"]) / int(w["total_bidders"]) * 100
        d["pct_list"].append(w_pct)

        try:
            fp = float(w["final_price"])
            sp = float(w["start_price"])
            d["final_prices"].append(fp)
            if sp > 0:
                d["deal_ratios"].append(fp / sp)
        except (ValueError, TypeError):
            pass
        d["brands"][w["_brand"]] += 1

        if pct_low <= w_pct <= pct_high:
            d["peer_matches"].append({
                "car_name": w["car_name"],
                "car_link": w["car_link"],
                "start_price": w["start_price"],
                "final_price": w["final_price"],
                "winner_rank": int(w["winner_rank"]),
                "total_bidders": int(w["total_bidders"]),
                "winner_pct": round(w_pct, 1),
                "result_zcid": w["result_zcid"],
                "brand": w["_brand"],
                "pct_diff": round(abs(w_pct - user_pct), 1),
            })

    total_matches = sum(len(d["peer_matches"]) for d in bracket_stats.values())

    panorama_list = []
    for bk in sorted(bracket_stats.keys(), key=bracket_sort_key):
        d = bracket_stats[bk]
        peer_matches = d["peer_matches"]
        match_count = len(peer_matches)
        match_pct = round(match_count / total_matches * 100, 1) if total_matches > 0 else 0

        if match_pct >= 25:
            recommendation = "强烈推荐"
        elif match_pct >= 15:
            recommendation = "推荐"
        elif match_pct >= 5:
            recommendation = "可考虑"
        else:
            recommendation = "观望"

        avg_winner_pct = round(sum(d["pct_list"]) / len(d["pct_list"]), 1) if d["pct_list"] else 0
        avg_final = round(sum(d["final_prices"]) / len(d["final_prices"])) if d["final_prices"] else 0
        avg_deal = round(sum(d["deal_ratios"]) / len(d["deal_ratios"]), 2) if d["deal_ratios"] else 0
        top_brands = dict(d["brands"].most_common(10))

        if avg_winner_pct > 0:
            ratio = user_pct / avg_winner_pct
            if ratio < 0.8:
                difficulty = "容易"
            elif ratio < 1.2:
                difficulty = "适中"
            else:
                difficulty = "困难"
        else:
            difficulty = "—"

        periods_covered = len(set(m["result_zcid"] for m in peer_matches))

        peer_matches.sort(key=lambda x: x["pct_diff"])

        top5_sorted = sorted(peer_matches, key=lambda x: float(x["final_price"]))
        top5 = [
            {
                "car_name": m["car_name"],
                "car_link": m["car_link"],
                "start_price": m["start_price"],
                "final_price": m["final_price"],
                "result_zcid": m["result_zcid"],
                "winner_pct": m["winner_pct"],
                "brand": m["brand"],
            }
            for m in top5_sorted[:5]
        ]

        all_matches = [
            {
                "car_name": m["car_name"],
                "car_link": m["car_link"],
                "start_price": m["start_price"],
                "final_price": m["final_price"],
                "result_zcid": m["result_zcid"],
                "winner_pct": m["winner_pct"],
                "brand": m["brand"],
                "pct_diff": m["pct_diff"],
            }
            for m in peer_matches
        ]

        panorama_list.append({
            "bracket": bk,
            "match_count": match_count,
            "match_pct": match_pct,
            "recommendation": recommendation,
            "avg_final_price": avg_final,
            "avg_deal_ratio": avg_deal,
            "difficulty": difficulty,
            "periods_covered": periods_covered,
            "top_brands": top_brands,
            "top5": top5,
            "all_matches": all_matches,
        })

    panorama_list.sort(key=lambda x: -x["match_pct"])

    periods_order = get_all_zcids()
    period_trend_list = []
    for zcid in periods_order:
        total_bidders = 0
        for w in winner_pool:
            if w["result_zcid"] == zcid:
                total_bidders = int(w["total_bidders"])
                break
        if total_bidders == 0:
            continue

        user_equiv_rank = round(user_pct / 100 * total_bidders)

        winner_count = sum(1 for w in winner_pool if w["result_zcid"] == zcid)

        best_match = None
        best_diff = float("inf")
        for w in winner_pool:
            if w["result_zcid"] == zcid:
                w_pct_val = int(w["winner_rank"]) / int(w["total_bidders"]) * 100
                diff = abs(w_pct_val - user_pct)
                if diff < best_diff:
                    best_diff = diff
                    best_match = w

        if best_match is not None:
            matched_car = {
                "car_name": best_match["car_name"],
                "car_link": best_match["car_link"],
                "final_price": best_match["final_price"],
                "bracket": best_match["price_bracket"],
            }
        else:
            matched_car = None

        period_trend_list.append({
            "zcid": zcid,
            "total_bidders": total_bidders,
            "winner_count": winner_count,
            "user_equiv_rank": user_equiv_rank,
            "matched_car": matched_car,
        })

    all_final_prices = []
    for d in bracket_stats.values():
        for m in d["peer_matches"]:
            try:
                all_final_prices.append(float(m["final_price"]))
            except (ValueError, TypeError):
                pass
    min_final_price = round(min(all_final_prices)) if all_final_prices else None

    return {
        "rank": rank,
        "total": GSXX_TOTAL,
        "user_pct": round(user_pct, 1),
        "total_matches": total_matches,
        "min_final_price": min_final_price,
        "panorama": panorama_list,
        "period_trend": period_trend_list,
    }


# ── Car detail data ──
CAR_DETAILS_PATH = os.path.join(DOWNLOADS_DIR, LATEST_ZCID, "car_details_llm.csv")
MILEAGE_PATH = os.path.join(DOWNLOADS_DIR, LATEST_ZCID, "mileage.csv")


def load_car_details():
    rows = []
    if not os.path.exists(CAR_DETAILS_PATH):
        return rows
    with open(CAR_DETAILS_PATH, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["_brand"] = extract_brand(row.get("car_name", ""))
            rows.append(row)

    mileage_map = {}
    if os.path.exists(MILEAGE_PATH):
        with open(MILEAGE_PATH, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                link = row.get("car_link", "")
                km = row.get("mileage_km", "")
                if link and km:
                    mileage_map[link] = km

    for row in rows:
        link = row.get("car_link", "")
        if link in mileage_map:
            row["mileage"] = mileage_map[link]

    return rows


@app.route("/cars")
def cars_page():
    return flask.render_template("cars.html")


@app.route("/api/cars")
def api_cars():
    cars = load_car_details()

    # Filters from query params
    brand = flask.request.args.get("brand", "")
    court = flask.request.args.get("court", "")
    has_license = flask.request.args.get("has_license", "")
    has_registration = flask.request.args.get("has_registration", "")
    has_plate = flask.request.args.get("has_plate", "")
    has_key = flask.request.args.get("has_key", "")
    is_mortgaged = flask.request.args.get("is_mortgaged", "")
    fuel_type = flask.request.args.get("fuel_type", "")
    emission = flask.request.args.get("emission", "")
    final_price_min = flask.request.args.get("final_price_min", "")
    final_price_max = flask.request.args.get("final_price_max", "")
    violation_min = flask.request.args.get("violation_min", "")
    violation_max = flask.request.args.get("violation_max", "")
    parking_max = flask.request.args.get("parking_max", "")
    repair_max = flask.request.args.get("repair_max", "")
    deposit_max = flask.request.args.get("deposit_max", "")
    extra_fee_max = flask.request.args.get("extra_fee_max", "")
    mileage_max = flask.request.args.get("mileage_max", "")

    # Apply filters
    if brand:
        brand_list = [b.strip() for b in brand.split(",") if b.strip()]
        if brand_list:
            cars = [c for c in cars if c.get("_brand") in brand_list]
    if court:
        court_list = [ct.strip() for ct in court.split(",") if ct.strip()]
        if court_list:
            cars = [c for c in cars if c.get("court") in court_list]
    if has_license:
        cars = [c for c in cars if c.get("has_license") == has_license]
    if has_registration:
        cars = [c for c in cars if c.get("has_registration") == has_registration]
    if has_plate:
        cars = [c for c in cars if c.get("has_plate") == has_plate]
    if has_key:
        cars = [c for c in cars if c.get("has_key") == has_key]
    if is_mortgaged:
        cars = [c for c in cars if c.get("is_mortgaged") == is_mortgaged]
    if fuel_type:
        fuel_list = [f.strip() for f in fuel_type.split(",") if f.strip()]
        if fuel_list:
            cars = [c for c in cars if c.get("fuel_type") in fuel_list]
    if emission:
        emission_list = [e.strip() for e in emission.split(",") if e.strip()]
        if emission_list:
            cars = [c for c in cars if c.get("emission_standard") in emission_list]
    if final_price_min:
        cars = [c for c in cars if float(c.get("final_price", 0)) >= float(final_price_min)]
    if final_price_max:
        cars = [c for c in cars if float(c.get("final_price", 0)) <= float(final_price_max)]
    if violation_min:
        cars = [c for c in cars if int(c.get("violation_count", 0) or 0) >= int(violation_min)]
    if violation_max:
        cars = [c for c in cars if int(c.get("violation_count", 0) or 0) <= int(violation_max)]
    if parking_max:
        cars = [c for c in cars if float(c.get("parking_fee", 0) or 0) <= float(parking_max)]
    if repair_max:
        cars = [c for c in cars if float(c.get("repair_fee", 0) or 0) <= float(repair_max)]
    if deposit_max:
        cars = [c for c in cars if float(c.get("deposit", 0) or 0) <= float(deposit_max)]
    if extra_fee_max:
        cars = [c for c in cars if float(c.get("total_extra_fee", 0) or 0) <= float(extra_fee_max)]
    if mileage_max:
        cars = [c for c in cars if c.get("mileage") and float(c.get("mileage", 0)) <= float(mileage_max)]

    # Sort
    sort_by = flask.request.args.get("sort", "final_price")
    sort_dir = flask.request.args.get("dir", "asc")
    
    sort_keys = [k.strip() for k in sort_by.split(",") if k.strip()]
    sort_dirs = [d.strip().lower() for d in sort_dir.split(",")]
    while len(sort_dirs) < len(sort_keys):
        sort_dirs.append("asc")
    
    def sort_key(c):
        result = []
        for i, key in enumerate(sort_keys):
            val = c.get(key, "")
            try:
                num = float(val) if val else 0
            except (ValueError, TypeError):
                num = 0
            if sort_dirs[i] == "desc":
                result.append(-num)
            else:
                result.append(num)
        return result
    
    cars.sort(key=sort_key)

    # Build filter options (unique values for dropdowns)
    all_cars = load_car_details()
    options = {
        "brands": sorted(set(c["_brand"] for c in all_cars if c.get("_brand"))),
        "courts": sorted(set(c["court"] for c in all_cars if c.get("court"))),
        "fuel_types": sorted(set(c["fuel_type"] for c in all_cars if c.get("fuel_type"))),
        "emissions": sorted(set(c["emission_standard"] for c in all_cars if c.get("emission_standard"))),
    }

    return {
        "total": len(cars),
        "cars": cars,
        "options": options,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
