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

async function overview() {
  const where = { zcid: CURRENT_ZCID };

  // 1. 本期总量
  const totalRes = await db.collection('cars').where(where).count();
  const total = totalRes.total;

  // 2. 品牌 / 法院 / 燃料 / 排放（本期）
  const [brandTop, courtTop, fuelDist, emissionDist] = await Promise.all([
    groupCount('brand'),
    groupCount('court'),
    groupCount('fuel_type'),
    groupCount('emission_standard')
  ]);

  // 3. 起拍价档位 / 里程分布（本期，内存分桶，506 行量级）
  const priceRes = await db.collection('cars').aggregate()
    .match(where)
    .project({ start_price: 1, mileage_km: 1 })
    .limit(1000)
    .end();
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

  // 4. 车况概览（本期计数查询）
  const countWhere = async (extra) => {
    const res = await db.collection('cars')
      .where(Object.assign({}, where, extra)).count();
    return res.total;
  };
  const [noLicense, noRegistration, noPlate, noKey, mortgaged, withMileage] = await Promise.all([
    countWhere({ has_license: '无' }),
    countWhere({ has_registration: '无' }),
    countWhere({ has_plate: '无' }),
    countWhere({ has_key: '无' }),
    countWhere({ is_mortgaged: '是' }),
    countWhere({ mileage_km: _.neq(null) })
  ]);

  const avgRes = await db.collection('cars').aggregate()
    .match(Object.assign({}, where, { total_extra_fee: _.neq(null) }))
    .group({ _id: null, avgFee: $.avg('$total_extra_fee') })
    .end();
  const avgExtraFee = avgRes.list.length
    ? Math.round(avgRes.list[0].avgFee || 0) : 0;

  // 5. 历史推荐依据概览（仅数量，不提供车辆列表）
  const winnersRes = await db.collection('winners').count();
  const periodRes = await db.collection('winners').aggregate()
    .group({ _id: '$result_zcid' })
    .end();
  const poolRes = await db.collection('pool_all')
    .where({ zcid: _.gt(0) }).count();

  return {
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
    history: {
      periods: periodRes.list.length,
      winners: winnersRes.total,
      pool: poolRes.total
    }
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
