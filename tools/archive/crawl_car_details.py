#!/usr/bin/env python3
"""
爬取指定期次所有车辆的详情页，提取标的物调查情况表中的结构化字段。

用法:
  python3 tools/crawl_car_details.py 2400              # 爬取2400期
  python3 tools/crawl_car_details.py 2400 --no-download # 仅从缓存解析
  python3 tools/crawl_car_details.py 2400 --limit 10   # 只爬前10辆(测试用)

输出: downloads/{zcid}/car_details.csv
缓存: downloads/{zcid}/detail_pages/
"""

import os
import sys
import re
import csv
import time
import random
import html
import http.cookiejar
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")

HOME_URL = "https://jpxkc.cbex.com/page/jpxkc/info/jggs_detail"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]


def build_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }


def make_opener():
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def fetch_page(url, opener, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=build_headers())
            with opener.open(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            backoff = (2 ** attempt) * random.uniform(1, 3)
            print(f"      [重试 {attempt+1}/{retries}] {e}，等待 {backoff:.1f}s")
            time.sleep(backoff)
    return None


def extract_field(text, pattern, group=1, default=""):
    m = re.search(pattern, text)
    if m:
        return m.group(group).strip()
    return default


def extract_yes_no(text, keyword):
    """提取 有/无 字段，兼容多种格式:
    - 机动车行驶证（有）
    - 机动车行驶证   有
    - 1、机动车行驶证    有
    """
    m = re.search(keyword + r'\s*[（(]?\s*(有|无)\s*[）)]?', text)
    if m:
        return m.group(1)
    return ""


def extract_survey_section(html_text):
    m = re.search(r'标的物调查情况表(.+?)(?:竞买须知|图片展示)', html_text, re.DOTALL)
    if m:
        raw = m.group(1)
        raw = html.unescape(raw)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw
    return ""


def parse_detail_html(html_text):
    html_text = html.unescape(html_text)
    text = re.sub(r'<[^>]+>', ' ', html_text)
    text = re.sub(r'\s+', ' ', text)

    result = {}

    result["raw_survey"] = extract_survey_section(html.unescape(html_text))

    result["has_license"] = extract_yes_no(text, r'机动车行驶证')
    result["has_registration"] = extract_yes_no(text, r'机动车登记证')
    result["has_plate"] = extract_yes_no(text, r'车牌\s')

    result["use_type"] = extract_field(text, r'使用性质\s*(.+?)\s*钥匙')

    result["has_key"] = extract_field(text, r'钥匙\s*(有|无)')

    result["preview_location"] = extract_field(text, r'预展地点[：:]\s*(.+?)(?:。|权利限制)')

    # 违章: 兼容 "13  起，0  分， 1300  元" 等多余空格
    violation = re.search(
        r'违章记录[：:]\s*(\d+)\s*起\s*[，,]?\s*(\d+)\s*分\s*[，,]?\s*([\d.]+)\s*元',
        text
    )
    if violation:
        result["violation_count"] = int(violation.group(1))
        result["violation_points"] = int(violation.group(2))
        result["violation_fine"] = float(violation.group(3))
    elif re.search(r'违章记录[：:].{0,15}(无|没有)', text):
        result["violation_count"] = 0
        result["violation_points"] = 0
        result["violation_fine"] = 0
    else:
        result["violation_count"] = ""
        result["violation_points"] = ""
        result["violation_fine"] = ""

    # 抵押: 兼容 "是/否" 和 "有抵押/无抵押"
    mortgage_raw = extract_field(text, r'(?:是否)?抵押[：:]\s*(.+?)(?:[（(]|如有|，|$)')
    if any(k in mortgage_raw for k in ('是', '有抵押', '已抵押', '已')):
        result["is_mortgaged"] = "是"
    elif any(k in mortgage_raw for k in ('否', '无抵押', '未抵押', '无', '未')):
        result["is_mortgaged"] = "否"
    else:
        result["is_mortgaged"] = ""

    # 停车费、维修费: 先尝试分项，再尝试合并格式
    parking = re.search(r'停车费\s*([\d,.]+)\s*元', text)
    repair = re.search(r'维修费\s*([\d,.]+)\s*元', text)
    if parking:
        result["parking_fee"] = float(parking.group(1).replace(',', ''))
    else:
        result["parking_fee"] = 0
    if repair:
        result["repair_fee"] = float(repair.group(1).replace(',', ''))
    else:
        result["repair_fee"] = 0

    # 合并格式: "停车、维修等费用： 5902  元"
    combined_fee = re.search(r'停车\s*[、，,]?\s*维修等?费用[：:]\s*([\d,.]+)\s*元', text)
    if combined_fee and not parking and not repair:
        result["total_extra_fee"] = float(combined_fee.group(1).replace(',', ''))
    else:
        total_match = re.search(r'共计\s*([\d,.]+)\s*元', text)
        if total_match:
            result["total_extra_fee"] = float(total_match.group(1).replace(',', ''))
        else:
            result["total_extra_fee"] = result["parking_fee"] + result["repair_fee"]

    result["first_reg_date"] = extract_field(text, r'初次登记日期[：:]\s*(.+?)(?:\s*2\s*、|里程)')

    result["inspection_expiry"] = extract_field(text, r'检验有效期止日期[：:]\s*(.+?)(?:[（(]|$)')

    result["vehicle_model"] = extract_field(text, r'车辆型号[：:]\s*(\S+)')

    result["fuel_type"] = extract_field(text, r'燃料种类[：:]\s*(.+?)(?:\s*9\s*、|$)')

    # 排放标准: 兼容 国五/国六/国Ⅴ/国Ⅵ 等
    result["emission_standard"] = extract_field(text, r'排放标准[：:]\s*(国\s*[一二三四五六ⅠⅡⅢⅣⅤⅥ]+[\u4e00-\u9fff]*)')

    appraisal = re.search(r'评估价[：:]\s*¥?\s*([\d,]+\.?\d*)', text)
    result["appraisal_price"] = float(appraisal.group(1).replace(',', '')) if appraisal else ""

    deposit = re.search(r'保证金[：:]\s*¥?\s*([\d,]+\.?\d*)', text)
    result["deposit"] = float(deposit.group(1).replace(',', '')) if deposit else ""

    return result


def crawl_period(zcid, skip_download=False, limit=0):
    zcid_dir = os.path.join(DOWNLOADS_DIR, str(zcid))
    detail_csv = os.path.join(zcid_dir, "result_detail.csv")
    cache_dir = os.path.join(zcid_dir, "detail_pages")
    survey_dir = os.path.join(zcid_dir, "survey_texts")
    output_csv = os.path.join(zcid_dir, "car_details.csv")

    if not os.path.exists(detail_csv):
        print(f"错误: {detail_csv} 不存在，请先运行 download_detail.py")
        return

    # 读取车辆列表
    cars = []
    with open(detail_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cars.append(row)

    if limit > 0:
        cars = cars[:limit]

    print(f"期次 {zcid}: 共 {len(cars)} 辆车")
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(survey_dir, exist_ok=True)

    opener = make_opener()

    # 预热
    if not skip_download:
        try:
            req = urllib.request.Request(HOME_URL, headers={"User-Agent": random.choice(USER_AGENTS)})
            opener.open(req, timeout=15).read()
        except Exception:
            pass

    fieldnames = [
        "car_name", "car_link", "item_no", "court", "start_price", "final_price", "status",
        "has_license", "has_registration", "has_plate", "use_type", "has_key",
        "preview_location", "violation_count", "violation_points", "violation_fine",
        "is_mortgaged", "parking_fee", "repair_fee", "total_extra_fee",
        "first_reg_date", "inspection_expiry", "vehicle_model",
        "fuel_type", "emission_standard", "appraisal_price", "deposit",
    ]

    results = []
    for i, car in enumerate(cars, 1):
        link = car.get("car_link", "")
        if not link:
            continue

        slug = link.rstrip("/").split("/")[-1].replace(".html", "")
        cache_path = os.path.join(cache_dir, f"{slug}.html")

        print(f"  [{i}/{len(cars)}] {car['car_name'][:30]}...", end=" ")

        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                html = f.read()
            print("(缓存)")
        elif skip_download:
            print("(跳过，无缓存)")
            continue
        else:
            html = fetch_page(link, opener)
            if html:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(html)
                print("✓")
            else:
                print("✗ 失败")
                continue

            # 随机延迟
            delay = random.uniform(1.5, 4.0)
            if i > 20:
                delay += random.uniform(0.5, 2.0)
            time.sleep(delay)

        detail = parse_detail_html(html)

        if detail.get("raw_survey"):
            survey_path = os.path.join(survey_dir, f"{slug}.txt")
            if not os.path.exists(survey_path):
                with open(survey_path, "w", encoding="utf-8") as f:
                    f.write(detail["raw_survey"])

        row = {
            "car_name": car.get("car_name", ""),
            "car_link": link,
            "item_no": car.get("item_no", ""),
            "court": car.get("court", ""),
            "start_price": car.get("start_price", ""),
            "final_price": car.get("final_price", ""),
            "status": car.get("status", ""),
        }
        row.update(detail)
        row.pop("raw_survey", None)
        results.append(row)

    # 写入 CSV
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n完成: {len(results)}/{len(cars)} 辆车 → {output_csv}")


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid> [--no-download] [--limit N]")
        sys.exit(1)

    zcid = int(sys.argv[1])
    skip_download = "--no-download" in sys.argv

    limit = 0
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    crawl_period(zcid, skip_download=skip_download, limit=limit)


if __name__ == "__main__":
    main()
