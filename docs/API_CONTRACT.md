# 小程序 API 数据契约（v3）

> 云函数与前端共享的唯一契约。前端调用云函数，云函数读写云数据库。任何字段修改须同步此文档。
>
> **202611 期（2464）调整**：`cars` 集合只存本期在售车辆（zcid=2464）；历史中拍（`winners`）
> 与资格池（`pool_all`，仅 2400 期）只用于 `rank` 云函数的推荐，不再提供历史车辆列表。
>
> **v3 变更（成功率推荐）**：`recommendation` 改为按**本期成功率**分级（≥75 强烈推荐 / 55-74 推荐 /
> 35-54 可考虑 / <35 观望），弃用 match_pct 占比分级；新增 `success_rate` / `cover_rate` /
> `suggested_bid` / `capped` 等字段；v3.2 匹配窗口改为「名次 ±N 名（默认 ±50 名起步，样本 <30 自动
> 翻倍扩窗，上限 ±3000 名）」，`window` / `window_pct` 入参废弃，改为 `window_rank`。

## 1. 云函数调用约定

所有调用：`wx.cloud.callFunction({ name, data })`，返回 `{ result: {...} }`。
错误返回：`{ error: { code: number, msg: string } }`。

## 2. 云数据库集合

| 集合 | 说明 | 关键索引 |
|---|---|---|
| `pool_all` | 排名资格池（仅最新期 2400，12,972 行）| `(zcid, times)`, `(zcid, times, reg_time)` 复合索引 |
| `cars` | 本期在售车辆（仅 zcid=2464，506 行）| `(zcid, final_price)`, `(zcid, brand)` |
| `winners` | 历史中拍者画像（331–2400 期，5,407 条，仅用于推荐）| `result_zcid`, `price_bracket` |
| `favorites` | 收藏 | `openid` |
| `histories` | 查询历史 | `openid` |

## 3. 云函数接口

### 3.1 `rank` — 排名查询
**方法 `calculate`**
- 入参：`{ times: int, reg_time: string, window_rank?: int }`（reg_time 格式 `YYYY-MM-DD HH:MM:SS.mmm`，归一化无空格；window_rank 可选，默认 50，范围 10-3000，即匹配窗口 = 用户排名 ±N 名起步）
- 出参：
```
{
  rank: int,              // 精确排名（1-based）
  total: int,             // 全量池人数
  user_pct: float,        // 百分比（1位小数）
  total_matches: int,     // 同分位窗口内历史中拍总数（= peer_count）
  min_final_price: int|null,
  window_base: int,       // 请求的窗口起点（名次，默认 50）
  window_rank_used: int,  // 实际生效窗口（名次；样本 <30 自动翻倍扩窗，上限 3000）
  peer_count: int,        // 同分位中拍人数
  sample_insufficient: bool,  // peer_count < 30 时为 true，前端展示"样本较少"提示
  history_periods: int,   // 历史期次总数（成功率分母，当前 15）
  panorama: [{
    bracket: string,      // "10-15万"
    match_count: int,     // 同分位成交数
    match_pct: float,     // 0-100 占比（⚠ v3 仅保留兼容，前端不再渲染）
    success_rate: float,  // 0-100 本期成功率 = cover_rate（档位级）
    cover_rate: float,    // 同 success_rate；语义：同分位人群买到该档位的期次覆盖率
    recommendation: "强烈推荐|推荐|可考虑|观望",  // 按 success_rate 分级（75/55/35）
    avg_final_price: int,
    avg_winner_times: float,   // 档位内中拍者平均摇号次数（1位小数）
    difficulty: "容易|适中|困难|—",   // ⚠ 已废弃：前端不再渲染，仅保留兼容
    periods_covered: int,
    top_brands: {brand: count},
    top5: [{car_name, car_link, start_price, final_price, result_zcid, winner_pct, winner_times, brand}],
    all_matches: [{car_name, car_link, start_price, final_price, result_zcid, winner_pct, winner_times, brand, pct_diff}],
    current_cars: [{   // 本期在售，起拍价升序限 5
      car_name, car_link, start_price, limit_price, mileage_km, fuel_type, brand, zcid,
      predicted_final_price,  // 目标出价 = 起拍价 × 该档历史 avg_deal_ratio
      suggested_bid,          // 建议出价 = min(最高限价, 目标出价)
      capped: bool,           // 目标出价 ≥ 最高限价 时 true（限价封顶）
      success_rate: int|null  // 单车成功率 = 档位成功率 × (suggested_bid / 目标出价)
    }],
    current_period: string, current_zcid: int,
    recommend_reason: string
  }],
  period_trend: [{
    zcid: string,
    total_bidders: int,
    winner_count: int,
    user_equiv_rank: int,
    matched_car: {car_name, car_link, final_price, bracket} | null
  }],
  latest_zcid: int,         // 排名统计所用的资格池最新期（pool_all，新期资格池发布前不随 cars 变）
  current_zcid: int,        // 本期在售期次（固定 2464）
  current_period: string    // "202611期"
}
```

> 排名算法：`compute_rank` 在**资格池最新期**（`pool_all` 中 `zcid = latest_zcid`）内
> count(`times > 输入`) + count(`times == 输入 AND reg_time < 输入`) + 1，与 webapp 一致。
>
> **成功率公式（v3.2）**：同分位窗口 = 用户排名 ±N 名（N 自 window_base 起自适应翻倍至样本 ≥30，封顶 3000）；窗口内历史中拍者为 peer；
> `cover_rate = 覆盖期次 / history_periods × 100`（history_periods 当前为 15 期，331–2400）；
> 单车 `suggested_bid = min(最高限价, 起拍价 × 平均溢价)`，
> `reach = suggested_bid / (起拍价 × 平均溢价)`（限价封顶时 < 1），
> **单车成功率 = cover_rate × reach**。档位级 success_rate = cover_rate。
>
> `panorama[].top5 / all_matches` 为**历史成交参考**，仅用于解释推荐，不是可筛选列表。
> 查询历史保存走 `histories` 云函数（见 3.5），rank 不再提供 `history` 方法。

### 3.2 `cars` — 本期在售筛选（仅 zcid=2464）
**方法 `list`**
- 入参：
```
{
  page: int,                // 1-based，默认 1
  pageSize: int,            // 默认 20，最大 50
  filters: {                // 全部可选
    brand: string[], court: string[], fuel_type: string[], emission: string[],
    has_license, has_registration, has_plate, has_key: "有"|"无"|null,
    is_mortgaged: "是"|"否"|null,
    final_price_min, final_price_max: float|null,
    violation_min, violation_max: int|null,
    mileage_max: int|null,
    parking_max, repair_max, deposit_max, extra_fee_max: float|null
  },
  sort: string,             // 字段名，默认 "final_price"
  dir: "asc"|"desc"         // 默认 "asc"；可空字段（mileage_km/violation_count）升序时 null 恒排最后
}
```
> `zcid` 参数已废弃：云函数固定 `zcid=2464`，前端无需传。
> **防御性报错**：筛选结果 total=0 且集合总数>0 时返回
> `{ error: { code: 409, msg: ... } }` —— 提示 cars 集合为旧版数据（缺少 2464 期在售车辆），
> 需在云开发控制台清空后重新导入 `downloads/export/cars.json` 及 winners.json / pool_all.json。

- 出参：
```
{
  total: int,
  page: int,
  pageSize: int,
  cars: [{
    car_link, car_name, zcid, period, item_no, court,
    start_price, limit_price, final_price, brand,
    has_license, has_registration, has_plate, has_key, use_type,
    fuel_type, emission_standard, violation_count, violation_points, violation_fine,
    is_mortgaged, parking_fee, repair_fee, total_extra_fee, deposit,
    mileage_km, preview_location, first_reg_date, inspection_expiry, vehicle_model,
    source: "detail"|"detail_partial"
  }],
  options: { brands: string[], courts: string[], fuel_types: string[], emissions: string[] },
  latest_zcid: int          // 固定 2464
}
```

**方法 `detail`**
- 入参：`{ car_link: string }`
- 出参：`{ car: {...单辆车完整字段}, winner: {...} | null, is_favorite: bool }`
  （只允许本期 `zcid=2464` 的车辆；历史 car_link 返回 404「车辆不存在或非本期在售」）

**方法 `zcids`**（兼容保留）
- 入参：`{}`
- 出参：`{ zcids: [{zcid: 2464, period: "202611期", count: int}], latest: 2464 }`（恒为单元素）

### 3.3 `trends` — 本期在售分析（仅 zcid=2464）
**方法 `overview`**
- 入参：`{}`
- 出参：
```
{
  current_zcid: int,                // 2464
  current_period: string,           // "202611期"
  total: int,                       // 本期在售台数
  brand_top: [{ brand: string, count: int }],        // 本期
  court_top: [{ court: string, count: int }],        // 本期
  fuel_dist: [{ fuel_type: string, count: int }],    // 本期
  emission_dist: [{ emission: string, count: int }], // 本期
  price_dist: [{ bracket: string, count: int }],     // 起拍价 5 万档（本期）
  mileage_dist: [{ range: string, count: int }],     // 0-5万,…,30万+（本期）
  condition: { total, no_license, no_registration, no_plate, no_key,
               mortgaged, with_mileage, avg_extra_fee },
  history: { periods: int, winners: int, pool: int } // 历史推荐依据概览（仅数量）
}
```
> 历史中拍统计（bracket_times / times_dist 等）已下线；历史数据只服务于 `rank` 的推荐。

### 3.4 `favorites` — 收藏
| 方法 | 入参 | 出参 |
|---|---|---|
| `add` | `{car_link}` | `{ok: true}`（幂等）|
| `remove` | `{car_link}` | `{ok: true}` |
| `list` | `{}` | `{list: [car_link...]}` |
| `status` | `{car_link}` | `{is_favorite: bool}` |

### 3.5 `histories` — 查询历史
| 方法 | 入参 | 出参 |
|---|---|---|
| `add` | `{times, reg_time, summary?}` | `{ok: true}`（每人最多保留 30 条，超出删最旧）|
| `list` | `{}` | `{list: [{times, reg_time, summary, created_at}]}`（按时间倒序）|
| `clear` | `{}` | `{ok: true}` |

## 4. 前端常量（miniprogram/utils/constants.js）

```js
const PRICE_BRACKETS = ["0-5万","5-10万","10-15万","15-20万","20-25万","25-30万","30-35万","35-40万","40-45万"];
const RECOMMENDATIONS = { STRONG: "强烈推荐", GOOD: "推荐", MAYBE: "可考虑", WAIT: "观望" };
const DIFFICULTY = { EASY: "容易", MEDIUM: "适中", HARD: "困难" };
const FUEL_TYPES = ["汽油", "油电混合", "纯电"];   // 燃料归并后 3 类（与 import_db.normalize_fuel 对齐）
```

## 5. 广告位配置（miniprogram/utils/ad.js）

```js
// 测试广告位 ID（微信官方测试用），上线前替换为流量主后台申请的 ID
const AD_UNITS = {
  bannerCars: "adunit-xxxxxxxx",      // cars 列表底部
  bannerDetail: "adunit-xxxxxxxx",    // 详情页
  bannerMine: "adunit-xxxxxxxx",      // 我的页
  interstitial: "adunit-xxxxxxxx"     // 开屏替代（插屏）
};
```

---
## v4.0（2026-11-10 · 仅小程序端先行）

> rank 云函数升级为「竞争力阶梯 v4」：纯价格维度，去品牌、去 suggested_bid/predicted_final_price、
> 去成功率/期次趋势。webapp 暂保持 v3.2 自有 Flask 逻辑不受影响；后续跟进时再合并。

### rank.calculate 新出参
```
ver: 'v4.0.1'
rank, total, user_pct,
band_half,          // 同类分位带宽（±2.5 起步，翻倍扩窗至样本≥30，上限 ±10）
band_sample,        // 带内历史中拍样本数
deep_count,         // 可达深度（分位≥用户）同类人数
recent_periods: [], // 近 4 期 zcid（代际对齐）
ladder: [{          // 按档位价格升序
  bracket, score_pct,       // 竞争力分 = 近4期「每期可达深度同类获单÷同期档成交」期均（%）
  recent_orders,            // 近4期可达深度同类获单数
  current_supply,           // 本期在售台数
  pass, fail, star          // 判定线: score≥0.3 或 recent_orders≥3 且有在售; star=前三序号(1-3)
}],
top_recommendations: [{     // 通过线的前三档（价格升序）
  bracket, star, score_pct, recent_orders, current_supply, thin,
  cars: [{ car_name, car_link, start_price, limit_price, mileage_km, fuel_type }]   // 起拍价最低3台
}],
overall: { has_pass, verdict }
```

### 小程序 rank 页删除模块
价格档位全景、档位卡片（热门品牌/历史成交参考 top5）、期次趋势（往期成交举例）。

### 已修复
- bracketSortKey 被误用作 sort 比较器（返回排序键而非差值），V8 稳定排序导致档位顺序完全乱序、
  前三推荐选错档——改为 `.sort((a,b)=>bracketSortKey(a)-bracketSortKey(b))`。
