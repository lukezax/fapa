// cloudfunctions/trends/index.js
// 画像/趋势总览：bracket_times / bracket_dist / court_top / brand_top / times_dist
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const $ = db.command.aggregate;

function bracketSortKey(b) {
  const m = /^(\d+)/.exec(String(b || ''));
  return m ? parseInt(m[1], 10) : 9999;
}

// 摇号次数分桶：0-9, 10-19, …, 70-79, 80+（中拍者次数中位数 81、最大 88）
function timesBucket(t) {
  const n = Number(t) || 0;
  if (n >= 80) return '80+';
  return `${Math.floor(n / 10) * 10}-${Math.floor(n / 10) * 10 + 9}`;
}

async function overview() {
  // 1. 品牌 Top
  const brandRes = await db.collection('cars').aggregate()
    .match({ brand: $.neq('') })
    .group({ _id: '$brand', count: $.sum(1) })
    .sort({ count: -1 })
    .limit(15)
    .end();
  const brandTop = brandRes.list
    .filter(r => r._id)
    .map(r => ({ brand: r._id, count: r.count }));

  // 2. 档位分布（winners）
  const bracketRes = await db.collection('winners').aggregate()
    .match({ price_bracket: $.neq('') })
    .group({ _id: '$price_bracket', count: $.sum(1) })
    .end();
  const bracketDist = bracketRes.list
    .filter(r => r._id)
    .sort((a, b) => bracketSortKey(a._id) - bracketSortKey(b._id))
    .map(r => ({ bracket: r._id, count: r.count }));

  // 3. 价格档位 × 中拍摇号次数：每档聚合次数分布 → 均值/中位数/样本数
  const bracketTimes = [];
  for (const bk of bracketDist) {
    const res = await db.collection('winners').aggregate()
      .match({ price_bracket: bk.bracket, winner_times: $.neq(null) })
      .group({ _id: '$winner_times', count: $.sum(1) })
      .limit(1000)
      .end();
    const pairs = res.list
      .filter(r => r._id != null)
      .map(r => ({ times: Number(r._id), count: r.count }))
      .sort((a, b) => a.times - b.times);
    if (pairs.length === 0) continue;

    const totalCount = pairs.reduce((s, p) => s + p.count, 0);
    const timesSum = pairs.reduce((s, p) => s + p.times * p.count, 0);
    const avg = Math.round(timesSum / totalCount * 10) / 10;

    const expanded = [];
    for (const p of pairs) {
      for (let i = 0; i < p.count; i++) expanded.push(p.times);
    }
    const mid = Math.floor(expanded.length / 2);
    const median = expanded.length % 2 === 1
      ? expanded[mid]
      : Math.round((expanded[mid - 1] + expanded[mid]) / 2 * 10) / 10;

    bracketTimes.push({
      bracket: bk.bracket,
      avg_times: avg,
      median_times: median,
      min_times: pairs[0].times,
      max_times: pairs[pairs.length - 1].times,
      count: totalCount
    });
  }

  // 4. 摇号次数分布（winners.winner_times，聚合后在内存分桶）+ 中位数 + ≥80 占比
  const timesRes = await db.collection('winners').aggregate()
    .match({ winner_times: $.neq(null) })
    .group({ _id: '$winner_times', count: $.sum(1) })
    .limit(1000)
    .end();
  const pairs = timesRes.list
    .filter(r => r._id != null)
    .map(r => ({ times: Number(r._id), count: r.count }))
    .sort((a, b) => a.times - b.times);

  const bucketMap = {};
  let timesTotal = 0;
  let ge80 = 0;
  const expanded = [];
  for (const p of pairs) {
    bucketMap[timesBucket(p.times)] = (bucketMap[timesBucket(p.times)] || 0) + p.count;
    timesTotal += p.count;
    if (p.times >= 80) ge80 += p.count;
    for (let i = 0; i < p.count; i++) expanded.push(p.times);
  }
  const rangeOrder = [];
  for (let i = 0; i <= 7; i++) rangeOrder.push(`${i * 10}-${i * 10 + 9}`);
  rangeOrder.push('80+');
  const timesDist = rangeOrder
    .filter(b => bucketMap[b])
    .map(b => ({ range: b, count: bucketMap[b] }));

  const mid = Math.floor(expanded.length / 2);
  const timesMedian = expanded.length % 2 === 1
    ? expanded[mid]
    : Math.round((expanded[mid - 1] + expanded[mid]) / 2 * 10) / 10;
  const timesGe80Pct = timesTotal ? Math.round(ge80 / timesTotal * 1000) / 10 : 0;

  // 5. 数据概览
  const carsCountRes = await db.collection('cars').count();
  const winnersCountRes = await db.collection('winners').count();
  const periodRes = await db.collection('cars').aggregate()
    .match({ zcid: $.neq(null) })
    .group({ _id: '$zcid' })
    .limit(50)
    .end();

  return {
    bracket_times: bracketTimes,
    bracket_dist: bracketDist,
    brand_top: brandTop,
    times_dist: timesDist,
    times_median: timesMedian,
    times_ge80_pct: timesGe80Pct,
    stats: {
      periods: periodRes.list.length,
      cars: carsCountRes.total,
      winners: winnersCountRes.total
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
