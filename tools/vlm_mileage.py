#!/usr/bin/env python3
"""
VLM 里程表识别工具 — 从车辆详情页图片中识别里程数。

策略: 并发下载所有图片 → 拼接成 3 列大图 → 一次 VLM 调用识别里程表。

用法:
  python3 tools/vlm_mileage.py 2400
  python3 tools/vlm_mileage.py 2400 --limit 10
  python3 tools/vlm_mileage.py 2400 --force   # 强制重新处理

输入: downloads/{zcid}/result_detail.csv
输出: downloads/{zcid}/mileage.csv (增量更新)
缓存: downloads/{zcid}/car_images/{slug}/
"""

import os
import sys
import re
import csv
import json
import time
import base64
import random
import urllib.request
import http.cookiejar
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
VLM_URL = "http://127.0.0.1:8080/v1/chat/completions"
VLM_MODEL = "/home/lima/workspace/model/9b/claude/Qwen3.5-9B.Q8_0.gguf"

COL_WIDTH = 400
GRID_PADDING = 4
N_COLS = 3
GRID_QUALITY = 75
MAX_TOKENS = 4096
MAX_GRID_PIXELS = 2_000_000
DOWNLOAD_WORKERS = 5
DOWNLOAD_TIMEOUT = 30


def fetch_page(url, opener):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://jpxkc.cbex.com/page/jpxkc/info/jggs_detail",
    })
    with opener.open(req, timeout=DOWNLOAD_TIMEOUT) as resp:
        return resp.read().decode("utf-8")


def extract_image_urls(html_text):
    html_text = html_text.replace("&amp;", "&")
    all_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_text)
    return [img for img in all_imgs if "/editorUpload/file/" in img]


def download_image(url, save_path, referer):
    if os.path.exists(save_path):
        return save_path
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
    })
    data = urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT).read()
    with open(save_path, "wb") as f:
        f.write(data)
    return save_path


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


def call_vlm_composite(img_b64, prompt):
    payload = json.dumps({
        "model": VLM_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        # 思考型模型：关闭思考，否则 reasoning 吞掉输出 token
        "chat_template_kwargs": {"enable_thinking": False},
    })
    req = urllib.request.Request(
        VLM_URL,
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"].strip()
    clean = content.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


def process_car(car, img_dir, opener, referer):
    slug = car["car_link"].rstrip("/").split("/")[-1].replace(".html", "")
    car_img_dir = os.path.join(img_dir, slug)
    os.makedirs(car_img_dir, exist_ok=True)

    detail_url = car["car_link"]
    if not detail_url.startswith("http"):
        detail_url = "https://jpxkc.cbex.com" + detail_url

    html_path = os.path.join(car_img_dir, "page.html")
    if not os.path.exists(html_path):
        try:
            html_text = fetch_page(detail_url, opener)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_text)
        except Exception as e:
            return {"error": f"page fetch failed: {e}"}
    else:
        with open(html_path, "r", encoding="utf-8") as f:
            html_text = f.read()

    img_urls = extract_image_urls(html_text)
    if not img_urls:
        return {"error": "no images found on page"}

    img_paths = []
    for i, url in enumerate(img_urls):
        if not url.startswith("http"):
            url = "https://jpxkc.cbex.com" + url
        img_paths.append((i, url, os.path.join(car_img_dir, f"img_{i+1}.jpg")))

    to_download = [(i, u, p) for i, u, p in img_paths if not os.path.exists(p)]

    if to_download:
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = {
                pool.submit(download_image, u, p, referer): (i, u, p)
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
        return {"error": "failed to stitch images"}
    
    for grid, start_offset, batch_size in grids:
        buf = BytesIO()
        grid.save(buf, format='JPEG', quality=GRID_QUALITY)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        
        prompt = f'这是一张由{batch_size}张小图拼接成的大图（3列，从上到下从左到右编号{start_offset+1}-{start_offset+batch_size}）。其中哪些小图包含汽车仪表盘？仪表盘上可能有多个数字（TRIP小计、ODO总里程等），请返回总行驶里程ODO（通常是最大的那个数字，单位公里）。只返回JSON: {{"odometer_images": [{{"img": 编号, "mileage_km": 数字}}]}}'
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = call_vlm_composite(img_b64, prompt)
                if result.get("odometer_images"):
                    found = result["odometer_images"][0]
                    mileage_km = found.get("mileage_km")
                    if mileage_km is not None:
                        if float(mileage_km) < 10000:
                            print(f" [里程偏低 {mileage_km}km，校验中...]", end="", flush=True)
                            img_num = found.get("img")
                            
                            verify_prompt1 = f'这是一张由{batch_size}张小图拼接成的大图（3列，从上到下从左到右编号{start_offset+1}-{start_offset+batch_size}）。上次你识别第{img_num}张图的里程为{mileage_km}公里，这个数值偏低，请仔细重新检查第{img_num}张图的仪表盘。注意：ODO总里程通常是5位或6位数字（如84820、138215），不要把数字中间的小数点当作分隔符。请重新返回总行驶里程ODO（单位公里，整数）。只返回JSON: {{"odometer_images": [{{"img": 编号, "mileage_km": 数字}}]}}'
                            
                            try:
                                verify_result1 = call_vlm_composite(img_b64, verify_prompt1)
                                if verify_result1.get("odometer_images"):
                                    verify_found1 = verify_result1["odometer_images"][0]
                                    verify_km1 = verify_found1.get("mileage_km")
                                    if verify_km1 is not None and float(verify_km1) >= 10000:
                                        return {
                                            "mileage_km": verify_km1,
                                            "found_in_image": verify_found1.get("img"),
                                            "total_images": len(img_urls),
                                        }
                                    
                                    print(f" [仍偏低 {verify_km1}km，再次校验...]", end="", flush=True)
                                    verify_prompt2 = f'这是一张由{batch_size}张小图拼接成的大图（3列，从上到下从左到右编号{start_offset+1}-{start_offset+batch_size}）。你两次识别第{img_num}张图的里程都偏低（{mileage_km}和{verify_km1}公里）。请非常仔细地重新检查第{img_num}张图。二手车ODO里程通常在1万-30万公里之间。请逐位读出仪表盘上的数字，不要遗漏任何一位。只返回JSON: {{"odometer_images": [{{"img": 编号, "mileage_km": 数字}}]}}'
                                    
                                    verify_result2 = call_vlm_composite(img_b64, verify_prompt2)
                                    if verify_result2.get("odometer_images"):
                                        verify_found2 = verify_result2["odometer_images"][0]
                                        verify_km2 = verify_found2.get("mileage_km")
                                        if verify_km2 is not None:
                                            return {
                                                "mileage_km": verify_km2,
                                                "found_in_image": verify_found2.get("img"),
                                                "total_images": len(img_urls),
                                            }
                            except Exception as e:
                                print(f" [校验失败: {e}]", end="", flush=True)
                        
                        return {
                            "mileage_km": mileage_km,
                            "found_in_image": found.get("img"),
                            "total_images": len(img_urls),
                        }
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f" [VLM error, retrying: {e}]", end="", flush=True)
                    time.sleep(2)
                else:
                    print(f" [VLM failed after {max_retries} attempts: {e}]", end="", flush=True)

    return {"mileage_km": "", "found_in_image": None, "total_images": len(img_urls)}


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
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid> [--limit N] [--force] [--retry-low]")
        sys.exit(1)

    zcid = sys.argv[1]
    force = "--force" in sys.argv
    retry_low = "--retry-low" in sys.argv
    limit = 0
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    zcid_dir = os.path.join(DOWNLOADS_DIR, zcid)
    detail_csv = os.path.join(zcid_dir, "result_detail.csv")
    mileage_csv = os.path.join(zcid_dir, "mileage.csv")
    img_dir = os.path.join(zcid_dir, "car_images")

    if not os.path.exists(detail_csv):
        print(f"错误: {detail_csv} 不存在")
        sys.exit(1)

    cars = []
    with open(detail_csv, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cars.append(row)
    if limit > 0:
        cars = cars[:limit]

    existing = load_existing_mileage(mileage_csv) if not force else {}

    to_process = []
    for car in cars:
        link = car.get("car_link", "")
        if link in existing and existing[link].get("mileage_km"):
            if retry_low:
                try:
                    km = float(existing[link]["mileage_km"])
                    if km < 10000:
                        to_process.append(car)
                        continue
                except (ValueError, TypeError):
                    pass
            continue
        to_process.append(car)

    print(f"期次 {zcid}: 共 {len(cars)} 辆, 已有 {len(cars) - len(to_process)} 辆, 待处理 {len(to_process)} 辆")

    if not to_process:
        print("全部已完成")
        return

    os.makedirs(img_dir, exist_ok=True)
    opener, _ = make_opener = (
        urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        ),
        None,
    )

    fieldnames = [
        "car_name", "car_link", "item_no", "court",
        "start_price", "final_price", "status",
        "mileage_km", "found_in_image", "total_images",
    ]

    processed = 0
    found = 0
    errors = 0

    for i, car in enumerate(to_process, 1):
        name = car.get("car_name", "")[:30]
        print(f"  [{i}/{len(to_process)}] {name}...", end=" ", flush=True)

        referer = car["car_link"]
        result = process_car(car, img_dir, opener, referer)

        if "error" in result:
            print(f"✗ {result['error']}")
            errors += 1
            continue

        mileage = result.get("mileage_km", "")
        img_idx = result.get("found_in_image", "-")
        total_imgs = result.get("total_images", "?")

        if mileage:
            print(f"✓ {mileage}km (图{img_idx}/{total_imgs})")
            found += 1
        else:
            print(f"- 未找到里程表 ({total_imgs}张图)")

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
        }
        existing[car["car_link"]] = row
        processed += 1

        if processed % 5 == 0:
            with open(mileage_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(existing.values())

    with open(mileage_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing.values())

    print(f"\n完成: 处理 {processed} 辆, 找到里程 {found} 辆, 失败 {errors} 辆")
    print(f"输出: {mileage_csv}")


if __name__ == "__main__":
    main()
