#!/usr/bin/env python3
"""
从缓存的 HTML 页面中提取标的物调查情况表原始文本，保存为 .txt 文件。

用法:
  python3 tools/extract_survey_texts.py 2400

输出: downloads/{zcid}/survey_texts/{slug}.txt
"""

import os
import sys
import re
import csv
import html

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def extract_survey_text(html_text):
    html_text = html.unescape(html_text)
    m = re.search(r'标的物调查情况表(.+?)(?:竞买须知|图片展示)', html_text, re.DOTALL)
    if m:
        raw = m.group(1)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw
    return ""


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid>")
        sys.exit(1)

    zcid = sys.argv[1]
    zcid_dir = os.path.join(DOWNLOADS_DIR, zcid)
    detail_csv = os.path.join(zcid_dir, "result_detail.csv")
    cache_dir = os.path.join(zcid_dir, "detail_pages")
    survey_dir = os.path.join(zcid_dir, "survey_texts")

    if not os.path.exists(detail_csv):
        print(f"错误: {detail_csv} 不存在")
        sys.exit(1)

    os.makedirs(survey_dir, exist_ok=True)

    cars = []
    with open(detail_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cars.append(row)

    extracted = 0
    skipped = 0
    missing = 0

    for i, car in enumerate(cars, 1):
        link = car.get("car_link", "")
        if not link:
            continue

        slug = link.rstrip("/").split("/")[-1].replace(".html", "")
        cache_path = os.path.join(cache_dir, f"{slug}.html")
        survey_path = os.path.join(survey_dir, f"{slug}.txt")

        if not os.path.exists(cache_path):
            missing += 1
            continue

        if os.path.exists(survey_path):
            skipped += 1
            continue

        with open(cache_path, "r", encoding="utf-8") as f:
            html_text = f.read()

        text = extract_survey_text(html_text)
        if text:
            with open(survey_path, "w", encoding="utf-8") as f:
                f.write(text)
            extracted += 1
        else:
            missing += 1

    print(f"完成: 提取 {extracted} 个, 已存在 {skipped} 个, 缺失 {missing} 个")
    print(f"输出目录: {survey_dir}")


if __name__ == "__main__":
    main()
