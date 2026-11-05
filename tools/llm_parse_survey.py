#!/usr/bin/env python3
"""
使用 LLM (OpenAI 兼容 API) 解析标的物调查情况表，提取结构化字段。

用法:
  python3 tools/llm_parse_survey.py 2400
  python3 tools/llm_parse_survey.py 2400 --limit 10
  python3 tools/llm_parse_survey.py 2400 --force

配置: tools/llm_config.json

输出: downloads/{zcid}/car_details_llm.csv
"""

import os
import sys
import json
import csv
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
CONFIG_PATH = os.path.join(BASE_DIR, "tools", "llm_config.json")

EXTRACT_FIELDS = """从以下标的物调查情况表中提取结构化信息，以 JSON 格式返回。

要求：
1. 只返回 JSON，不要其他文字
2. 字段缺失时返回空字符串 ""
3. 数字字段返回数字类型（不带引号）
4. 费用字段如果合并描述（如"停车、维修等费用：5902元"），填入 total_extra_fee，parking_fee 和 repair_fee 留空
5. 排放标准统一为：国一/国二/国三/国四/国五/国六（罗马数字转为中文数字）

字段说明：
{
  "has_license": "有/无 (行驶证)",
  "has_registration": "有/无 (登记证)",
  "has_plate": "有/无 (车牌)",
  "use_type": "使用性质 (如: 非营运)",
  "has_key": "有/无 (钥匙)",
  "preview_location": "预展地点完整地址",
  "violation_count": 违章起数(数字),
  "violation_points": 违章扣分(数字),
  "violation_fine": 违章罚款金额(数字),
  "is_mortgaged": "是/否 (是否抵押)",
  "parking_fee": 停车费(数字),
  "repair_fee": 维修费(数字),
  "total_extra_fee": 额外费用合计(数字),
  "first_reg_date": "初次登记日期 (如: 2019年8月6日)",
  "inspection_expiry": "检验有效期止日期",
  "vehicle_model": "车辆型号",
  "fuel_type": "燃料种类 (如: 汽油)",
  "emission_standard": "排放标准 (如: 国五)",
  "appraisal_price": 评估价(数字),
  "deposit": 保证金(数字),
  "mileage": 行驶里程数(数字，单位公里。如文本写"5.23万公里"请转换为52300，如写"见图片展示"或未提及则返回空字符串"")
}

标的物调查情况表：
"""


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"错误: 配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def call_llm(config, survey_text):
    url = f"{config['api_base'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config["model"],
        "temperature": config.get("temperature", 0),
        "max_tokens": config.get("max_tokens", 2000),
        # 思考型模型：关闭思考，否则 reasoning 吞掉输出 token
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": "你是一个数据提取助手，只返回 JSON。"},
            {"role": "user", "content": EXTRACT_FIELDS + survey_text},
        ],
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    return json.loads(content)


def normalize_mileage(result):
    val = result.get("mileage", "")
    if not val:
        return
    if isinstance(val, (int, float)):
        return
    s = str(val).strip()
    if "万" in s:
        try:
            num = float(s.replace("万公里", "").replace("万", "").replace("km", "").replace("公里", "").strip())
            result["mileage"] = int(num * 10000)
        except ValueError:
            result["mileage"] = ""
    else:
        try:
            result["mileage"] = int(float(s.replace("公里", "").replace("km", "").strip()))
        except ValueError:
            result["mileage"] = ""


def process_one(slug, survey_dir, config, force=False, output_dir=None):
    survey_path = os.path.join(survey_dir, f"{slug}.txt")
    if not os.path.exists(survey_path):
        return slug, None, "missing"

    cache_path = os.path.join(output_dir or survey_dir, f"{slug}.json")
    if os.path.exists(cache_path) and not force:
        with open(cache_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        normalize_mileage(result)
        return slug, result, "cached"

    with open(survey_path, "r", encoding="utf-8") as f:
        text = f.read()

    if not text.strip():
        return slug, None, "empty"

    try:
        result = call_llm(config, text)
        normalize_mileage(result)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return slug, result, "ok"
    except Exception as e:
        return slug, None, f"error: {e}"


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid> [--limit N] [--force]")
        sys.exit(1)

    zcid = sys.argv[1]
    force = "--force" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    config = load_config()
    print(f"API: {config['api_base']}")
    print(f"Model: {config['model']}")

    zcid_dir = os.path.join(DOWNLOADS_DIR, zcid)
    survey_dir = os.path.join(zcid_dir, "survey_texts")
    detail_csv = os.path.join(zcid_dir, "result_detail.csv")
    output_csv = os.path.join(zcid_dir, "car_details_llm.csv")

    if not os.path.exists(survey_dir):
        print(f"错误: {survey_dir} 不存在，请先运行 download_survey.py")
        sys.exit(1)

    if not os.path.exists(detail_csv):
        print(f"错误: {detail_csv} 不存在")
        sys.exit(1)

    cars = []
    with open(detail_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cars.append(row)

    if limit > 0:
        cars = cars[:limit]

    slugs = []
    for car in cars:
        link = car.get("car_link", "")
        if link:
            slug = link.rstrip("/").split("/")[-1].replace(".html", "")
            slugs.append(slug)

    print(f"期次 {zcid}: 共 {len(slugs)} 辆车待处理")
    print(f"并发: {config.get('concurrency', 3)}")

    fieldnames = [
        "car_name", "car_link", "item_no", "court", "start_price", "final_price", "status",
        "has_license", "has_registration", "has_plate", "use_type", "has_key",
        "preview_location", "violation_count", "violation_points", "violation_fine",
        "is_mortgaged", "parking_fee", "repair_fee", "total_extra_fee",
        "first_reg_date", "inspection_expiry", "vehicle_model",
        "fuel_type", "emission_standard", "appraisal_price", "deposit", "mileage",
    ]

    slug_to_car = {}
    for car in cars:
        link = car.get("car_link", "")
        if link:
            slug = link.rstrip("/").split("/")[-1].replace(".html", "")
            slug_to_car[slug] = car

    results = []
    stats = {"ok": 0, "cached": 0, "error": 0, "missing": 0, "empty": 0}
    concurrency = config.get("concurrency", 3)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(process_one, slug, survey_dir, config, force, survey_dir): slug
            for slug in slugs
        }

        for i, future in enumerate(as_completed(futures), 1):
            slug, llm_result, status = future.result()
            cat = status.split(":")[0] if ":" in status else status
            stats[cat] = stats.get(cat, 0) + 1

            car = slug_to_car.get(slug, {})
            row = {
                "car_name": car.get("car_name", ""),
                "car_link": car.get("car_link", ""),
                "item_no": car.get("item_no", ""),
                "court": car.get("court", ""),
                "start_price": car.get("start_price", ""),
                "final_price": car.get("final_price", ""),
                "status": car.get("status", ""),
            }

            if llm_result:
                for k in fieldnames:
                    if k in row:
                        continue
                    val = llm_result.get(k, "")
                    row[k] = val if val is not None else ""

            results.append(row)

            if i % 10 == 0 or i == len(slugs):
                print(f"  [{i}/{len(slugs)}] ok={stats['ok']} cached={stats['cached']} error={stats['error']}")

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n完成: {len(results)} 辆 → {output_csv}")
    print(f"统计: ok={stats['ok']} cached={stats['cached']} error={stats['error']} missing={stats['missing']} empty={stats['empty']}")


if __name__ == "__main__":
    main()
