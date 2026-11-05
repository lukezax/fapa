#!/usr/bin/env python3
"""
下载竞价结果详情页面的所有分页并合并为一个表格 CSV。

用法:
  python3 tools/download_detail.py <zcid>      # 下载指定期次
  python3 tools/download_detail.py all          # 下载所有已知期次
  python3 tools/download_detail.py <zcid> --no-download  # 仅从缓存合并 CSV

API: POST https://jpxkc.cbex.com/page/jpxkc/info/jggs_detail_datas
     params: zcid={id}&isShowName=true&pageSize=10&pageNo={n}
"""

import os
import sys
import re
import csv
import time
import random
import http.cookiejar
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def get_known_zcids():
    return sorted([int(d) for d in os.listdir(DOWNLOADS_DIR) if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))])


KNOWN_ZCIDS = get_known_zcids()

API_URL = "https://jpxkc.cbex.com/page/jpxkc/info/jggs_detail_datas"
HOME_URL = "https://jpxkc.cbex.com/page/jpxkc/info/jggs_detail"
TOKEN = "csjYYpm9vN8Ep07VGj/hcYE666Lg6JzuZJYu/+JatRClqqgOEsBDkot5TWjwS7LGOHBIwg/xGyvFqFVySUgXow=="

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

ACCEPT_LANGS = [
    "zh-CN,zh;q=0.9",
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.8,en;q=0.6",
    "zh-CN,zh;q=0.9,en;q=0.5",
    "zh-CN,zh;q=0.8",
]


def build_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGS),
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": HOME_URL,
        "Connection": "keep-alive",
    }


def make_opener():
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    return opener, cookie_jar


def prewarm_home(opener):
    try:
        req = urllib.request.Request(HOME_URL, headers={"User-Agent": random.choice(USER_AGENTS)})
        resp = opener.open(req, timeout=15)
        resp.read()
        resp.close()
    except Exception:
        pass


def natural_delay(page_no, total_pages):
    if page_no <= 10:
        base = random.uniform(2, 5)
    elif page_no <= 30:
        base = random.uniform(4, 8)
    else:
        base = random.uniform(6, 10)
    # 越靠近末尾越慢一点
    progress = page_no / total_pages
    if progress > 0.8:
        base += random.uniform(1, 3)
    return base


def fetch_page(opener, zcid, page_no, retries=3):
    data = urllib.parse.urlencode({
        "zcid": str(zcid),
        "isShowName": "true",
        "pageSize": "10",
        "pageNo": str(page_no),
    }).encode("utf-8")

    for attempt in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=data, headers=build_headers())
            with opener.open(req, timeout=30) as resp:
                html = resp.read().decode("utf-8")
            return html
        except Exception as e:
            backoff = (2 ** attempt) * random.uniform(1, 3)
            print(f"      [重试 {attempt+1}/{retries}] 第{page_no}页失败: {e}，等待 {backoff:.1f}s")
            time.sleep(backoff)
    return None


def get_total_pages(html):
    # 格式1: totalpage="44"
    m = re.search(r'totalpage\s*=\s*["\']?(\d+)["\']?', html)
    if m:
        return int(m.group(1))
    # 格式2: id="pageNo" ... totalpage="44"
    m = re.search(r'id=["\']pageNo["\'][^>]*totalpage=["\']?(\d+)', html)
    if m:
        return int(m.group(1))
    # 格式3: total: parseInt("541"), 或 total: "541",
    m = re.search(r'total:\s*(?:parseInt\()?["\'](\d+)["\']\)?', html)
    if m:
        total_records = int(m.group(1))
        page_size = 10
        m2 = re.search(r'pageSize:\s*["\']?(\d+)["\']?', html)
        if m2:
            page_size = int(m2.group(1))
        return (total_records + page_size - 1) // page_size
    return 1


def extract_table_rows(html):
    rows = []
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    for tr_match in tr_pattern.finditer(html):
        tr_html = tr_match.group(1)
        if '<th' in tr_html:
            continue
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr_html, re.DOTALL)
        if len(tds) < 8:
            continue

        car_name = re.sub(r'<[^>]+>', '', tds[0]).strip()
        car_link = ''
        link_m = re.search(r'href=["\']([^"\']+)["\']', tds[0])
        if link_m:
            href = link_m.group(1)
            car_link = href if href.startswith('http') else 'https://jpxkc.cbex.com' + href

        item_no = re.sub(r'<[^>]+>', '', tds[1]).strip()
        court = re.sub(r'<[^>]+>', '', tds[2]).strip()
        start_price = re.sub(r'<[^>]+>', '', tds[3]).strip().lstrip('\xa0¥$€\u00a5').replace(',', '')

        code_raw = re.sub(r'<[^>]+>', '', tds[4]).strip()
        code_prefix = re.sub(r'\*', '', code_raw)[:9] if code_raw else ''

        buyer = re.sub(r'<[^>]+>', '', tds[5]).strip()
        status = re.sub(r'<[^>]+>', '', tds[6]).strip()
        final_price = re.sub(r'<[^>]+>', '', tds[7]).strip().lstrip('\xa0¥$€\u00a5').replace(',', '')

        rows.append({
            'car_name': car_name,
            'car_link': car_link,
            'item_no': item_no,
            'court': court,
            'start_price': start_price,
            'code': code_prefix,
            'buyer': buyer,
            'status': status,
            'final_price': final_price,
        })
    return rows


def download_all_pages(zcid, skip_download=False):
    zcid_dir = os.path.join(DOWNLOADS_DIR, str(zcid))
    detail_dir = os.path.join(zcid_dir, "detail")
    os.makedirs(detail_dir, exist_ok=True)

    if skip_download:
        print(f"  [跳过下载] zcid={zcid}")
    else:
        print(f"  [下载] zcid={zcid}")

        opener, _ = make_opener()
        prewarm_home(opener)

        first_html = fetch_page(opener, zcid, 1)
        if not first_html:
            print(f"    ✗ 无法获取第一页，跳过")
            return
        total_pages = get_total_pages(first_html)
        print(f"    总页数: {total_pages}")

        with open(os.path.join(detail_dir, "page_1.html"), "w", encoding="utf-8") as f:
            f.write(first_html)

        for page in range(2, total_pages + 1):
            html = fetch_page(opener, zcid, page)
            if html:
                with open(os.path.join(detail_dir, f"page_{page}.html"), "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"    ✓ 第{page}/{total_pages}页", end="\r" if page < total_pages else "\n")
            else:
                print(f"    ✗ 第{page}页失败")

            delay = natural_delay(page, total_pages)
            time.sleep(delay)

    print(f"  [合并] zcid={zcid}")
    all_rows = []
    html_files = sorted(
        [f for f in os.listdir(detail_dir) if f.startswith("page_") and f.endswith(".html")],
        key=lambda f: int(re.search(r'page_(\d+)', f).group(1))
    )

    if not html_files:
        print(f"    ✗ 没有缓存页面")
        return

    for fname in html_files:
        fpath = os.path.join(detail_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            html = f.read()
        rows = extract_table_rows(html)
        all_rows.extend(rows)

    csv_path = os.path.join(zcid_dir, "result_detail.csv")
    fieldnames = ["car_name", "car_link", "item_no", "court", "start_price",
                  "code", "buyer", "status", "final_price"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"    ✓ 合并完成: {csv_path} ({len(all_rows)} 条记录)")
    return all_rows


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid|all> [--no-download]")
        sys.exit(1)

    arg = sys.argv[1]
    skip_download = "--no-download" in sys.argv

    if arg == "all":
        zcids = KNOWN_ZCIDS
    else:
        zcids = [int(arg)]

    for i, zcid in enumerate(zcids, 1):
        download_all_pages(zcid, skip_download=skip_download)
        if not skip_download and i < len(zcids):
            rest = random.uniform(15, 40)
            print(f"    [休息 {rest:.0f}s 后处理下一个]")
            time.sleep(rest)


if __name__ == "__main__":
    main()
