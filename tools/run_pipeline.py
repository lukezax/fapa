#!/usr/bin/env python3
"""
一键执行新一期数据处理流程。

用法:
  python3 tools/run_pipeline.py <zcid>
  python3 tools/run_pipeline.py <zcid> --skip-vlm   # 跳过 VLM 里程识别
  python3 tools/run_pipeline.py <zcid> --only-b     # 只执行 Pipeline B (车辆详情)

流程:
  Pipeline A (竞拍排名分析):
    1. parse_gsxx.py - 解析竞买人名单
    2. download_detail.py - 下载竞价结果
    3. merge_gsxx.py - 合并所有期次竞买人
    4. combine.py - 关联竞买人+竞价结果
    5. build_winner_profiles.py - 计算中拍者画像

  Pipeline B (车辆详情筛选):
    6. download_survey.py - 下载车辆调查情况表
    7. llm_parse_survey.py - LLM 解析车辆详情
    8. vlm_mileage.py - VLM 识别里程表
"""

import os
import sys
import subprocess
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")


def run_step(step_num, description, cmd, skip=False):
    if skip:
        print(f"\n[{step_num}] {description} - 跳过")
        return True

    print(f"\n{'='*60}")
    print(f"[{step_num}] {description}")
    print(f"{'='*60}")
    print(f"执行: {' '.join(cmd)}")
    print()

    start = time.time()
    result = subprocess.run(cmd, cwd=BASE_DIR)
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n✓ 完成 ({elapsed:.1f}s)")
        return True
    else:
        print(f"\n✗ 失败 (exit code {result.returncode})")
        return False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 tools/run_pipeline.py <zcid> [--skip-vlm] [--only-b]")
        print()
        print("示例:")
        print("  python3 tools/run_pipeline.py 2500")
        print("  python3 tools/run_pipeline.py 2500 --skip-vlm")
        print("  python3 tools/run_pipeline.py 2500 --only-b")
        sys.exit(1)

    zcid = sys.argv[1]
    skip_vlm = "--skip-vlm" in sys.argv
    only_b = "--only-b" in sys.argv

    print(f"处理期次: {zcid}")
    print(f"选项: skip_vlm={skip_vlm}, only_b={only_b}")

    total_start = time.time()
    success_count = 0
    total_count = 0

    # Pipeline A: 竞拍排名分析
    if not only_b:
        print(f"\n{'#'*60}")
        print(f"# Pipeline A: 竞拍排名分析")
        print(f"{'#'*60}")

        # Step 1: 解析竞买人名单
        total_count += 1
        if run_step(1, "解析竞买人名单 (parse_gsxx.py)",
                    ["python3", "tools/parse_gsxx.py", zcid]):
            success_count += 1

        # Step 2: 下载竞价结果
        total_count += 1
        if run_step(2, "下载竞价结果 (download_detail.py)",
                    ["python3", "tools/download_detail.py", zcid]):
            success_count += 1

        # Step 3: 合并所有期次竞买人
        total_count += 1
        if run_step(3, "合并所有期次竞买人 (merge_gsxx.py)",
                    ["python3", "tools/merge_gsxx.py"]):
            success_count += 1

        # Step 4: 关联竞买人+竞价结果
        total_count += 1
        if run_step(4, "关联竞买人+竞价结果 (combine.py)",
                    ["python3", "tools/combine.py"]):
            success_count += 1

        # Step 5: 计算中拍者画像
        total_count += 1
        if run_step(5, "计算中拍者画像 (build_winner_profiles.py)",
                    ["python3", "tools/build_winner_profiles.py"]):
            success_count += 1

    # Pipeline B: 车辆详情筛选
    print(f"\n{'#'*60}")
    print(f"# Pipeline B: 车辆详情筛选")
    print(f"{'#'*60}")

    # Step 6: 下载车辆调查情况表
    total_count += 1
    if run_step(6, "下载车辆调查情况表 (download_survey.py)",
                ["python3", "tools/download_survey.py", zcid]):
        success_count += 1

    # Step 7: LLM 解析车辆详情
    total_count += 1
    if run_step(7, "LLM 解析车辆详情 (llm_parse_survey.py)",
                ["python3", "tools/llm_parse_survey.py", zcid]):
        success_count += 1

    # Step 8: VLM 识别里程表
    total_count += 1
    if run_step(8, "VLM 识别里程表 (vlm_mileage.py)",
                ["python3", "tools/vlm_mileage.py", zcid],
                skip=skip_vlm):
        success_count += 1

    total_elapsed = time.time() - total_start

    print(f"\n{'='*60}")
    print(f"总结")
    print(f"{'='*60}")
    print(f"成功: {success_count}/{total_count}")
    print(f"耗时: {total_elapsed:.1f}s ({total_elapsed/60:.1f}分钟)")
    print()

    if success_count == total_count:
        print("✓ 全部完成")
        sys.exit(0)
    else:
        print(f"✗ {total_count - success_count} 个步骤失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
