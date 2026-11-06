#!/usr/bin/env python3
"""
VLM 里程表识别工具 — 从车辆详情页图片中识别里程数。

策略: 并发下载所有图片 → 拼接成 3 列大图 → VLM 识别里程表。

用法:
  export JPXKC_API_KEY='sk-...'
  python3 tools/vlm_mileage.py 2464
  python3 tools/vlm_mileage.py 2464 --concurrency 4
  python3 tools/vlm_mileage.py 2464 --provider fallback
  python3 tools/vlm_mileage.py 2464 --force          # 全部重跑
  python3 tools/vlm_mileage.py 2464 --retry-low      # 重跑 <1万公里 的结果

输入: downloads/{zcid}/result_detail.csv
输出: downloads/{zcid}/mileage.csv (增量更新)
日志: downloads/{zcid}/vlm_log.jsonl
缓存: downloads/{zcid}/car_images/{slug}/
配置: tools/vlm_config.json（端点/模型/并发/超时）
"""

import os
import sys
import re
import csv
import json
import time
import base64
import random
import argparse
import http.cookiejar
import urllib.request
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
CONFIG_PATH = os.path.join(BASE_DIR, "tools", "vlm_config.json")

COL_WIDTH = 400
GRID_PADDING = 4
N_COLS = 3
GRID_QUALITY = 75
MAX_GRID_PIXELS = 2_000_000
DOWNLOAD_WORKERS = 5
DOWNLOAD_TIMEOUT = 30
MAX_VLM_RETRIES = 5


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"错误: 配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_name = config.get("api_key_env", "JPXKC_API_KEY")
    env_key = os.environ.get(env_name, "").strip()
    for name in ("primary", "fallback"):
        provider = config.get(name)
        if not provider:
            continue
        provider["url"] = provider["api_base"].rstrip("/") + "/chat/completions"
        provider["api_key"] = provider.get("api_key") or env_key
    return config


def fetch_page(url, opener, retries=4):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://jpxkc.cbex.com/page/jpxkc/info/jggs_detail",
            })
            with opener.open(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:
            last_err = e
            time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
    raise last_err


def extract_image_urls(html_text):
    html_text = html_text.replace("&amp;", "&")
    all_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
    return [img for img in all_imgs if "/editorUpload/file/" in img]


def download_image(url, save_path, referer, retries=3):
    if os.path.exists(save_path):
        return save_path
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": referer,
            })
            data = urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT).read()
            with open(save_path, "wb") as f:
                f.write(data)
            return save_path
        except Exception as e:
            last_err = e
            time.sleep((2 ** attempt) + random.uniform(0.3, 1.0))
    raise last_err


def stitch_images(img_paths):
    from PIL import Image

    pil_imgs = []
    for path in img_paths:
        if not os.path.exists(path):
            continue
        try:
            img = Image.open(path)
            img.load()
            ratio = COL_WIDTH / img.width
            pil_imgs.append(img.resize((COL_WIDTH, int(img.height * ratio)), Image.LANCZOS))
        except Exception:
            continue

    if not pil_imgs:
        return []

    grid_w = N_COLS * COL_WIDTH + (N_COLS - 1) * GRID_PADDING
    avg_h = sum(img.height for img in pil_imgs) / len(pil_imgs)
    max_rows = max(1, int(MAX_GRID_PIXELS / (grid_w * avg_h)))
    max_per_grid = max_rows * N_COLS

    grids = []
    for start in range(0, len(pil_imgs), max_per_grid):
        batch = pil_imgs[start:start + max_per_grid]
        n_rows = (len(batch) + N_COLS - 1) // N_COLS
        max_row_h = max(img.height for img in batch)
        grid_h = n_rows * max_row_h + (n_rows - 1) * GRID_PADDING
        grid = Image.new('RGB', (grid_w, grid_h), (255, 255, 255))

        for idx, img in enumerate(batch):
            row = idx // N_COLS
            col = idx % N_COLS
            x = col * (COL_WIDTH + GRID_PADDING)
            y = row * (max_row_h + GRID_PADDING)
            grid.paste(img, (x, y))

        grids.append((grid, start, len(batch)))

    return grids


def parse_json_content(content):
    """兼容 ```json 包裹、前后说明文字。"""
    clean = content.strip()
    clean = clean.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except Exception:
        m = re.search(r"\{.*\}", clean, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def call_vlm_composite(img_b64, prompt, provider, config):
    payload = json.dumps({
        "model": provider["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": config.get("max_tokens", 500),
        "temperature": 0,
        # 思考型模型：关闭思考，否则 reasoning 吞掉输出 token
        "chat_template_kwargs": {
            "enable_thinking": bool(config.get("enable_thinking", False))
        },
    })
    headers = {"Content-Type": "application/json"}
    if provider.get("api_key"):
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    req = urllib.request.Request(
        provider["url"],
        data=payload.encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=config.get("timeout", 180)) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    return parse_json_content(content)


def call_vlm(img_b64, prompt, config, preferred="primary"):
    """按 preferred → 另一个端点 的顺序尝试，返回 (result, model_name)。"""
    order = [preferred] + [p for p in ("primary", "fallback") if p != preferred]
    last_err = None
    for name in order:
        provider = config.get(name)
        if not provider:
            continue
        try:
            result = call_vlm_composite(img_b64, prompt, provider, config)
            return result, provider["model"]
        except Exception as e:
            last_err = e
    raise last_err or RuntimeError("no VLM provider available")


def extract_km(result):
    items = (result or {}).get("odometer_images") or []
    if not items:
        return None, None
    first = items[0]
    if not isinstance(first, dict):
        return None, None
    km = first.get("mileage_km")
    if km is None or km == "":
        return None, first.get("img")
    try:
        return float(km), first.get("img")
    except (TypeError, ValueError):
        return None, first.get("img")


def process_car(car, img_dir, config, preferred="primary"):
    started = time.time()
    slug = car["car_link"].rstrip("/").split("/")[-1].replace(".html", "")
    car_img_dir = os.path.join(img_dir, slug)
    os.makedirs(car_img_dir, exist_ok=True)

    detail_url = car["car_link"]
    if not detail_url.startswith("http"):
        detail_url = "https://jpxkc.cbex.com" + detail_url

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    html_path = os.path.join(car_img_dir, "page.html")
    if not os.path.exists(html_path):
        try:
            html_text = fetch_page(detail_url, opener)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_text)
        except Exception as e:
            return {"status": "error", "error": f"page fetch failed: {e}",
                    "duration": round(time.time() - started, 1)}
    else:
        with open(html_path, "r", encoding="utf-8") as f:
            html_text = f.read()

    img_urls = extract_image_urls(html_text)
    if not img_urls:
        return {"status": "no_images", "error": "no images found on page",
                "duration": round(time.time() - started, 1)}

    img_paths = []
    for i, url in enumerate(img_urls):
        if not url.startswith("http"):
            url = "https://jpxkc.cbex.com" + url
        img_paths.append((i, url, os.path.join(car_img_dir, f"img_{i+1}.jpg")))

    to_download = [(i, u, p) for i, u, p in img_paths if not os.path.exists(p)]
    if to_download:
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {
                pool.submit(download_image, u, p, detail_url): (i, u, p)
                for i, u, p in to_download
            }
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception:
                    pass

    paths_only = [p for i, u, p in img_paths]
    grids = stitch_images(paths_only)
    if not grids:
        return {"status": "error", "error": "failed to stitch images",
                "duration": round(time.time() - started, 1)}

    model_used = None
    last_error = None
    for grid, start_offset, batch_size in grids:
        buf = BytesIO()
        grid.save(buf, format='JPEG', quality=GRID_QUALITY)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        prompt = (
            f'这是一张由{batch_size}张小图拼接成的大图（3列，从上到下从左到右编号'
            f'{start_offset+1}-{start_offset+batch_size}）。其中哪些小图包含汽车仪表盘？'
            '仪表盘上可能有多个数字（TRIP小计、ODO总里程等），请返回总行驶里程ODO'
            '（通常是最大的那个数字，单位公里）。只返回JSON: '
            '{"odometer_images": [{"img": 编号, "mileage_km": 数字}]}'
        )

        for attempt in range(MAX_VLM_RETRIES):
            try:
                result, model_used = call_vlm(img_b64, prompt, config, preferred)
                km, img_no = extract_km(result)
                if km is not None:
                    if km < 5000 or km > 400000:
                        print(f" [里程异常 {int(km)}km，校验中...]", end="", flush=True)
                        verify_prompt = (
                            f'这是一张由{batch_size}张小图拼接成的大图（3列，从上到下从左到右编号'
                            f'{start_offset+1}-{start_offset+batch_size}）。上次你识别第{img_no}张图的里程为'
                            f'{int(km)}公里，这个数值异常，请仔细重新检查第{img_no}张图的仪表盘。'
                            '注意：ODO总里程通常是5位或6位数字（如84820、138215），'
                            '不要把数字中间的小数点当作分隔符，也不要把小计TRIP当成总里程。'
                            '请重新返回总行驶里程ODO（单位公里，整数）。只返回JSON: '
                            '{"odometer_images": [{"img": 编号, "mileage_km": 数字}]}'
                        )
                        try:
                            verify_result, verify_model = call_vlm(
                                img_b64, verify_prompt, config, preferred
                            )
                            verify_km, verify_img = extract_km(verify_result)
                            if verify_km is not None and 5000 <= verify_km <= 400000:
                                model_used = verify_model
                                return {
                                    "status": "found",
                                    "mileage_km": int(verify_km),
                                    "found_in_image": verify_img,
                                    "total_images": len(img_urls),
                                    "model": model_used,
                                    "duration": round(time.time() - started, 1),
                                }
                        except Exception as e:
                            last_error = str(e)
                    return {
                        "status": "found",
                        "mileage_km": int(km),
                        "found_in_image": img_no,
                        "total_images": len(img_urls),
                        "model": model_used,
                        "duration": round(time.time() - started, 1),
                    }
                break
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_VLM_RETRIES - 1:
                    print(f" [VLM error, retrying: {e}]", end="", flush=True)
                    time.sleep(2)
                else:
                    print(f" [VLM failed after {MAX_VLM_RETRIES} attempts: {e}]",
                          end="", flush=True)

    return {
        "status": "not_found",
        "mileage_km": "",
        "found_in_image": "",
        "total_images": len(img_urls),
        "model": model_used or "",
        "error": last_error or "",
        "duration": round(time.time() - started, 1),
    }


def load_existing_mileage(csv_path):
    data = {}
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row.get("car_link", "")
                if key:
                    data[key] = row
    return data


def main():
    parser = argparse.ArgumentParser(description="VLM 里程识别")
    parser.add_argument("zcid")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--retry-low", action="store_true")
    parser.add_argument("--only-missing", action="store_true")
    parser.add_argument("--provider", choices=["primary", "fallback"], default="primary")
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()

    config = load_config()
    concurrency = args.concurrency or int(config.get("concurrency", 4))
    provider = config.get(args.provider) or config["primary"]

    zcid_dir = os.path.join(DOWNLOADS_DIR, args.zcid)
    detail_csv = os.path.join(zcid_dir, "result_detail.csv")
    mileage_csv = os.path.join(zcid_dir, "mileage.csv")
    log_path = os.path.join(zcid_dir, "vlm_log.jsonl")
    img_dir = os.path.join(zcid_dir, "car_images")

    if not os.path.exists(detail_csv):
        print(f"错误: {detail_csv} 不存在")
        sys.exit(1)

    cars = []
    with open(detail_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cars.append(row)
    if args.limit > 0:
        cars = cars[:args.limit]

    existing = {} if args.force else load_existing_mileage(mileage_csv)

    to_process = []
    for car in cars:
        link = car.get("car_link", "")
        row = existing.get(link)
        if row and not args.force:
            if args.only_missing:
                continue
            if row.get("mileage_km"):
                if args.retry_low:
                    try:
                        if float(row["mileage_km"]) < 10000:
                            to_process.append(car)
                            continue
                    except (ValueError, TypeError):
                        pass
                continue
            if row.get("vlm_status") == "not_found":
                continue
        to_process.append(car)

    print(f"期次 {args.zcid}: 共 {len(cars)} 辆, 已有 {len(cars) - len(to_process)} 辆, "
          f"待处理 {len(to_process)} 辆")
    print(f"VLM: {provider['model']} @ {provider['url']} | 并发 {concurrency}")

    if not to_process:
        print("全部已完成")
        return

    os.makedirs(img_dir, exist_ok=True)
    fieldnames = [
        "car_name", "car_link", "item_no", "court",
        "start_price", "final_price", "status",
        "mileage_km", "found_in_image", "total_images",
        "vlm_status", "vlm_model",
    ]

    processed = 0
    found = 0
    not_found = 0
    errors = 0

    def checkpoint():
        with open(mileage_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing.values())

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(process_car, car, img_dir, config, args.provider): car
            for car in to_process
        }
        for i, future in enumerate(as_completed(futures), 1):
            car = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = {"status": "error", "error": str(e)}

            status = result.get("status", "error")
            mileage = result.get("mileage_km", "")
            img_idx = result.get("found_in_image", "")
            total_imgs = result.get("total_images", "?")

            if status == "found":
                found += 1
                print(f"  [{i}/{len(to_process)}] {car.get('car_name','')[:24]}... "
                      f"✓ {mileage}km (图{img_idx}/{total_imgs})")
            elif status == "not_found":
                not_found += 1
                print(f"  [{i}/{len(to_process)}] {car.get('car_name','')[:24]}... "
                      f"- 未找到里程表 ({total_imgs}张图)")
            else:
                errors += 1
                print(f"  [{i}/{len(to_process)}] {car.get('car_name','')[:24]}... "
                      f"✗ {result.get('error','')[:80]}")

            row = {
                "car_name": car.get("car_name", ""),
                "car_link": car.get("car_link", ""),
                "item_no": car.get("item_no", ""),
                "court": car.get("court", ""),
                "start_price": car.get("start_price", ""),
                "final_price": car.get("final_price", ""),
                "status": car.get("status", ""),
                "mileage_km": mileage,
                "found_in_image": img_idx if img_idx else "",
                "total_images": total_imgs,
                "vlm_status": status,
                "vlm_model": result.get("model", ""),
            }
            existing[car["car_link"]] = row
            processed += 1

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "car_link": car.get("car_link", ""),
                    "provider": args.provider,
                    "status": status,
                    "mileage_km": mileage,
                    "found_in_image": img_idx,
                    "total_images": total_imgs,
                    "model": result.get("model", ""),
                    "duration": result.get("duration"),
                    "error": result.get("error", ""),
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, ensure_ascii=False) + "\n")

            if processed % 5 == 0:
                checkpoint()

    checkpoint()
    print(f"\n完成: 处理 {processed} 辆, 找到里程 {found} 辆, "
          f"未找到 {not_found} 辆, 失败 {errors} 辆")
    print(f"输出: {mileage_csv}")
    print(f"日志: {log_path}")


if __name__ == "__main__":
    main()
