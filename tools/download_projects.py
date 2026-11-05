#!/usr/bin/env python3
"""
下载项目页标的列表（竞价开始前、结果公示尚无数据时使用）。

用法:
  python3 tools/download_projects.py 2464
  python3 tools/download_projects.py 2464 --limit 3   # 试跑前3条

输出: downloads/{zcid}/result_detail.csv
      字段与 download_detail.py 完全一致（court 为空，由 download_survey.py
      抓详情页时回填）；竞价结束后重跑 download_detail.py 会用真实成交
      结果整表覆盖，无缝衔接。
      另存 downloads/{zcid}/limit_prices.csv（最高限价，供参考）。
"""

import os
import sys
import re
import csv
import time
import html
import random
import http.cookiejar
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")

API_URL = "https://jpxkc.cbex.com/page/jpxkc/zc_prjs/prj_li"
REFERER_TPL = "https://jpxkc.cbex.com/jpxkc/zc_prjs/{zcid}.html"
ITEM_PREFIX = "https://jpxkc.cbex.com"
PAGE_SIZE = 16

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def build_headers(zcid):
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": REFERER_TPL.format(zcid=zcid),
        "Connection": "keep-alive",
    }


def make_opener():
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))


def fetch_page(opener, zcid, page_no, retries=3):
    data = urllib.parse.urlencode({
        "id": str(zcid),
        "sortTag": "0",
        "keyWord": "",
        "pageNo": str(page_no),
        "pageSize": str(PAGE_SIZE),
    }).encode("utf-8")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=data, headers=build_headers(zcid))
            with opener.open(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            backoff = (2 ** attempt) * random.uniform(1, 3)
            print(f"  [重试 {attempt + 1}/{retries}] 第{page_no}页失败: {e}，等待 {backoff:.1f}s")
            time.sleep(backoff)
    return None


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).strip()


def clean_price(s):
    return s.replace(",", "").replace("¥", "").strip()


def extract_items(page_html):
    items = []
    for m in re.finditer(r'<li id="prj_li_\d+"[^>]*>(.*?)</li>', page_html, re.DOTALL):
        block = m.group(1)

        link_m = re.search(r'href=["\'](/jpxkc/prj/detail/\d+\.html)["\']', block)
        if not link_m:
            continue
        car_link = ITEM_PREFIX + link_m.group(1)

        title_m = re.search(r'<a class="title"[^>]*>(.*?)</a>', block, re.DOTALL)
        car_name = html.unescape(strip_tags(title_m.group(1))) if title_m else ""

        start_m = re.search(r'起始价[：:]\s*(?:<[^>]+>\s*)*¥?\s*([\d,.]+)', block)
        start_price = clean_price(start_m.group(1)) if start_m else ""

        item_m = re.search(r'标的物编号[：:]\s*([^<\n]+)', block)
        item_no = html.unescape(item_m.group(1).strip()) if item_m else ""

        limit_m = re.search(r'最高限价[：:]\s*(?:<[^>]+>\s*)*¥?\s*([\d,.]+)', block)
        limit_price = clean_price(limit_m.group(1)) if limit_m else ""

        state_m = re.search(r'<span class="label_state_\w+">([^<]+)</span>', block)
        status = strip_tags(state_m.group(1)) if state_m else ""

        items.append({
            "car_link": car_link,
            "car_name": car_name,
            "start_price": start_price,
            "item_no": item_no,
            "limit_price": limit_price,
            "status": status,
        })
    return items


def get_total(page_html):
    m = re.search(r'total:\s*["\']?(\d+)', page_html)
    return int(m.group(1)) if m else 0


def load_existing_courts(csv_path):
    courts = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("car_link") and row.get("court"):
                    courts[row["car_link"]] = row["court"]
    return courts


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid> [--limit N]")
        sys.exit(1)

    zcid = sys.argv[1]
    limit = 0
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    zcid_dir = os.path.join(DOWNLOADS_DIR, zcid)
    os.makedirs(zcid_dir, exist_ok=True)
    csv_path = os.path.join(zcid_dir, "result_detail.csv")
    limit_csv_path = os.path.join(zcid_dir, "limit_prices.csv")

    opener = make_opener()

    first_html = fetch_page(opener, zcid, 1)
    if not first_html:
        print("✗ 无法获取第1页")
        sys.exit(1)

    total = get_total(first_html)
    if total == 0 and "暂无数据" in first_html:
        print("✗ 该期暂无数据（可能尚未发布标的）")
        sys.exit(1)

    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 1
    print(f"期次 {zcid}: 标的 {total} 件，共 {pages} 页")

    all_items = extract_items(first_html)
    for page in range(2, pages + 1):
        if limit and len(all_items) >= limit:
            break
        page_html = fetch_page(opener, zcid, page)
        if page_html:
            items = extract_items(page_html)
            all_items.extend(items)
            print(f"  ✓ 第 {page}/{pages} 页（累计 {len(all_items)} 条）")
        else:
            print(f"  ✗ 第 {page} 页失败")
        time.sleep(random.uniform(2, 5))

    # 去重（以 car_link 为准）
    seen = set()
    deduped = []
    for it in all_items:
        if it["car_link"] in seen:
            continue
        seen.add(it["car_link"])
        deduped.append(it)
    all_items = deduped

    if limit:
        all_items = all_items[:limit]

    # 保留旧表中的 court（download_survey 回填后重跑本脚本不丢法院）
    courts = load_existing_courts(csv_path)

    fieldnames = ["car_name", "car_link", "item_no", "court", "start_price",
                  "code", "buyer", "status", "final_price"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for it in all_items:
            writer.writerow({
                "car_name": it["car_name"],
                "car_link": it["car_link"],
                "item_no": it["item_no"],
                "court": courts.get(it["car_link"], ""),
                "start_price": it["start_price"],
                "code": "",
                "buyer": "",
                "status": it["status"],
                "final_price": "",
            })

    with open(limit_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["car_link", "limit_price"])
        writer.writeheader()
        for it in all_items:
            writer.writerow({"car_link": it["car_link"], "limit_price": it["limit_price"]})

    print(f"\n完成: {len(all_items)} 条 → {csv_path}")
    print(f"      最高限价 → {limit_csv_path}")


if __name__ == "__main__":
    main()
