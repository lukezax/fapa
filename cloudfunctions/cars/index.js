// cloudfunctions/cars/index.js
// 车辆筛选：list / detail / zcids
// 筛选语义与 webapp /api/cars 对齐：等值筛选精确匹配，多选为 in，区间为 gte/lte
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const _ = db.command;
const $ = db.command.aggregate;

// 本期在售期次（202611 期）。筛选/详情只允许访问这一期。
const CURRENT_ZCID = 2464;
const CURRENT_PERIOD = '202611期';

// 字符串等值筛选（空值/null 不过滤）
function eqFilter(filters, key, field) {
  const v = filters ? filters[key] : null;
  if (v === null || v === undefined || v === '') return null;
  return { [field]: v };
}

// 多选 in 筛选
function inFilter(filters, key, field) {
  const arr = filters && filters[key] ? filters[key] : [];
  const cleaned = (Array.isArray(arr) ? arr : [arr]).filter(x => x !== '' && x != null);
  if (cleaned.length === 0) return null;
  return { [field]: _.in(cleaned) };
}

// 数值区间筛选（min/max 都为 null 时跳过）
function rangeFilter(filters, minKey, maxKey, field) {
  const min = filters ? filters[minKey] : null;
  const max = filters ? filters[maxKey] : null;
  const parts = {};
  if (min !== null && min !== undefined && min !== '') parts[field] = _.gte(Number(min));
  if (max !== null && max !== undefined && max !== '') {
    parts[field] = parts[field] ? _.and(parts[field], _.lte(Number(max))) : _.lte(Number(max));
  }
  return Object.keys(parts).length ? parts : null;
}

// 仅上限筛选（≤，空值/null 不匹配）
function maxOnlyFilter(filters, key, field) {
  const v = filters ? filters[key] : null;
  if (v === null || v === undefined || v === '') return null;
  return { [field]: _.lte(Number(v)) };
}

function buildWhere(filters, zcid) {
  const where = {};

  if (zcid !== null && zcid !== undefined && zcid !== '') {
    where.zcid = Number(zcid);
  }

  const eqs = [
    ['has_license', 'has_license'], ['has_registration', 'has_registration'],
    ['has_plate', 'has_plate'], ['has_key', 'has_key'], ['is_mortgaged', 'is_mortgaged']
  ];
  for (const [k, f] of eqs) {
    const c = eqFilter(filters, k, f);
    if (c) Object.assign(where, c);
  }

  const ins = [
    ['brand', 'brand'], ['court', 'court'], ['fuel_type', 'fuel_type'], ['emission', 'emission_standard']
  ];
  for (const [k, f] of ins) {
    const c = inFilter(filters, k, f);
    if (c) Object.assign(where, c);
  }

  // min+max 双边区间
  const ranges = [
    ['limit_price_min', 'limit_price_max', 'limit_price'],
    ['violation_min', 'violation_max', 'violation_count']
  ];
  for (const [minK, maxK, f] of ranges) {
    const c = rangeFilter(filters, minK, maxK, f);
    if (c) Object.assign(where, c);
  }

  // 仅上限
  const maxOnly = [
    ['parking_max', 'parking_fee'],
    ['repair_max', 'repair_fee'],
    ['deposit_max', 'deposit'],
    ['extra_fee_max', 'total_extra_fee'],
    ['mileage_max', 'mileage_km']
  ];
  for (const [k, f] of maxOnly) {
    const c = maxOnlyFilter(filters, k, f);
    if (c) Object.assign(where, c);
  }

  return where;
}

async function latestZcid() {
  // 固定返回本期在售期次
  return CURRENT_ZCID;
}

// 本期数据版本（meta 文档，模块级缓存 10 分钟）
let _metaCache = { ts: 0, data: null };
const META_TTL = 10 * 60 * 1000;

async function getMeta() {
  const now = Date.now();
  if (_metaCache.data && now - _metaCache.ts < META_TTL) return _metaCache.data;
  let data = null;
  try {
    const res = await db.collection('meta').doc('current').get();
    data = res.data || null;
  } catch (e) {
    data = null;
  }
  _metaCache = { ts: now, data };
  return data;
}

// 筛选选项（品牌/法院/燃料/排放）：一次导库内不变，模块级缓存 30 分钟
let _optCache = { zcid: 0, ts: 0, data: null };
const OPT_TTL = 30 * 60 * 1000;

async function getOptions(zcid) {
  const now = Date.now();
  if (_optCache.data && _optCache.zcid === zcid && now - _optCache.ts < OPT_TTL) {
    return _optCache.data;
  }
  const [brands, courts, fuelTypes, emissions] = await Promise.all([
    aggregateDistinct('brand', zcid),
    aggregateDistinct('court', zcid),
    aggregateDistinct('fuel_type', zcid),
    aggregateDistinct('emission_standard', zcid)
  ]);
  const data = { brands, courts, fuel_types: fuelTypes, emissions };
  _optCache = { zcid, ts: now, data };
  return data;
}

async function list(event) {
  const zcid = CURRENT_ZCID;
  const page = Math.max(1, parseInt(event.page, 10) || 1);
  const pageSize = Math.min(50, Math.max(1, parseInt(event.pageSize, 10) || 20));
  const filters = event.filters || {};
  const sort = event.sort || 'start_price';
  const dir = event.dir === 'desc' ? 'desc' : 'asc';
  const needOptions = event.needOptions !== false;

  const where = buildWhere(filters, zcid);
  const collection = db.collection('cars');

  // 聚合管道排序：可空字段（里程/违章）升序时 null 恒排最后
  const nullKey = '_null_' + sort;
  const sortSpec = { [nullKey]: 1 };
  sortSpec[sort] = dir === 'asc' ? 1 : -1;

  // count 与列表聚合并发；筛选选项命中缓存时零查询
  const [countRes, res, options] = await Promise.all([
    collection.where(where).count(),
    collection.aggregate()
      .match(where)
      .addFields({ [nullKey]: $.eq(['$' + sort, null]) })
      .sort(sortSpec)
      .skip((page - 1) * pageSize)
      .limit(pageSize)
      .end(),
    needOptions ? getOptions(zcid) : Promise.resolve(null)
  ]);

  const total = countRes.total;

  // 防御：集合里有数据但本期(2464)查不到 → 大概率是旧版数据未重新导入
  if (total === 0) {
    const anyRes = await collection.count();
    if (anyRes.total > 0) {
      return {
        error: {
          code: 409,
          msg: 'cars 集合为旧版数据（缺少 ' + CURRENT_ZCID + ' 期在售车辆）。'
            + '请在云开发控制台清空 cars 集合后重新导入 downloads/export/cars.json，'
            + '并同步导入 winners.json / pool_all.json'
        }
      };
    }
  }

  return {
    total,
    page,
    pageSize,
    cars: res.list,
    options,
    latest_zcid: zcid,
    meta: await getMeta()
  };
}

async function aggregateDistinct(field, zcid) {
  let agg = db.collection('cars').aggregate()
    .match({ [field]: $.neq('') });
  if (zcid !== null && zcid !== undefined && zcid !== '') {
    agg = agg.match({ zcid: Number(zcid) });
  }
  const res = await agg
    .group({ _id: '$' + field, n: $.sum(1) })
    .sort({ n: -1 })
    .end();
  return res.list
    .map(r => r._id)
    .filter(v => v !== null && v !== undefined && v !== '')
    .sort();
}

async function detail(event) {
  const { car_link, openid } = event;
  if (!car_link) return { error: { code: 400, msg: '缺少 car_link' } };

  // 只允许查看本期在售车辆
  const res = await db.collection('cars')
    .where({ car_link, zcid: CURRENT_ZCID }).limit(1).get();
  if (res.data.length === 0) {
    return { error: { code: 404, msg: '车辆不存在或非本期在售' } };
  }
  const car = res.data[0];

  // 联表 winners 与收藏态并发（无 openid 时跳过收藏查询）
  const [wRes, favRes] = await Promise.all([
    db.collection('winners').where({ car_link }).limit(10).get(),
    openid
      ? db.collection('favorites').where({ openid, car_link }).count()
      : Promise.resolve({ total: 0 })
  ]);

  // 同一 car_link 可能跨期重复拍卖，优先取与车辆同期的记录
  let winner = null;
  if (wRes.data.length) {
    const match = wRes.data.find(w => w.result_zcid === car.zcid) || wRes.data[0];
    winner = {
      winner_times: match.winner_times,
      winner_rank: match.winner_rank,
      total_bidders: match.total_bidders,
      winner_reg_time: match.winner_reg_time,
      result_zcid: match.result_zcid
    };
  }

  return { car, winner, is_favorite: favRes.total > 0 };
}

async function zcids() {
  // 只提供本期在售期次
  const countRes = await db.collection('cars')
    .where({ zcid: CURRENT_ZCID }).count();
  return {
    zcids: [{ zcid: CURRENT_ZCID, period: CURRENT_PERIOD, count: countRes.total }],
    latest: CURRENT_ZCID
  };
}

exports.main = async (event, context) => {
  const wxContext = cloud.getWXContext();
  const method = event.method || 'list';
  try {
    switch (method) {
      case 'list':
        return await list(event);
      case 'detail':
        return await detail({ ...event, openid: wxContext.OPENID });
      case 'zcids':
        return await zcids();
      default:
        return { error: { code: 400, msg: `未知方法: ${method}` } };
    }
  } catch (e) {
    return { error: { code: 500, msg: e.message } };
  }
};
