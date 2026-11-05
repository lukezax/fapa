#!/usr/bin/env python3
"""
解析 gsxx PDF 文件，提取竞买人信息，输出为 CSV。

用法:
  python3 tools/parse_gsxx.py <zcid>     # 解析单个期次
  python3 tools/parse_gsxx.py all         # 解析所有期次
  python3 tools/parse_gsxx.py <zcid> --dry-run  # 仅预览不写文件

输出: downloads/{zcid}/gsxx_{zcid}.csv
  字段: full_code - 完整12位编码, prefix - 9位前缀, times - 摇号次数, reg_time - 注册时间
"""

import os
import sys
import re
import csv
import concurrent.futures
import multiprocessing
import pdfplumber

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


def get_known_zcids():
    return sorted([int(d) for d in os.listdir(DOWNLOADS_DIR) if d.isdigit() and os.path.isdir(os.path.join(DOWNLOADS_DIR, d))])


KNOWN_ZCIDS = get_known_zcids()

# 码表标记 -> 期次名
PERIOD_MAP = {
    # 格式: 结尾三位匹配
}


def get_period_name(zcid):
    """zcid 到期次名的映射"""
    names = {
        2400: "202606期", 2238: "202512期", 2041: "202506期",
        1897: "202411期", 1694: "202402期", 1609: "202310期",
        1533: "202306期", 1417: "202302期", 1064: "202211期",
        725: "202206期", 640: "202202期", 532: "202111期",
        413: "202106期", 378: "202102期", 331: "202011期",
    }
    return names.get(zcid, f"zcid={zcid}")


def parse_pdf(filepath):
    """
    解析 PDF 中的竞买人列表。
    每行格式: 718610025**** 84 2011-01-17 08: 51: 18. 077
    """
    records = []
    pdf = pdfplumber.open(filepath)
    for page in pdf.pages:
        text = page.extract_text()
        if not text:
            continue
        for line in text.split('\n'):
            m = re.match(r'(\d{9})(\*{4})\s+(\d+)\s+([\d\s:\.-]+)', line)
            if m:
                records.append({
                    'full_code': m.group(1) + m.group(2),
                    'prefix': m.group(1),
                    'times': int(m.group(3)),
                    'reg_time': m.group(4).strip(),
                })
    pdf.close()
    return records


def write_csv(filepath, records):
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['full_code', 'prefix', 'times', 'reg_time'])
        writer.writeheader()
        writer.writerows(records)


def parse_one(zcid, dry_run=False):
    period_name = get_period_name(zcid)
    pdf_path = os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.pdf")
    csv_path = os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.csv")

    print(f"  [{period_name}] zcid={zcid}")

    if not os.path.exists(pdf_path):
        print(f"    ✗ PDF 不存在: {pdf_path}")
        return False

    records = parse_pdf(pdf_path)
    if not records:
        print(f"    ⚠ 未提取到记录")
        return False

    if dry_run:
        print(f"    ✓ 共 {len(records)} 条记录 (预览前3条):")
        for r in records[:3]:
            print(f"      {r['full_code']}  {r['times']}次  {r['reg_time']}")
        return True

    write_csv(csv_path, records)
    print(f"    ✓ {len(records)} 条记录 → {csv_path}")
    return True


def detect_system():
    cpu_count = os.cpu_count() or 4
    available_ram_mb = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    available_ram_mb = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass
    if available_ram_mb is None:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemFree:"):
                        free_mb = int(line.split()[1]) // 1024
                        available_ram_mb = int(free_mb * 0.8)
                        break
        except Exception:
            pass
    return cpu_count, available_ram_mb


def get_pdf_sizes(zcids):
    sizes = []
    for zcid in zcids:
        path = os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.pdf")
        if os.path.exists(path):
            sizes.append(os.path.getsize(path) / (1024 * 1024))
    return sizes


def estimate_workers(zcids, cpu_count, available_ram_mb):
    total = len(zcids)
    if total == 0:
        return 0, "无 PDF"

    pdf_sizes = get_pdf_sizes(zcids)
    if not pdf_sizes:
        return 0, "无可用 PDF"

    max_pdf_mb = max(pdf_sizes)
    per_worker_mb = max(200, int(max_pdf_mb * 12))

    cpu_limit = cpu_count
    ram_limit = cpu_limit
    if available_ram_mb is not None:
        usable_ram = available_ram_mb - 2048
        ram_limit = max(1, usable_ram // per_worker_mb) if usable_ram > 0 else 1
    count_limit = total

    workers = min(cpu_limit, ram_limit, count_limit)
    workers = max(1, (workers + 1) // 2)

    reasons = [
        f"CPU {cpu_count}核 → {cpu_limit}",
        f"内存 {available_ram_mb}MB / 每进程~{per_worker_mb}MB → {ram_limit}" if available_ram_mb else f"内存未知 → 保守 {ram_limit}",
        f"PDF {total}个 → {count_limit}",
        f"50%策略: {workers}",
    ]

    return workers, "  |  ".join(reasons)


def run_batch(zcids, dry_run, workers):
    success = 0
    mp_ctx = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=mp_ctx) as executor:
        fut_map = {executor.submit(parse_one, zcid, dry_run): zcid for zcid in zcids}
        for future in concurrent.futures.as_completed(fut_map):
            zcid = fut_map[future]
            try:
                if future.result():
                    success += 1
            except Exception as e:
                period = get_period_name(zcid)
                print(f"  [{period}] ✗ 异常: {e}")
    return success


def run_sequential(zcids, dry_run):
    success = 0
    for zcid in zcids:
        if parse_one(zcid, dry_run=dry_run):
            success += 1
    return success


def main():
    if len(sys.argv) < 2:
        print(f"用法: python3 {sys.argv[0]} <zcid|all> [--dry-run]")
        sys.exit(1)

    arg = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if arg == "all":
        zcids = KNOWN_ZCIDS
    else:
        zcids = [int(arg)]

    existing = []
    for zcid in zcids:
        pdf_path = os.path.join(DOWNLOADS_DIR, str(zcid), f"gsxx_{zcid}.pdf")
        if os.path.exists(pdf_path):
            existing.append(zcid)
        else:
            print(f"  [{get_period_name(zcid)}] ⚠ PDF 不存在，跳过")

    if not existing:
        print("错误: 没有可用的 PDF")
        sys.exit(1)

    cpu_count, available_ram_mb = detect_system()
    workers, reason = estimate_workers(existing, cpu_count, available_ram_mb)

    print(f"系统: CPU {cpu_count}核 / RAM {available_ram_mb or '?'}MB 可用")
    print(f"PDF: {len(existing)} 个期次")
    print(f"策略: {reason}\n")

    if len(existing) == 1:
        success = run_sequential(existing, dry_run)
    else:
        success = run_batch(existing, dry_run, workers)

    print(f"\n完成: {success}/{len(existing)} 个期次解析成功")


if __name__ == "__main__":
    main()
