// cloudfunctions/trends/index.js
// 本期（2464 / 202611期）在售车辆分析。
// 历史中拍数据只用于 rank 云函数的推荐，不再在此提供历史车辆统计。
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const _ = db.command;
const $ = db.command.aggregate;

// 本期在售期次（与 cloudfunctions/cars 保持一致）
const CURRENT_ZCID = 2464;
const CURRENT_PERIOD = '202611期';

function bracketOf(startPrice) {
  const p = Number(startPrice) || 0;
  if (p <= 0) return null;
  const lo = Math.floor(p / 50000) * 50000;
  return `${lo / 10000}-${lo / 10000 + 5}万`;
}

function mileageBucket(km) {
  const n = Number(km) || 0;
  if (n <= 0) return null;
  if (n >= 300000) return '30万+';
  const lo = Math.floor(n / 50000) * 50000;
  return `${lo / 10000}-${lo / 10000 + 5}万`;
}

const BRACKET_ORDER = [
  '0-5万', '5-10万', '10-15万', '15-20万', '20-25万',
  '25-30万', '30-35万', '35-40万', '40-45万', '45-50万'
];
const MILEAGE_ORDER = [
  '0-5万', '5-10万', '10-15万', '15-20万', '20-25万',
  '25-30万', '30万+'
];

async function groupCount(field, extraWhere) {
  const match = Object.assign({ zcid: CURRENT_ZCID }, extraWhere || {});
  const res = await db.collection('cars').aggregate()
    .match(match)
    .group({ _id: `$${field}`, count: $.sum(1) })
    .end();
  return res.list
    .filter(r => r._id !== null && r._id !== undefined && r._id !== '')
    .map(r => ({ name: r._id, count: r.count }))
    .sort((a, b) => b.count - a.count);
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

// 概览结果缓存：本期车辆数据一次导库内不变，10 分钟内重复进入直接返回
let _overviewCache = { key: '', ts: 0, data: null };

async function overview() {
  const where = { zcid: CURRENT_ZCID };
  const meta = await getMeta();
  const key = meta ? `${meta.cars_zcid}-${meta.cars_count}` : String(CURRENT_ZCID);
  const now = Date.now();
  if (_overviewCache.data && _overviewCache.key === key && now - _overviewCache.ts < META_TTL) {
    return _overviewCache.data;
  }

  const countWhere = async (extra) => {
    const res = await db.collection('cars')
      .where(Object.assign({}, where, extra)).count();
    return res.total;
  };

  // 全部查询并发：12 个独立查询只占一个往返窗口
  const [
    totalRes, brandTop, courtTop, fuelDist, emissionDist, priceRes,
    noLicense, noRegistration, noPlate, noKey, mortgaged, withMileage, avgRes
  ] = await Promise.all([
    db.collection('cars').where(where).count(),
    groupCount('brand'),
    groupCount('court'),
    groupCount('fuel_type'),
    groupCount('emission_standard'),
    db.collection('cars').aggregate()
      .match(where)
      .project({ start_price: 1, mileage_km: 1 })
      .limit(1000)
      .end(),
    countWhere({ has_license: '无' }),
    countWhere({ has_registration: '无' }),
    countWhere({ has_plate: '无' }),
    countWhere({ has_key: '无' }),
    countWhere({ is_mortgaged: '是' }),
    countWhere({ mileage_km: _.neq(null) }),
    db.collection('cars').aggregate()
      .match(Object.assign({}, where, { total_extra_fee: _.neq(null) }))
      .group({ _id: null, avgFee: $.avg('$total_extra_fee') })
      .end()
  ]);

  const total = totalRes.total;

  // 本期起拍价档位 / 里程分布（内存分桶，506 行量级）
  const priceMap = {};
  const mileageMap = {};
  for (const c of priceRes.list) {
    const bk = bracketOf(c.start_price);
    if (bk) priceMap[bk] = (priceMap[bk] || 0) + 1;
    const mb = mileageBucket(c.mileage_km);
    if (mb) mileageMap[mb] = (mileageMap[mb] || 0) + 1;
  }
  const priceDist = BRACKET_ORDER
    .filter(b => priceMap[b])
    .map(b => ({ bracket: b, count: priceMap[b] }));
  const mileageDist = MILEAGE_ORDER
    .filter(b => mileageMap[b])
    .map(b => ({ range: b, count: mileageMap[b] }));

  const avgExtraFee = avgRes.list.length
    ? Math.round(avgRes.list[0].avgFee || 0) : 0;

  // 历史推荐依据概览（仅数量，不提供车辆列表）
  // 优先用 meta（导库时写入），避免每次全表 count
  const history = meta ? {
    periods: meta.winners_periods,
    winners: meta.winners_count,
    pool: meta.pool_count
  } : await fallbackHistory();

  const result = {
    current_zcid: CURRENT_ZCID,
    current_period: CURRENT_PERIOD,
    total,
    brand_top: brandTop.slice(0, 15).map(r => ({ brand: r.name, count: r.count })),
    court_top: courtTop.slice(0, 10).map(r => ({ court: r.name, count: r.count })),
    fuel_dist: fuelDist.map(r => ({ fuel_type: r.name, count: r.count })),
    emission_dist: emissionDist.map(r => ({ emission: r.name, count: r.count })),
    price_dist: priceDist,
    mileage_dist: mileageDist,
    condition: {
      total,
      no_license: noLicense,
      no_registration: noRegistration,
      no_plate: noPlate,
      no_key: noKey,
      mortgaged: mortgaged,
      with_mileage: withMileage,
      avg_extra_fee: avgExtraFee
    },
    history,
    data_meta: meta ? {
      period: meta.period,
      pool_zcid: meta.pool_zcid,
      pool_count: meta.pool_count,
      pool_updated_at: meta.pool_updated_at,
      cars_count: meta.cars_count,
      cars_updated_at: meta.cars_updated_at,
      winners_count: meta.winners_count,
      winners_periods: meta.winners_periods
    } : null
  };

  _overviewCache = { key, ts: now, data: result };
  return result;
}

// meta 缺失时的兜底（3 个查询并发）
async function fallbackHistory() {
  const [winnersRes, periodRes, poolRes] = await Promise.all([
    db.collection('winners').count(),
    db.collection('winners').aggregate().group({ _id: '$result_zcid' }).end(),
    db.collection('pool_all').where({ zcid: CURRENT_ZCID }).count()
  ]);
  return {
    periods: periodRes.list.length,
    winners: winnersRes.total,
    pool: poolRes.total
  };
}

exports.main = async (event, context) => {
  const method = event.method || 'overview';
  try {
    switch (method) {
      case 'overview':
        return await overview();
      default:
        return { error: { code: 400, msg: `未知方法: ${method}` } };
    }
  } catch (e) {
    return { error: { code: 500, msg: e.message } };
  }
};
