# 京牌竞拍数据处理 — 使用指南

本指南说明如何运行京牌竞拍分析工具的完整数据处理流程。
支持两种方式：**一键执行**（推荐）和**拆分执行**（按需调试）。

---

## 目录

- [0. 准备工作](#0-准备工作)
- [1. 一键执行（推荐）](#1-一键执行推荐)
- [2. 拆分执行](#2-拆分执行)
- [3. 数据产物说明](#3-数据产物说明)
- [4. 常见问题](#4-常见问题)

---

## 0. 准备工作

### 0.1 环境依赖

```bash
# Python 3.8+
pip install flask pdfplumber requests
```

### 0.2 LLM 配置（可选，用于 Pipeline B）

`tools/llm_config.json` 中配置 LLM API（OpenAI 兼容接口）：

```json
{
  "api_base": "http://127.0.0.1:8080/v1",
  "api_key": "no-key",
  "model": "qwen3",
  "temperature": 0,
  "max_tokens": 2000,
  "concurrency": 1,
  "batch_size": 10
}
```

> 注意：若本地模型未启动，`llm_parse_survey` 和 `vlm_mileage` 会失败。
> 可用 `--skip-vlm` 跳过 VLM 步骤，但 LLM 解析步骤不可跳过。

### 0.3 数据目录结构

所有脚本都从 `downloads/` 目录自动识别期次（按数字命名的子目录）：

```
downloads/
├── 331/               # 历史期次
├── ...
├── 2400/              # 当前最新期次
│   ├── gsxx_2400.pdf      # 竞买人名单 PDF（需手动放入）
│   ├── gsxx_2400.csv      # [产出] 解析后的竞买人
│   ├── result_detail.csv  # [产出] 竞价结果明细
│   ├── car_details_llm.csv# [产出] LLM 解析车辆详情
│   ├── mileage.csv        # [产出] VLM 里程识别
│   ├── survey_texts/      # 调查情况表文本缓存
│   └── car_images/        # 车辆图片缓存
├── combined.csv           # [产出] 全期次合并数据
├── merged_gsxx.csv        # [产出] 去重后竞买人
└── winner_profiles.csv    # [产出] 中拍者画像
```

> **重要**：处理新期次时，把该期的竞买人名单 PDF 放入 `downloads/{新期次}/gsxx_{新期次}.pdf`，脚本会自动发现它，无需修改任何代码。

---

## 1. 一键执行（推荐）

`tools/run_pipeline.py` 串联全部 8 个步骤，按顺序执行，失败即停。

### 基本用法

```bash
# 处理完整流程（Pipeline A + B）
python3 tools/run_pipeline.py 2400

# 跳过 VLM 里程识别（未启动视觉模型时）
python3 tools/run_pipeline.py 2400 --skip-vlm

# 只跑 Pipeline B（车辆详情筛选，不重复跑排名分析）
python3 tools/run_pipeline.py 2400 --only-b
```

### 执行流程

```
Pipeline A: 竞拍排名分析（主页 / 数据来源）
  1. parse_gsxx.py          解析竞买人名单 PDF → gsxx_{zcid}.csv
  2. download_detail.py      下载竞价结果 → result_detail.csv
  3. merge_gsxx.py           合并所有期次竞买人 → merged_gsxx.csv
  4. combine.py              关联竞买人+竞价结果 → combined.csv
  5. build_winner_profiles.py 计算中拍者画像 → winner_profiles.csv

Pipeline B: 车辆详情筛选（/cars 数据来源）
  6. download_survey.py      下载车辆调查情况表 → survey_texts/*.txt
  7. llm_parse_survey.py     LLM 解析车辆详情 → car_details_llm.csv
  8. vlm_mileage.py          VLM 识别里程表 → mileage.csv
```

### 参数说明

| 参数 | 说明 |
|---|---|
| `<zcid>` | 期次 ID，如 `2400`。脚本会处理 `downloads/2400/` 目录 |
| `--skip-vlm` | 跳过步骤 8（VLM 里程识别） |
| `--only-b` | 只执行 Pipeline B（步骤 6-8），跳过 Pipeline A |

### 执行后启动 Web 应用

```bash
# 新终端窗口
python3 webapp/app.py
# 访问 http://localhost:5000
#   主页 /      = 竞拍排名分析
#   /cars      = 车辆详情筛选
```

---

## 2. 拆分执行

按需单独运行某个步骤，适合调试或断点续跑。
所有脚本均在项目根目录下运行（`cd /home/lima/workspace/fapa`）。

### Pipeline A：竞拍排名分析

#### 步骤 1：解析竞买人名单

```bash
# 解析单个期次（从 downloads/{zcid}/gsxx_{zcid}.pdf 提取）
python3 tools/parse_gsxx.py 2400

# 解析所有期次
python3 tools/parse_gsxx.py all

# 仅预览不写文件
python3 tools/parse_gsxx.py 2400 --dry-run
```

**输入**: `downloads/2400/gsxx_2400.pdf`
**输出**: `downloads/2400/gsxx_2400.csv`（字段：full_code / prefix / times / reg_time）

#### 步骤 2：下载竞价结果

```bash
# 下载指定期次的竞价结果（分页抓取并合并）
python3 tools/download_detail.py 2400

# 下载所有已知期次
python3 tools/download_detail.py all

# 仅从缓存合并 CSV（不重新下载）
python3 tools/download_detail.py 2400 --no-download
```

**输出**: `downloads/2400/result_detail.csv`

#### 步骤 3：合并所有期次竞买人

```bash
python3 tools/merge_gsxx.py                # 合并全部
python3 tools/merge_gsxx.py --out FILE     # 指定输出路径
```

**说明**: 按摇号编码前 9 位去重，保留最新期次记录。
**输出**: `downloads/merged_gsxx.csv`

#### 步骤 4：关联竞买人 + 竞价结果

```bash
python3 tools/combine.py
```

**说明**: 以 merged_gsxx 为主表，匹配 prefix 前 7 位 = result_detail.code。
**输出**: `downloads/combined.csv`

#### 步骤 5：计算中拍者画像

```bash
python3 tools/build_winner_profiles.py
```

**输出**: `downloads/winner_profiles.csv`

### Pipeline B：车辆详情筛选

#### 步骤 6：下载车辆调查情况表

```bash
# 下载全部车辆
python3 tools/download_survey.py 2400

# 只下载前 10 辆（测试用）
python3 tools/download_survey.py 2400 --limit 10

# 强制重新提取（默认已有缓存自动跳过，断点续传）
python3 tools/download_survey.py 2400 --force
```

**输出**: `downloads/2400/survey_texts/{slug}.txt`

#### 步骤 7：LLM 解析车辆详情

```bash
python3 tools/llm_parse_survey.py 2400
python3 tools/llm_parse_survey.py 2400 --limit 10   # 测试用
python3 tools/llm_parse_survey.py 2400 --force      # 重新解析
```

**输入**: `survey_texts/*.txt`（来自步骤 6）
**输出**: `downloads/2400/car_details_llm.csv`

#### 步骤 8：VLM 识别里程表

```bash
python3 tools/vlm_mileage.py 2400
python3 tools/vlm_mileage.py 2400 --limit 10   # 测试用
python3 tools/vlm_mileage.py 2400 --force      # 强制重新处理
```

**说明**: 并发下载车辆图片 → 拼接大图 → 一次 VLM 调用识别里程。
**输出**: `downloads/2400/mileage.csv`（增量更新）

---

## 3. 数据产物说明

| 文件 | 用途 | 生成步骤 |
|---|---|---|
| `downloads/{zcid}/gsxx_{zcid}.csv` | 竞买人名单 | 1 |
| `downloads/{zcid}/result_detail.csv` | 竞价结果明细 | 2 |
| `downloads/merged_gsxx.csv` | 去重后全量竞买人 | 3 |
| `downloads/combined.csv` | 竞买人+竞价结果关联表 | 4 |
| `downloads/winner_profiles.csv` | 中拍者画像 | 5 |
| `downloads/{zcid}/survey_texts/*.txt` | 调查情况表文本 | 6 |
| `downloads/{zcid}/car_details_llm.csv` | 结构化车辆详情 | 7 |
| `downloads/{zcid}/mileage.csv` | 车辆里程数据 | 8 |

---

## 4. 常见问题

**Q: 处理新期次需要改代码吗？**
不需要。脚本自动扫描 `downloads/` 下的数字目录。只需放入新期次的 PDF：
`downloads/{新期次}/gsxx_{新期次}.pdf`，然后运行 `run_pipeline.py {新期次}`。

**Q: 断点续跑怎么用？**
所有下载类脚本（download_detail / download_survey / vlm_mileage）都有缓存，
重复运行会自动跳过已完成部分。LLM 解析失败的车会跳过，重跑即可补齐。

**Q: 为什么 LLM 步骤失败？**
检查 `tools/llm_config.json` 中的 API 地址和模型路径，确认本地模型服务已启动。

**Q: 只更新车辆数据，不重复跑排名？**
用 `--only-b`：`python3 tools/run_pipeline.py 2400 --only-b`。

**Q: 已废弃的脚本在哪？**
`tools/archive/` 目录下（crawl_car_details.py、extract_survey_texts.py、parse_331_md.py、analyze_bidder.py），
仅供历史参考，不参与当前流程。
