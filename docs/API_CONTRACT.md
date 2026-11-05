# 小程序 API 数据契约（v1）

> 云函数与前端共享的唯一契约。前端调用云函数，云函数读写云数据库。任何字段修改须同步此文档。

## 1. 云函数调用约定

所有调用：`wx.cloud.callFunction({ name, data })`，返回 `{ result: {...} }`。
错误返回：`{ error: { code: number, msg: string } }`。

## 2. 云数据库集合

| 集合 | 说明 | 关键索引 |
|---|---|---|
| `pool_all` | 全量资格池（精确排名）| `(zcid, times)`, `(zcid, times, reg_time)` 复合索引 |
| `cars` | 跨期全部车辆 | `(zcid, final_price)`, `(zcid, brand)` |
| `winners` | 中拍者画像（15 期 5407 条）| `result_zcid`, `price_bracket` |
| `favorites` | 收藏 | `openid` |
| `histories` | 查询历史 | `openid` |

## 3. 云函数接口

### 3.1 `rank` — 排名查询
**方法 `calculate`**
- 入参：`{ times: int, reg_time: string }`（reg_time 格式 `YYYY-MM-DD HH:MM:SS.mmm`，归一化无空格）
- 出参：
```
{
  rank: int,              // 精确排名（1-based）
  total: int,             // 全量池人数
  user_pct: float,        // 百分比（1位小数）
  total_matches: int,     // 匹配总数
  min_final_price: int|null,
  panorama: [{
    bracket: string,      // "10-15万"
    match_count: int,
    match_pct: float,     // 0-100
    recommendation: "强烈推荐|推荐|可考虑|观望",
    avg_final_price: int,
    avg_winner_times: float,   // 档位内中拍者平均摇号次数（1位小数）
    difficulty: "容易|适中|困难|—",   // ⚠ 已废弃：前端不再渲染（与推荐度并列易误读），仅保留兼容
    periods_covered: int,
    top_brands: {brand: count},
    top5: [{car_name, car_link, start_price, final_price, result_zcid, winner_pct, winner_times, brand}],
    all_matches: [{car_name, car_link, start_price, final_price, result_zcid, winner_pct, winner_times, brand, pct_diff}],
    current_cars: [{car_name, car_link, start_price, mileage_km, fuel_type, zcid}]   // 本期在售，起拍价升序限5
  }],
  period_trend: [{
    zcid: string,
    total_bidders: int,
    winner_count: int,
    user_equiv_rank: int,
    matched_car: {car_name, car_link, final_price, bracket} | null
  }],
  latest_zcid: int,         // 排名统计所用的资格池最新期（pool_all，新期资格池发布前不随 cars 变）
  current_zcid: int         // 车辆最新期（本期在售来源）
}
```

> 排名算法：`compute_rank` 在**资格池最新期**（`pool_all` 中 `zcid = latest_zcid`）内
> count(`times > 输入`) + count(`times == 输入 AND reg_time < 输入`) + 1，与 webapp 一致。
> `panorama[].current_cars`：本期（`current_zcid`）起拍价落在该档区间的在售车，按起拍价升序取 5 台。
> 查询历史保存走 `histories` 云函数（见 3.5），rank 不再提供 `history` 方法。

### 3.2 `cars` — 车辆筛选
**方法 `list`**
- 入参：
```
{
  zcid: string|null,        // null=全部期次，默认前端传最新期
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
- 出参：
```
{
  total: int,
  page: int,
  pageSize: int,
  cars: [{
    car_link, car_name, zcid, period, item_no, court,
    start_price, final_price, brand,
    has_license, has_registration, has_plate, has_key, use_type,
    fuel_type, emission_standard, violation_count, violation_points, violation_fine,
    is_mortgaged, parking_fee, repair_fee, total_extra_fee, deposit,
    mileage_km, preview_location, first_reg_date, inspection_expiry, vehicle_model,
    source: "detail"|"winner_only"
  }],
  options: { brands: string[], courts: string[], fuel_types: string[], emissions: string[] },
                          // 选项在与列表同一 zcid 范围内去重（只看最新期时选项也来自该期）
  latest_zcid: int          // 后端确认的最新期
}
```

**方法 `detail`**
- 入参：`{ car_link: string }`
- 出参：`{ car: {...单辆车完整字段}, winner: {winner_times, winner_rank, total_bidders, winner_reg_time, result_zcid} | null, is_favorite: bool }`
  （`winner` 为联表 winners 的中拍信息；同一 car_link 跨期重复拍卖时优先取与车辆同 zcid 的记录）

**方法 `zcids`**（期次列表，供筛选页切换）
- 入参：`{}`
- 出参：`{ zcids: [{zcid: int, period: string, count: int}], latest: int }`

### 3.3 `trends` — 画像/趋势
**方法 `overview`**
- 入参：`{}`
- 出参：
```
{
  bracket_times: [{ bracket: string, avg_times: float, median_times: float, min_times: int, max_times: int, count: int }],
                          // 价格档位 × 中拍摇号次数（均值/中位数/最低/最高/样本数）
  bracket_dist: [{ bracket: string, count: int }],
  brand_top: [{ brand: string, count: int }],
  times_dist: [{ range: string, count: int }],   // 0-9,10-19,…,70-79,80+（共9档，最大80）
  times_median: float,                           // 中拍者次数中位数
  times_ge80_pct: float,                         // 次数 ≥80 的中拍者占比
  stats: { periods: int, cars: int, winners: int }   // 数据概览
}
```

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
