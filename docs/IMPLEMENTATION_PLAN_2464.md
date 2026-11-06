# 2464 本期数据与“只推荐本期车”实施方案

> 版本：v1.0 | 日期：2026-11-06
> 目标期次：2464（202611 期，竞价开始 2026-11-16 08:00）
> 范围：数据拉取、LLM/VLM 落盘、云端导入、筛选改造、推荐链路改造、Web/小程序同步

---

## 0. 现状与结论

| 项目 | 现状 |
|---|---|
| 2464 标的 | 506 台，竞价开始 2026-11-16 08:00 |
| 2464 成交结果 | 官方接口返回“暂无数据”，506 行全部“等待竞价” |
| 2464 资格池 | `gsxx_2464.pdf` 不存在，官方项目页无名单入口 |
| `survey_texts` | 503 个 txt + 7 个 json，3 台车缺 txt |
| `car_details_llm.csv` | 506 行，仅 7 行有数据，499 行空 |
| `mileage.csv` | 96 行，仅 1 行有里程 |
| `car_images` | 仅 79 台车有缓存 |
| 历史数据 | `winners` 5,407 条（331–2400）；最新资格池 2400 期 12,972 人 |

**结论**：2464 处于竞价前状态，本期无法计算 2464 自己的排名。推荐基准为：

- 排名：2400 期资格池（12,972 人）
- 分位 → 档位 → 历史成交证据：`winners`（331–2400，5,407 条）
- 本期推荐车型：2464 在售 506 台

---

## 1. 目标数据架构

```
pool_all（仅 2400 期，12,972 人）
        └──> 算用户排名 / 分位
winners（331–2400，5,407 条）
        └──> 分位 → 价格档位 → 历史成交证据（只用于推荐）
cars（仅 2464 期，506 台）
        └──> 车辆筛选 / 详情 / 本期推荐车型
```

- 所有“车辆列表/筛选/详情”只读 `cars`（2464）。
- `winners` / `pool_all` 只被 `rank` 使用，不再提供历史车辆列表。
- `favorites` / `histories` 不变。

---

## 2. 模型配置

### 2.1 端点

| 用途 | 端点 | 模型 | 说明 |
|---|---|---|---|
| LLM 车况解析 | `http://192.168.200.73:8000/v1` | `Qwen3.5-122B-A10B-w4a8-nothinking` | 主用 |
| VLM 里程识别 | `http://192.168.200.73:8000/v1` | 同上 | 主用，实测 10 图网格约 1.6s |
| VLM 兜底 | `http://127.0.0.1:8022/v1` | `Qwen3.5-9B-ORG` | 122B 失败时使用 |

> `0.0.0.0:8022` 是监听地址，客户端使用 `127.0.0.1:8022` 或局域网 IP。
> 两个端点均支持 `"chat_template_kwargs": {"enable_thinking": false}`。

### 2.2 配置与密钥

- `tools/llm_config.json`：指向 122B，`api_key` 留空，运行时读 `JPXKC_API_KEY`。
- `tools/vlm_config.json`：primary=122B，fallback=9B，`api_key_env=JPXKC_API_KEY`。
- 执行前：

```bash
export JPXKC_API_KEY='sk-...'
```

---

## 3. 阶段 1：2464 数据拉取与 VLM 落盘

### 3.1 执行顺序

```bash
# 0. 备份（download_projects 会覆盖 result_detail）
cp -a downloads/2464 downloads/2464.bak.$(date +%Y%m%d-%H%M)

# 1. 刷新标的列表 + 最高限价
python3 tools/download_projects.py 2464

# 2. 补调查情况表（已有缓存跳过）
python3 tools/download_survey.py 2464

# 3. LLM 解析车况（全量重跑，保证字段一致）
python3 tools/llm_parse_survey.py 2464 --force

# 4. VLM 识别里程（重跑所有无里程车辆）
python3 tools/vlm_mileage.py 2464 --provider primary --concurrency 4
```

预计耗时：列表 3–5 分钟；调查表 1–2 分钟；LLM 约 12–15 分钟（并发 4）；VLM 约 20–40 分钟。

### 3.2 `tools/vlm_mileage.py` 改造点

- 从 `tools/vlm_config.json` 读取端点、模型、密钥、并发、超时。
- 增加 `Authorization: Bearer <key>`。
- 主模型 122B，失败自动切 9B。
- 增加 `--provider primary|fallback`、`--concurrency N`。
- `mileage.csv` 增加 `vlm_status`（found / not_found / error）和 `vlm_model`。
- 新增 `vlm_log.jsonl`：每台车的模型、耗时、原始返回、结果、错误。
- 保留 5 条断点写入；`not_found` 默认不重复跑，`--force` 可重跑。
- 无结果时保留现有低里程二次校验；后续如识别率不足，再加高分辨率复核。

### 3.3 `tools/llm_parse_survey.py` 改造点

- 读取 `JPXKC_API_KEY` 环境变量。
- 配置指向 122B，`enable_thinking=false`。
- 增加失败重试与错误日志。
- 保留 `{slug}.json` 缓存，`--force` 全量重跑。

### 3.4 落盘产物

```text
downloads/2464/
├── result_detail.csv        # 506 台在售标的
├── survey_texts/*.txt       # 506 份（缺 3 台则标记）
├── car_details_llm.csv      # 506 行车况
├── mileage.csv              # 506 行，含 vlm_status / vlm_model
├── vlm_log.jsonl            # VLM 审计日志
├── car_images/              # 全量图片缓存
├── limit_prices.csv         # 最高限价
├── cars_2464.csv            # result_detail + llm + mileage 合并表
└── audit.json               # 数据质量审计
```

### 3.5 质量门禁

- 506 行 `result_detail`，`car_link` 唯一；
- `car_details_llm.csv` ≥503 行有数据；
- `mileage.csv` 506 行，`vlm_status=found` ≥85%；
- 里程异常值（<1000 或 >500000）单独列出，人工抽查 20 台；
- `start_price > 0`，`court` 非空；
- 输出 `audit.json`。

---

## 4. 阶段 2：数据整合与云端导入

### 4.1 `tools/import_db.py` 改造

| 函数 | 改动 |
|---|---|
| `build_pool_all` | 默认只导入 2400 期 12,972 行；`--all-pool` 兼容全量 |
| `build_winners` | 只导入 331–2400，显式排除 2464 |
| `build_cars` | 只导入 2464，输出 `cars.jsonl`（506 行）；不写历史占位 |
| 新增 `manifest.json` | 行数、生成时间、来源期次 |

```bash
python3 tools/import_db.py --current-zcid 2464 --pool-zcid 2400
```

### 4.2 云端导入

1. 备份现有 `cars` / `winners` / `pool_all`。
2. 清空 `cars` 集合（旧 4,334 行）。
3. 导入 `downloads/export/cars.json`（506 行）。
4. 覆盖导入 `winners.json`、`pool_all.json`。
5. 确认索引：`pool_all(zcid, times)`、`(zcid, times, reg_time)`；`cars(zcid, final_price)`、`(zcid, brand)`。
6. 重新部署 `rank`、`cars`、`trends` 云函数。

---

## 5. 阶段 3：筛选只保留 2464

### 5.1 云函数 `cloudfunctions/cars/index.js`

```js
const CURRENT_ZCID = 2464;
```

- `list`：忽略前端 `zcid`，强制 `zcid=2464`；`latest_zcid` 返回 2464。
- `detail`：只查 `zcid=2464`，否则 404。
- `zcids`：只返回 2464 一条。
- `options`：只从 2464 聚合。

### 5.2 小程序

| 文件 | 改动 |
|---|---|
| `miniprogram/utils/constants.js` | 新增 `CURRENT_ZCID=2464`、`CURRENT_PERIOD='202611期'` |
| `miniprogram/pages/cars/cars.js` | 删除 `fetchZcids()`；固定 2464；`onLoad` 直接拉列表 |
| `miniprogram/pages/cars/cars.wxml` | 标题“202611期 · 本期在售”，无期次切换 |
| `miniprogram/pages/car-detail/car-detail.js` | 只允许 2464 车辆 |
| `miniprogram/pages/intro/intro.wxml` | 506 台本期在售；更新数据说明 |
| `miniprogram/app.js` | `latestZcid=2464` |

### 5.3 Web

| 文件 | 改动 |
|---|---|
| `webapp/app.py` | 新增 `CURRENT_ZCID=2464`、`POOL_ZCID=2400`；修复 2464 无 gsxx 导致启动崩溃；`/api/cars` 固定 2464 |
| `webapp/templates/cars.html` | 标题“202611期在售车辆”，显示 506 台 |
| `webapp/templates/index.html` | 档位卡片增加“本期在售”；历史 top5 标注“历史成交参考” |

---

## 6. 阶段 4：历史数据只用于推荐

### 6.1 推荐链路

```
用户 times + reg_time
  → 2400 资格池算 rank / user_pct
  → 331–2400 中拍者中找同分位
  → 聚合到起拍价 5 万档
  → 取该档位 2464 在售车
  → 输出：档位 + 历史成交证据 + 本期推荐车型
```

### 6.2 `cloudfunctions/rank/index.js`

- `latest_zcid` 来自 `pool_all`（2400）。
- `current_zcid` 固定 2464。
- `panorama[].current_cars` 为主推荐结果，按起拍价升序取 5。
- 新增：
  - `avg_deal_ratio`：档位历史成交价/起拍价均值；
  - `predicted_final_price`：本期车 `start_price × avg_deal_ratio`；
  - `recommend_reason`：推荐说明。
- `top5` / `all_matches` 保留为历史依据，不作为筛选列表。

### 6.3 Web `/api/calculate`

- 增加 `current_cars`、`current_zcid`、`avg_deal_ratio`。
- `index.html` 渲染本期在售，点击跳 `/cars`。
- 历史 top5 保留外链或改为参考信息。

### 6.4 小程序 `pages/rank`

- `current_cars` 区块改为“本期推荐 · 202611期”。
- 历史 top5 改为不可点击的“历史成交参考”，避免历史车辆详情 404。
- 增加“查看本期全部车辆”入口。

---

## 7. 阶段 5：`trends` 页面

改造为 **2464 本期分析**：

- 本期品牌、法院、燃料/排放、起拍价、里程分布；
- 本期车况概览（证件缺失、抵押、平均额外费用）；
- 保留“历史推荐依据”入口，跳转 `rank`；
- 不再展示历史车辆列表。

---

## 8. 阶段 6：验收

- [ ] 2464：506 台，506 行 LLM，506 行 mileage，found ≥85%
- [ ] `cars` 集合 = 506，全部 `zcid=2464`
- [ ] `cars.list` 返回 506；`cars.detail` 历史链接 404
- [ ] `rank`：`total=12972`、`current_zcid=2464`、`current_cars` 全为 2464
- [ ] `winners` 不含 2464
- [ ] Web `/cars` 只显示 2464；`/api/calculate` 带 `current_cars`
- [ ] 小程序筛选页无期次切换；首页统计更新
- [ ] 历史数据不出现在车辆列表/筛选中
- [ ] `manifest.json` 与云端行数一致

---

## 9. 风险与回滚

| 风险 | 处理 |
|---|---|
| `download_projects.py` 覆盖 `result_detail.csv` | 先 `cp -a downloads/2464` 备份；脚本保留 `court` |
| 3 台车缺调查表 | 重跑 `download_survey`；仍缺失标记 `source=missing` |
| 2464 数据竞价前变动 | 11-16 前再跑一次增量 |
| VLM 误识别 | 122B + 低里程二次校验 + 异常值人工抽查 |
| 122B 并发过高 | 默认 4；遇 429/5xx 降并发并切 9B |
| 云端清空 `cars` 不可逆 | 导入前控制台导出备份 |
| 历史 top5 链接失效 | 小程序改为不可点击；Web 保留外链 |

---

## 10. 默认决策（本次实施采用）

1. VLM 主用 122B，9B 兜底。
2. `trends` 改成本期 2464 分析。
3. LLM 全量 `--force` 重跑 506 台。
4. Web 与小程序同步改造。
5. 小程序历史 top5 改为不可点击。
6. `pool_all` 只导入 2400 期 12,972 行。
7. 2464 增加 `limit_price`（最高限价）字段，用于筛选与推荐参考。
