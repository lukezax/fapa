// cloudfunctions/rank/index.js
// 排名查询（精确排名）——移植 webapp/app.py /api/calculate 算法
//
// 算法要点（与 Flask 版完全一致）：
// 1. compute_rank：在"最新期次"资格池内 count(times > 输入) + count(times == 输入 AND reg_time < 输入) + 1
// 2. user_pct = rank / total * 100；窗口 ±10 名 → pct_low/pct_high
// 3. 对每个价格档位：统计匹配车、推荐度、难度、品牌 Top、top5、全匹配列表
// 4. period_trend：每个历史期次的等效排名 + 最近匹配车
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const _ = db.command;

// 价格档排序键
function bracketSortKey(b) {
  const m = /^(\d+)/.exec(String(b || ''));
  return m ? parseInt(m[1], 10) : 9999;
}

// reg_time 归一化（与 import_db.py 一致：去冒号/点号后空格）
function normalizeRegTime(rt) {
  return String(rt || '').replace(/:\s/g, ':').replace(/\.\s/g, '.').trim();
}

// 分页拉取集合全部数据
async function fetchAll(collectionName, max = 1000) {
  const all = [];
  const countRes = await db.collection(collectionName).count();
  const total = countRes.total;
  const pages = Math.ceil(total / max);
  for (let i = 0; i < pages; i++) {
    const res = await db.collection(collectionName)
      .skip(i * max).limit(max).get();
    all.push(...res.data);
  }
  return all;
}

// 资格池最新期（排名基准：pool_all 未发布新期前不随 cars 变）
async function getLatestPoolZcid() {
  const res = await db.collection('pool_all')
    .orderBy('zcid', 'desc').limit(1).get();
  return res.data.length ? res.data[0].zcid : 2400;
}

// 车辆最新期（本期在售的来源，固定 2464）
function getLatestCarsZcid() {
  return CURRENT_ZCID;
}

// 本期在售期次（202611 期）。current_cars 只取这一期。
const CURRENT_ZCID = 2464;
const CURRENT_PERIOD = '202611期';

// 价格档位字符串 → [下限, 上限)（元），如 "10-15万" → [100000, 150000]
function bracketRange(bk) {
  const m = /^(\d+)-(\d+)万$/.exec(String(bk || ''));
  if (!m) return null;
  return [parseInt(m[1], 10) * 10000, parseInt(m[2], 10) * 10000];
}

// 精确排名：最新期次资格池内统计
async function computeRank(times, regTime, latestZcid) {
  const userTimes = parseInt(times, 10);
  const userKey = normalizeRegTime(regTime);

  // count(times > userTimes AND zcid == latest)
  const gt = await db.collection('pool_all')
    .where({ zcid: latestZcid, times: _.gt(userTimes) })
    .count();
  // count(times == userTimes AND reg_time < userKey AND zcid == latest)
  const eq = await db.collection('pool_all')
    .where({ zcid: latestZcid, times: userTimes, reg_time: _.lt(userKey) })
    .count();

  const better = gt.total + eq.total;
  return better + 1;
}

async function calculate(event) {
  const { times, reg_time } = event;
  const window = parseInt(event.window, 10) || 10;

  if (!times || !reg_time) {
    return { error: { code: 400, msg: '请填写次数和注册时间' } };
  }

  const latestZcid = await getLatestPoolZcid();
  const carsZcid = getLatestCarsZcid();

  // 资格池总量（最新期）
  const totalRes = await db.collection('pool_all')
    .where({ zcid: latestZcid }).count();
  const total = totalRes.total;
  if (total === 0) {
    return { error: { code: 500, msg: '资格池为空，请先导入数据' } };
  }

  const rank = await computeRank(times, reg_time, latestZcid);
  const userPct = rank / total * 100;

  const lowAbs = Math.max(1, rank - window);
  const highAbs = rank + window;
  const pctLow = Math.floor(lowAbs / total * 100);
  const pctHigh = Math.ceil(highAbs / total * 100);

  // 加载全部中拍者
  const winners = await fetchAll('winners');
  const winnersEnriched = winners.map(w => ({
    ...w,
    _pct: (w.winner_times || 0) / (w.total_bidders || 1), // 与 Flask 对齐（此处仅备用）
    _brand: w.brand || ''
  }));

  // 按价格档位统计
  const bracketStats = {};
  for (const w of winnersEnriched) {
    const bk = w.price_bracket;
    if (!bk) continue;
    if (!bracketStats[bk]) {
      bracketStats[bk] = {
        total: 0, pctList: [], finalPrices: [], timesList: [],
        dealRatios: [],
        brands: {}, peerMatches: []
      };
    }
    const d = bracketStats[bk];
    d.total += 1;
    const wPct = parseInt(w.winner_rank, 10) / parseInt(w.total_bidders, 10) * 100;
    d.pctList.push(wPct);
    d.timesList.push(parseInt(w.winner_times, 10) || 0);

    const fp = parseFloat(w.final_price);
    const sp = parseFloat(w.start_price);
    if (!isNaN(fp)) {
      d.finalPrices.push(fp);
    }
    if (!isNaN(fp) && !isNaN(sp) && sp > 0) {
      d.dealRatios.push(fp / sp);
    }
    const brand = w._brand || '未知';
    d.brands[brand] = (d.brands[brand] || 0) + 1;

    if (pctLow <= wPct && wPct <= pctHigh) {
      d.peerMatches.push({
        car_name: w.car_name,
        car_link: w.car_link,
        start_price: w.start_price,
        final_price: w.final_price,
        winner_rank: parseInt(w.winner_rank, 10),
        total_bidders: parseInt(w.total_bidders, 10),
        winner_pct: Math.round(wPct * 10) / 10,
        winner_times: parseInt(w.winner_times, 10) || 0,
        result_zcid: w.result_zcid,
        brand: brand,
        pct_diff: Math.round(Math.abs(wPct - userPct) * 10) / 10
      });
    }
  }

  const totalMatches = Object.values(bracketStats)
    .reduce((s, d) => s + d.peerMatches.length, 0);

  const panoramaList = [];
  for (const bk of Object.keys(bracketStats).sort(bracketSortKey)) {
    const d = bracketStats[bk];
    const peerMatches = d.peerMatches;
    const matchCount = peerMatches.length;
    const matchPct = totalMatches > 0
      ? Math.round(matchCount / totalMatches * 1000) / 10 : 0;

    let recommendation;
    if (matchPct >= 25) recommendation = '强烈推荐';
    else if (matchPct >= 15) recommendation = '推荐';
    else if (matchPct >= 5) recommendation = '可考虑';
    else recommendation = '观望';

    const avgWinnerPct = d.pctList.length
      ? Math.round(d.pctList.reduce((a, b) => a + b, 0) / d.pctList.length * 10) / 10 : 0;
    const avgFinal = d.finalPrices.length
      ? Math.round(d.finalPrices.reduce((a, b) => a + b, 0) / d.finalPrices.length) : 0;
    const avgTimes = d.timesList.length
      ? Math.round(d.timesList.reduce((a, b) => a + b, 0) / d.timesList.length * 10) / 10 : 0;

    // 品牌 Top10
    const topBrands = Object.entries(d.brands)
      .sort((a, b) => b[1] - a[1]).slice(0, 10);
    const topBrandsObj = {};
    for (const [k, v] of topBrands) topBrandsObj[k] = v;

    let difficulty;
    if (avgWinnerPct > 0) {
      const ratio = userPct / avgWinnerPct;
      if (ratio < 0.8) difficulty = '容易';
      else if (ratio < 1.2) difficulty = '适中';
      else difficulty = '困难';
    } else {
      difficulty = '—';
    }

    const periodsCovered = new Set(peerMatches.map(m => m.result_zcid)).size;

    peerMatches.sort((a, b) => a.pct_diff - b.pct_diff);

    const top5Sorted = [...peerMatches].sort((a, b) => parseFloat(a.final_price) - parseFloat(b.final_price));
    const top5 = top5Sorted.slice(0, 5).map(m => ({
      car_name: m.car_name, car_link: m.car_link,
      start_price: m.start_price, final_price: m.final_price,
      result_zcid: m.result_zcid, winner_pct: m.winner_pct,
      winner_times: m.winner_times, brand: m.brand
    }));

    const allMatches = peerMatches.map(m => ({
      car_name: m.car_name, car_link: m.car_link,
      start_price: m.start_price, final_price: m.final_price,
      result_zcid: m.result_zcid, winner_pct: m.winner_pct,
      winner_times: m.winner_times,
      brand: m.brand, pct_diff: m.pct_diff
    }));

    const avgDeal = d.dealRatios.length
      ? Math.round(d.dealRatios.reduce((a, b) => a + b, 0) / d.dealRatios.length * 100) / 100 : 0;

    panoramaList.push({
      bracket: bk, match_count: matchCount, match_pct: matchPct,
      recommendation, avg_final_price: avgFinal, avg_winner_times: avgTimes,
      avg_deal_ratio: avgDeal,
      difficulty, periods_covered: periodsCovered,
      top_brands: topBrandsObj, top5, all_matches: allMatches
    });
  }

  panoramaList.sort((a, b) => b.match_pct - a.match_pct);

  // 本期在售：每个档位查本期起拍价落在区间内的车，升序取 5
  const currentCarsByBracket = {};
  if (carsZcid) {
    for (const p of panoramaList) {
      const range = bracketRange(p.bracket);
      if (!range) { currentCarsByBracket[p.bracket] = []; continue; }
      const [lo, hi] = range;
      const res = await db.collection('cars')
        .where({ zcid: carsZcid, start_price: _.and(_.gte(lo), _.lt(hi)) })
        .orderBy('start_price', 'asc')
        .limit(5)
        .get();
      currentCarsByBracket[p.bracket] = res.data.map(c => {
        const predicted = (p.avg_deal_ratio > 0 && c.start_price)
          ? Math.round(c.start_price * p.avg_deal_ratio) : null;
        return {
          car_name: c.car_name,
          car_link: c.car_link,
          start_price: c.start_price,
          limit_price: c.limit_price != null ? c.limit_price : null,
          mileage_km: c.mileage_km,
          fuel_type: c.fuel_type,
          brand: c.brand,
          zcid: c.zcid,
          predicted_final_price: predicted
        };
      });
    }
    for (const p of panoramaList) {
      p.current_cars = currentCarsByBracket[p.bracket] || [];
      p.current_period = CURRENT_PERIOD;
      p.current_zcid = CURRENT_ZCID;
      if (p.current_cars.length && p.avg_deal_ratio > 0) {
        p.recommend_reason = '历史同档平均成交为起拍价的 ' + p.avg_deal_ratio + ' 倍，'
          + '本期在售 ' + p.current_cars.length + ' 台可参考该倍数出价';
      } else {
        p.recommend_reason = '';
      }
    }
  }

  // 期次趋势
  const zcids = [...new Set(winnersEnriched.map(w => w.result_zcid))]
    .sort((a, b) => b - a);
  const periodTrendList = [];
  for (const zcid of zcids) {
    const periodWinners = winnersEnriched.filter(w => w.result_zcid === zcid);
    if (periodWinners.length === 0) continue;
    const totalBidders = parseInt(periodWinners[0].total_bidders, 10) || 0;
    if (totalBidders === 0) continue;

    const userEquivRank = Math.round(userPct / 100 * totalBidders);
    const winnerCount = periodWinners.length;

    let bestMatch = null;
    let bestDiff = Infinity;
    for (const w of periodWinners) {
      const wPctVal = parseInt(w.winner_rank, 10) / parseInt(w.total_bidders, 10) * 100;
      const diff = Math.abs(wPctVal - userPct);
      if (diff < bestDiff) { bestDiff = diff; bestMatch = w; }
    }

    const matchedCar = bestMatch ? {
      car_name: bestMatch.car_name,
      car_link: bestMatch.car_link,
      final_price: bestMatch.final_price,
      bracket: bestMatch.price_bracket
    } : null;

    periodTrendList.push({
      zcid: String(zcid),
      total_bidders: totalBidders,
      winner_count: winnerCount,
      user_equiv_rank: userEquivRank,
      matched_car: matchedCar
    });
  }

  // 全匹配最低成交价
  let minFinalPrice = null;
  for (const d of Object.values(bracketStats)) {
    for (const m of d.peerMatches) {
      const fp = parseFloat(m.final_price);
      if (!isNaN(fp) && (minFinalPrice === null || fp < minFinalPrice)) minFinalPrice = fp;
    }
  }
  if (minFinalPrice !== null) minFinalPrice = Math.round(minFinalPrice);

  return {
    rank,
    total,
    user_pct: Math.round(userPct * 10) / 10,
    total_matches: totalMatches,
    min_final_price: minFinalPrice,
    panorama: panoramaList,
    period_trend: periodTrendList,
    latest_zcid: latestZcid,
    current_zcid: carsZcid,
    current_period: CURRENT_PERIOD
  };
}

exports.main = async (event, context) => {
  const method = event.method || 'calculate';
  try {
    switch (method) {
      case 'calculate':
        return await calculate(event);
      default:
        return { error: { code: 400, msg: `未知方法: ${method}` } };
    }
  } catch (e) {
    return { error: { code: 500, msg: e.message } };
  }
};
