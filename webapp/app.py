import os
import csv
import math
import sys
import re
from collections import Counter, defaultdict

import flask

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
sys.path.insert(0, BASE_DIR)

from tools.brand import extract_brand  # noqa: E402


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


ALL_ZCIDS = get_all_zcids()
# 本期在售（车辆筛选/推荐车型来源）
CURRENT_ZCID = max(ALL_ZCIDS) if ALL_ZCIDS else 2464
CURRENT_PERIOD = {2464: "202611期"}.get(CURRENT_ZCID, f"{CURRENT_ZCID}期")
# 排名资格池（最新一期有竞买人名单的期次）
POOL_ZCID = get_latest_pool_zcid(ALL_ZCIDS)

GSXX_PATH = os.path.join(DOWNLOADS_DIR, str(POOL_ZCID), f"gsxx_{POOL_ZCID}.csv")
WINNER_PATH = os.path.join(DOWNLOADS_DIR, "winner_profiles.csv")

app = flask.Flask(__name__)


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
    periods_order = [str(z) for z in ALL_ZCIDS]
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
    # 匹配窗口：用户分位 ±N 个百分点（默认 ±10%）
    try:
        window_pct = min(50.0, max(1.0, float(data.get("window_pct", 10))))
    except (TypeError, ValueError):
        window_pct = 10.0

    if not times or not reg_time:
        return {"error": "请填写次数和注册时间"}, 400

    try:
        reg_normalised = normalise_reg_time_input(reg_time)
        rank = compute_rank(times, reg_normalised)
    except Exception as e:
        return {"error": f"参数错误: {e}"}, 400

    user_pct = rank / GSXX_TOTAL * 100

    pct_low = max(0.0, user_pct - window_pct)
    pct_high = min(100.0, user_pct + window_pct)
    history_periods = len({w["result_zcid"] for w in winner_pool})

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

        # 本期成功率（档位级）= 同分位人群买到该档位车的期次覆盖率
        cover_rate = round(periods_covered / history_periods * 1000) / 10 if history_periods else 0
        success_rate = cover_rate

        if success_rate >= 75:
            recommendation = "强烈推荐"
        elif success_rate >= 55:
            recommendation = "推荐"
        elif success_rate >= 35:
            recommendation = "可考虑"
        else:
            recommendation = "观望"

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
            "success_rate": success_rate,
            "cover_rate": cover_rate,
            "avg_final_price": avg_final,
            "avg_deal_ratio": avg_deal,
            "difficulty": difficulty,
            "periods_covered": periods_covered,
            "top_brands": top_brands,
            "top5": top5,
            "all_matches": all_matches,
        })

    # 按成功率降序，同成功率按同分位样本数降序
    panorama_list.sort(key=lambda x: (-x["success_rate"], -x["match_count"]))

    # 本期在售：每个档位取起拍价落在区间内的车，升序取 5
    def bracket_range(bk):
        m = re.match(r"^(\d+)-(\d+)万$", str(bk or ""))
        if not m:
            return None
        return int(m.group(1)) * 10000, int(m.group(2)) * 10000

    current_cars_by_bracket = {}
    for p in panorama_list:
        rng = bracket_range(p["bracket"])
        if not rng:
            current_cars_by_bracket[p["bracket"]] = []
            continue
        lo, hi = rng
        matched = []
        for c in current_cars_pool:
            sp = c.get("start_price")
            try:
                spv = float(sp)
            except (TypeError, ValueError):
                continue
            if lo <= spv < hi:
                r = p.get("avg_deal_ratio") or 0
                # 历史同分位同档溢价对应的目标出价 = 起拍价 × 历史平均溢价
                predicted = round(spv * r) if r > 0 else None
                limit_raw = c.get("limit_price")
                try:
                    limit_v = float(limit_raw) if limit_raw not in (None, "") else None
                except (TypeError, ValueError):
                    limit_v = None
                # 建议出价 = min(最高限价, 目标出价)；限价封顶时成功率按可达度打折
                if predicted is not None and limit_v is not None:
                    suggested = min(limit_v, predicted)
                else:
                    suggested = predicted
                if predicted:
                    car_success = round(p.get("success_rate", 0) * (suggested / predicted))
                else:
                    car_success = None
                matched.append({
                    "car_name": c.get("car_name", ""),
                    "car_link": c.get("car_link", ""),
                    "start_price": c.get("start_price", ""),
                    "limit_price": c.get("limit_price", ""),
                    "mileage": c.get("mileage", ""),
                    "fuel_type": c.get("fuel_type", ""),
                    "brand": c.get("_brand", ""),
                    "predicted_final_price": predicted,
                    "suggested_bid": suggested,
                    "capped": bool(predicted is not None and limit_v is not None and predicted >= limit_v),
                    "success_rate": car_success,
                })
        matched.sort(key=lambda x: float(x["start_price"] or 0))
        current_cars_by_bracket[p["bracket"]] = matched[:5]

    for p in panorama_list:
        p["current_cars"] = current_cars_by_bracket.get(p["bracket"], [])
        p["current_period"] = CURRENT_PERIOD
        p["current_zcid"] = CURRENT_ZCID
        p["recommend_reason"] = (
            f"历史 {p['periods_covered']}/{history_periods} 期有同分位成交此档位，"
            f"本期成功率约 {p['success_rate']}%"
            if p["periods_covered"] > 0 else ""
        )

    periods_order = [str(z) for z in ALL_ZCIDS]
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
        "latest_zcid": POOL_ZCID,
        "current_zcid": CURRENT_ZCID,
        "current_period": CURRENT_PERIOD,
        "window_pct": window_pct,
        "peer_count": total_matches,
        "sample_insufficient": total_matches < 30,
        "history_periods": history_periods,
    }


# ── Car detail data ──
# ── Car detail data ──
CAR_DETAILS_PATH = os.path.join(DOWNLOADS_DIR, str(CURRENT_ZCID), "car_details_llm.csv")
MILEAGE_PATH = os.path.join(DOWNLOADS_DIR, str(CURRENT_ZCID), "mileage.csv")
LIMIT_PATH = os.path.join(DOWNLOADS_DIR, str(CURRENT_ZCID), "limit_prices.csv")


def load_limit_prices():
    limits = {}
    if os.path.exists(LIMIT_PATH):
        with open(LIMIT_PATH, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                link = row.get("car_link", "")
                val = row.get("limit_price", "")
                if link and val:
                    try:
                        limits[link] = float(val)
                    except ValueError:
                        pass
    return limits


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

    limit_map = load_limit_prices()
    for row in rows:
        link = row.get("car_link", "")
        if link in mileage_map:
            row["mileage"] = mileage_map[link]
        row["limit_price"] = limit_map.get(link, "")

    return rows


# 本期在售车辆池（202611期）：只用于推荐与筛选，历史期次不进入
current_cars_pool = load_car_details()


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
    sort_by = flask.request.args.get("sort", "start_price")
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
        "current_zcid": CURRENT_ZCID,
        "current_period": CURRENT_PERIOD,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
