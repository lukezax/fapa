# 京牌竞拍分析 — 微信小程序开发方案（v2）

> 状态：已批准（含 5 项决策） | 日期：2026-08-04 | 技术栈：原生小程序 + 微信云开发

---

## 0. 已确认决策（v1 评估结论）

| # | 决策项 | 结论 | 方案影响 |
|---|---|---|---|
| 1 | 排名精度 | **精确排名** | 导入全量资格池（20 万行）到 `pool_all` 集合，云函数精确 count 计算 |
| 2 | 车辆筛选范围 | **全量数据入库，筛选默认最新期** | `cars` 集合存跨期全部车辆；默认筛选 `result_zcid=最新期`；**导入工具支持增量**——下次新期次数据本地跑完后重新上传 |
| 3 | 图表方案 | **图表组件** | trends 页引入图表组件（ec-canvas / ECharts 小程序版）|
| 4 | 备案主体 | **个人主体先试** | 类目「工具-信息查询」，无支付/web-view/手机号能力，用 openid 规避 |
| 5 | 广告变现 | **开屏广告 + Banner 广告** | 新增广告位：开屏广告（启动页）+ Banner（列表页/详情页），需开通流量主（UV≥1000）|

---

## 1. 项目定位

把现有 Flask webapp（京牌竞拍分析）的核心能力移植为微信小程序，正式发布，微信云开发方案（免域名备案），通过广告变现。

**目标用户**：京牌竞拍参与者，在手机上快速查询自己的排名、预估中标概率、筛选车辆。

---

## 2. 架构总览

```
┌─────────────────────────────────────────────┐
│  微信小程序（原生 WXML/WXSS/JS，4 个 tab）      │
│  pages/rank   pages/cars   pages/trends  pages/mine │
│  + 开屏广告（启动） + Banner（列表/详情页）        │
└──────────────┬──────────────────────────────┘
               │ wx.cloud.callFunction
┌──────────────▼──────────────────────────────┐
│  微信云开发                                  │
│  ├─ 云函数：rank / cars / detail / trends /  │
│  │          options / favorites / histories  │
│  └─ 云数据库：                              │
│     ├─ pool_all    全量资格池（20万行，精确排名）│
│     ├─ cars        跨期全部车辆（car_link 主键）│
│     ├─ winners     中拍者画像（15期 5407条）   │
│     ├─ favorites   收藏（openid 维度）         │
│     └─ histories   查询历史（openid 维度）     │
└─────────────────────────────────────────────┘
        ▲ 一次性导入 + 增量上传（tools/import_db.py）
┌────────┴─────────────────────────────────────┐
│  现有数据管道 downloads/*.csv                │
└──────────────────────────────────────────────┘
```

**核心决策**：
- **后端**：微信云开发（免域名备案，个人主体可用，19.9元/月封顶）
- **前端**：原生小程序（4 个页面以内，无需框架）
- **数据**：CSV 导入云数据库；**精确排名**需全量资格池；**增量更新**支持下次新期次
- **广告**：流量主（个人可开通，UV≥1000），开屏 + Banner
- **复用**：现有 Flask 的排名算法、品牌提取、档位划分逻辑移植到云函数

---

## 3. 数据模型设计（基于现有 CSV 实测）

### 3.1 集合 `pool_all` — 全量资格池（精确排名用）

来自 `merged_gsxx.csv`（199,378 行，15 期全量），**精确排名数据源**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `full_code` | string | 完整 12 位编码 |
| `prefix` | string | 9 位前缀（去重键）|
| `times` | int | 摇号次数 |
| `reg_time` | string | 注册时间（归一化 ISO，去空格）|
| `zcid` | int | 期次 |

> **精确排名算法**（云函数 `rank` 移植）：`compute_rank(times, reg_time)` 需对全量池 O(N) 比较。云数据库侧实现：用聚合 `count(times < 输入) + count(times == 输入 AND reg_time < 输入) + 1`，需要索引 `(times, reg_time)`。20 万行 count 查询云数据库可承受（只读，低频）。

### 3.2 集合 `cars` — 跨期全部车辆（筛选数据源）

由各期 `result_detail.csv` + `car_details_llm.csv` + `mileage.csv` 按 `car_link` 1:1 合并；**历史期次仅 winner_profiles 有数据**（无详细车况，只含车名/链接/价格）。

| 字段 | 来源 | 类型 | 说明 |
|---|---|---|---|
| `_id` | 生成 | string | 云数据库主键 |
| `car_link` | 公共 | string | 唯一标识 |
| `car_name` | 公共 | string | 车辆名称 |
| `zcid` | 各期文件 | int | 期次（默认筛最新期）|
| `period` | 派生 | string | 期次名（202606期）|
| `item_no` | result_detail | string | |
| `court` | 公共 | string | 法院 |
| `start_price` | 公共 | float | 起拍价 |
| `final_price` | 公共 | float | 成交价 |
| `brand` | 派生 | string | 品牌（复用 Flask 品牌表）|
| 车况字段 | llm | mixed | has_license/has_registration/has_plate/has_key/use_type/fuel_type/emission_standard/violation_count/violation_points/violation_fine/is_mortgaged/parking_fee/repair_fee/total_extra_fee/deposit/preview_location/first_reg_date/inspection_expiry/vehicle_model |
| `mileage_km` | mileage.csv | int | 里程（llm 的 mileage 列 428/434 空，以 mileage.csv 为准）|
| `source` | 派生 | string | `detail`（有完整车况）/ `winner_only`（仅中拍记录）|

> 索引：`(zcid, final_price)`、`(zcid, brand)`、`(zcid, mileage_km)` 支撑筛选排序。

### 3.3 集合 `winners` — 中拍者画像（15 期，5,407 条）

来自 `winner_profiles.csv`，**注意按人分行**（125 辆车有多个中标者），车级展示需 `group by car_link`。

| 字段 | 来源 | 说明 |
|---|---|---|
| `car_link` | csv | 关联 cars |
| `result_zcid` | csv | 期次（15 个枚举）|
| `price_bracket` | csv | 9 档价格区间 |
| `winner_times` | csv | 中拍者摇号次数 |
| `winner_reg_time` | csv | 中拍者注册时间（归一化）|
| `winner_rank` | csv | 中拍者当时排名 |
| `total_bidders` | csv | 该期总人数 |

### 3.4 集合 `favorites` / `histories` — 用户数据

| 集合 | 字段 | 说明 |
|---|---|---|
| `favorites` | `openid, car_link, created_at` | 收藏车辆，按 openid 查询 |
| `histories` | `openid, times, reg_time, result_json, created_at` | 查询历史 |

> 云开发可通过云函数 `cloud.getWXContext().OPENID` 获取用户身份，无需登录。

---

## 4. 功能页面规划（4 个 tab + 广告）

### Tab 1 `pages/rank` — 排名查询（主页核心）
- 输入：摇号次数 + 注册时间（复用 webapp 的 4 段式输入：日期/时分/秒/毫秒）
- 展示：
  - **排名卡片**：rank / total / 百分比 / 总匹配数 / 最低成交价
  - **全景图**：9 个价格档位的匹配度条（`panorama` 数组）
  - **档位卡片**：推荐度（强烈推荐/推荐/可考虑/观望）+ 难度 + 平均成交价 + 品牌 Top + 前 5 便宜车
  - **期次趋势**：用户排名在各期次的等效排名 + 对应匹配车
- API：`rank` 云函数（移植 `compute_rank` + 档位统计逻辑，**精确排名**）

### Tab 2 `pages/cars` — 车辆筛选
- 筛选：品牌 / 法院 / 燃料 / 排放 / 证件（行驶证/登记证/车牌/钥匙）/ 抵押 / 价格区间 / 违章数 / 里程上限 / 费用上限
- **默认筛最新期次**，提供期次切换（跨期全部车辆）
- 排序：成交价、里程、违章数（点击列头切换升/降）
- 列表 → 点击进入详情（`pages/car-detail`，含车况字段 + 收藏按钮 + **Banner 广告**）
- API：`cars` 云函数（移植筛选+排序逻辑，**增加分页**，每次 20 条）

### Tab 3 `pages/trends` — 中拍者画像/趋势
- 15 期价格趋势折线（最低/平均/最高成交价）— **图表组件**（ec-canvas）
- 价格档位分布（9 档柱状）— 图表组件
- 中拍者摇号次数分布、法院 Top、品牌 Top
- API：`trends` 云函数（聚合 winners + pool_all）

### Tab 4 `pages/mine` — 我的
- 收藏列表（点击跳车辆详情）
- 查询历史（点击回填重新查询）
- 清除历史
- **Banner 广告**
- API：`favorites` / `histories` 云函数

### 广告位设计
| 广告位 | 位置 | 实现 | 说明 |
|---|---|---|---|
| 开屏广告 | 启动页（首屏） | 原生开屏广告组件 / 自建启动页+激励 | 微信无标准开屏组件，用「启动页停留 + Banner」或 `wx.createInterstitialAd` 插屏替代；**以实际流量主后台可用类型为准** |
| Banner | cars 列表页底部 / 详情页 / mine 页 | `<ad unit-id="...">` | 需要流量主开通后申请广告位 ID |

> 广告位 ID（`unit-id`）需在**流量主后台创建**后填入 `miniprogram/config.js`。开发阶段用测试广告位（微信提供的测试 ID）。

---

## 5. 云函数 API 设计

| 云函数 | 方法 | 入参 | 出参 |
|---|---|---|---|
| `rank` | `calculate` | `{times, reg_time}` | `{rank, total, user_pct, panorama[], bracket_cards[], period_trend[]}` |
| `cars` | `list` | `{filters{}, sort, dir, page, pageSize, zcid}` | `{total, cars[], options{brands, courts, fuel_types, emissions}}` |
| `cars` | `detail` | `{car_link}` | 单辆车完整字段 |
| `trends` | `overview` | `{}` | `{price_trend[], bracket_dist[], court_top[], brand_top[], times_dist[]}` |
| `favorites` | `add/remove/list` | `{car_link}` | `{ok}` / `{list[]}` |
| `histories` | `add/list/clear` | `{record}` | `{ok}` / `{list[]}` |

> 每个云函数内部对 `cloud.database()` 查询，SQL 能力用聚合 `aggregate` 实现（价格分桶、分组计数等）。

---

## 6. 实施计划

### 阶段 0：前置准备（并行于开发，不可跳过）
- [ ] 注册小程序账号（个人主体，身份证）
- [ ] **立即启动小程序备案**（平台初审1-2天 + 工信部短信核验24h + 管局1-20天）
- [ ] 选类目「工具-信息查询」
- [ ] 开通云开发环境
- [ ] 开通流量主（累计 UV≥1000 后可申请，先开发后开通）

### 阶段 1：数据导入工具（1 天）
- [ ] `tools/import_db.py`：读 CSV → 字段类型转换 → 日期归一化 → 品牌提取 → 全量资格池导入 + 跨期车辆合并 + **增量模式**（只导入新 zcid）
- [ ] 建立集合索引

### 阶段 2：云函数后端（2-3 天）
- [ ] `rank`（精确排名算法）+ `cars`（筛选+分页）+ `trends`（聚合）+ `favorites`/`histories`

### 阶段 3：小程序前端（3-4 天）
- [ ] 项目骨架 + 4 tab + 开屏页 + Banner 广告位
- [ ] `pages/rank` / `pages/cars` / `pages/car-detail` / `pages/trends`（图表组件）/ `pages/mine`

### 阶段 4：联调与发布（2-3 天）
- [ ] 真机调试 → 上传 → 体验版 → 提审 → 发布

**总计约 8-11 天**（备案周期另计，可与开发并行）。

---

## 7. 风险与注意点

| 风险 | 影响 | 对策 |
|---|---|---|
| 小程序备案周期 1-20 天 | 上线延迟 | 注册后立即启动备案，与开发并行 |
| 个人主体限制：无支付/web-view/手机号 | 收藏/历史用 openid 即可 | 已规避 |
| 全量资格池 20 万行 count 查询性能 | 精确排名变慢 | 建 `(times, reg_time)` 复合索引；云函数只读低频 |
| 历史期次无详细车况 | 筛选跨期时字段缺失 | `source=winner_only` 区分，前端降级展示 |
| LLM 数据质量（mileage 列 428 空） | 里程缺失 | 用 mileage.csv 的 mileage_km 字段 |
| reg_time 格式不统一（`20: 04: 34. 627` 带空格） | 排名计算错误 | 导入时统一归一化为 ISO 格式 |
| 开屏广告无标准组件 | 广告类型受限 | 用插屏广告替代（`wx.createInterstitialAd`），或启动页 Banner |
| 流量主 UV≥1000 门槛 | 广告暂时无法开通 | 先开发功能，达标后申请广告位，unit-id 后填 |
| 审核类目不符 | 驳回 | 类目选「工具-信息查询」，功能描述一致；不涉及交易 |

---

## 8. 交付物清单

- [ ] `tools/import_db.py` — 数据导入工具（支持全量 + 增量）
- [ ] `miniprogram/` — 小程序前端（4 tab + 开屏 + 广告位）
- [ ] `cloudfunctions/` — 云函数后端（7 个函数）
- [ ] `DEPLOY.md` — 部署指南（注册/备案/流量主/提审）
