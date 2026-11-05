#!/usr/bin/env python3
"""
下载车辆详情页，提取标的物调查情况表文本，保存为 .txt。

用法:
  python3 tools/download_survey.py 2400
  python3 tools/download_survey.py 2400 --limit 10
  python3 tools/download_survey.py 2400 --force

输出: downloads/{zcid}/survey_texts/{slug}.txt
已有缓存的自动跳过（断点续传），--force 强制重新提取。
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


def extract_price_info(html_text):
    html_text = html.unescape(html_text)
    result = []
    appraisal = re.search(r'评估价[：:]\s*¥?\s*([\d,]+\.?\d*)', html_text)
    if appraisal:
        result.append(f"评估价：{appraisal.group(1)}元")
    deposit = re.search(r'保证金[：:]\s*¥?\s*([\d,]+\.?\d*)', html_text)
    if deposit:
        result.append(f"保证金：{deposit.group(1)}元")
    return " ".join(result)


def extract_survey_text(html_text):
    html_text = html.unescape(html_text)
    m = re.search(r'标的物调查情况表(.+?)(?:竞买须知)', html_text, re.DOTALL)
    if not m:
        m = re.search(r'标的物调查情况表(.+)', html_text, re.DOTALL)
    if m:
        raw = m.group(1)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        price_info = extract_price_info(html_text)
        if price_info:
            raw = raw + " " + price_info
        return raw
    return ""


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid> [--limit N]")
        sys.exit(1)

    zcid = sys.argv[1]
    limit = 0
    force = "--force" in sys.argv
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    zcid_dir = os.path.join(DOWNLOADS_DIR, zcid)
    detail_csv = os.path.join(zcid_dir, "result_detail.csv")
    survey_dir = os.path.join(zcid_dir, "survey_texts")
    # 兼容旧缓存：detail_pages 目录中可能已有 HTML
    old_cache_dir = os.path.join(zcid_dir, "detail_pages")

    if not os.path.exists(detail_csv):
        print(f"错误: {detail_csv} 不存在，请先运行 download_detail.py")
        sys.exit(1)

    os.makedirs(survey_dir, exist_ok=True)

    cars = []
    with open(detail_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cars.append(row)

    if limit > 0:
        cars = cars[:limit]

    print(f"期次 {zcid}: 共 {len(cars)} 辆车")

    courts = {}
    opener = make_opener()
    try:
        req = urllib.request.Request(HOME_URL, headers={"User-Agent": random.choice(USER_AGENTS)})
        opener.open(req, timeout=15).read()
    except Exception:
        pass

    extracted = 0
    from_cache = 0
    failed = 0

    for i, car in enumerate(cars, 1):
        link = car.get("car_link", "")
        if not link:
            continue

        slug = link.rstrip("/").split("/")[-1].replace(".html", "")
        survey_path = os.path.join(survey_dir, f"{slug}.txt")

        print(f"  [{i}/{len(cars)}] {car['car_name'][:30]}...", end=" ")

        if os.path.exists(survey_path) and not force:
            print("(已有)")
            from_cache += 1
            continue

        # 旧 HTML 缓存可用
        old_html = os.path.join(old_cache_dir, f"{slug}.html")
        if os.path.exists(old_html):
            with open(old_html, "r", encoding="utf-8") as f:
                text = extract_survey_text(f.read())
            if text:
                with open(survey_path, "w", encoding="utf-8") as f:
                    f.write(text)
                print("(从旧缓存提取)")
                from_cache += 1
                continue

        # 需要下载
        html_text = fetch_page(link, opener)
        if not html_text:
            print("✗ 下载失败")
            failed += 1
            continue

        # 顺路提取处置法院（正文首次出现的"XX人民法院"）
        court_m = re.search(r'(北京市?[\u4e00-\u9fa5]{2,12}人民法院)', html_text)
        if court_m:
            courts[link] = court_m.group(1)

        text = extract_survey_text(html_text)
        if text:
            with open(survey_path, "w", encoding="utf-8") as f:
                f.write(text)
            print("✓")
            extracted += 1
        else:
            print("✗ 未找到调查情况表")
            failed += 1

        delay = random.uniform(1.5, 4.0)
        if i > 20:
            delay += random.uniform(0.5, 2.0)
        time.sleep(delay)

    print(f"\n完成: 新下载 {extracted}, 缓存 {from_cache}, 失败 {failed}")
    print(f"输出: {survey_dir}")

    # 回填处置法院到 result_detail.csv（download_projects 生成的空 court）
    if courts:
        with open(detail_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
        patched = 0
        for row in rows:
            if not row.get("court") and row.get("car_link") in courts:
                row["court"] = courts[row["car_link"]]
                patched += 1
        if patched:
            with open(detail_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            print(f"已回填法院 {patched} 条 → {detail_csv}")


if __name__ == "__main__":
    main()
