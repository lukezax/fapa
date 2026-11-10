// cloudfunctions/rank/index.js
// 排名查询 v4：竞争力阶梯（纯价格维度）
//
// 算法要点：
// 1. compute_rank：在"最新期次"资格池内 count(times > 输入) + count(times == 输入 AND reg_time < 输入) + 1
// 2. 同类 = 当代"分位带"（用户分位 ±2.5 个百分点起步，带内中拍样本 <30 自动翻倍，上限 ±10 分位）
// 3. 可达深度 = 同类中 分位 ≥ 用户分位（排位不比你好者）——强者的成交推不出用户可达
// 4. 竞争力分（归一） = 近 4 期「每期可达深度同类获单 ÷ 同期该档总成交」的期均，消除期次供给规模差异
// 5. 判定线 = 竞争力分 ≥ 0.3% 或 近4期同类获单 ≥ 3；本期无在售 ⛔
// 6. 前三推荐 = 通过线的档位按价格升序取前三（用户目标：花最少钱买到）
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

// 本期在售期次（202611 期）
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

  const gt = await db.collection('pool_all')
    .where({ zcid: latestZcid, times: _.gt(userTimes) })
    .count();
  const eq = await db.collection('pool_all')
    .where({ zcid: latestZcid, times: userTimes, reg_time: _.lt(userKey) })
    .count();

  return gt.total + eq.total + 1;
}

async function calculate(event) {
  const { times, reg_time } = event;

  if (!times || !reg_time) {
    return { error: { code: 400, msg: '请填写次数和注册时间' } };
  }

  const latestZcid = await getLatestPoolZcid();

  // 资格池总量（最新期）
  const totalRes = await db.collection('pool_all')
    .where({ zcid: latestZcid }).count();
  const total = totalRes.total;
  if (total === 0) {
    return { error: { code: 500, msg: '资格池为空，请先导入数据' } };
  }

  const rank = await computeRank(times, reg_time, latestZcid);
  const userPct = rank / total * 100;

  // 加载全部中拍者，计算历史分位
  const winners = await fetchAll('winners').catch(() => []);
  const winnersPct = winners
    .map(w => {
      const rk = parseInt(w.winner_rank, 10);
      const tb = parseInt(w.total_bidders, 10);
      return isNaN(rk) || isNaN(tb) || tb <= 0 ? null : {
        bracket: w.price_bracket,
        zcid: String(w.result_zcid),
        pct: rk / tb * 100
      };
    })
    .filter(Boolean);

  // 同类分位带：±2.5 分位起步，带内中拍样本 <30 自动翻倍，上限 ±10 分位
  let half = 2.5;
  while (half < 10 &&
    winnersPct.filter(w => userPct - half <= w.pct && w.pct < userPct + half).length < 30) {
    half *= 2;
  }
  if (half > 10) half = 10;

  const bandAll = winnersPct.filter(w => userPct - half <= w.pct && w.pct < userPct + half);
  const deep = bandAll.filter(w => w.pct >= userPct); // 可达深度：排位不比你好

  // 历史期次 + 近 4 期（代际对齐近期市场）
  const periods = [...new Set(winnersPct.map(w => w.zcid))].sort((a, b) => Number(a) - Number(b));
  const recent = periods.slice(-4);

  // 每期每档总成交（竞争力分母）
  const bracketTotalsByPeriod = {};
  for (const w of winnersPct) {
    if (!bracketTotalsByPeriod[w.zcid]) bracketTotalsByPeriod[w.zcid] = {};
    const t = bracketTotalsByPeriod[w.zcid];
    t[w.bracket] = (t[w.bracket] || 0) + 1;
  }

  // 本期在售车辆
  const carsRes = await db.collection('cars')
    .where({ zcid: CURRENT_ZCID }).limit(1000).get();
  const currentCars = carsRes.data || [];
  const carsByBracket = {};
  for (const c of currentCars) {
    const sp = parseFloat(c.start_price);
    if (isNaN(sp)) continue;
    for (const bk of Object.keys(allBrackets(winnersPct, currentCars))) {
      const range = bracketRange(bk);
      if (range && sp >= range[0] && sp < range[1]) {
        if (!carsByBracket[bk]) carsByBracket[bk] = [];
        carsByBracket[bk].push({ ...c, _sp: sp });
      }
    }
  }

  // 竞争力阶梯（纯价格档位，按价格升序）
  const bkSet = allBrackets(winnersPct, currentCars);
  const bks = Object.keys(bkSet).sort((a, b) => bracketSortKey(a) - bracketSortKey(b));

  const ladder = bks.map(bk => {
    let collected = [];      // 近4期中有该档成交的期 → n/T
    let recentOrders = 0;    // 近4期可达深度同类获单总数
    for (const z of recent) {
      const T = (bracketTotalsByPeriod[z] || {})[bk] || 0;
      const n = deep.filter(w => w.zcid === z && w.bracket === bk).length;
      recentOrders += n;
      if (T > 0) collected.push(n / T);
    }
    const scorePct = collected.length
      ? collected.reduce((a, b) => a + b, 0) / collected.length * 100
      : 0;
    const supply = (carsByBracket[bk] || []).length;
    const pass = supply > 0 && (scorePct >= 0.3 || recentOrders >= 3);
    return {
      bracket: bk,
      score_pct: Math.round(scorePct * 100) / 100,   // 竞争力分（归一后，%）
      recent_orders: recentOrders,
      current_supply: supply,
      pass,
      fail: supply === 0 ? 'no_supply' : (!pass ? 'too_few' : '')
    };
  });

  // 前三 = 通过线的档位按价格升序
  const passing = ladder.filter(x => x.pass);
  const top3 = passing.slice(0, 3);
  top3.forEach((x, i) => { x.star = i + 1; });

  // 本期车型推荐（每档起拍价最低 3 台，出价方式统一顶格）
  const topRecommendations = top3.map(x => ({
    bracket: x.bracket,
    star: x.star,
    score_pct: x.score_pct,
    recent_orders: x.recent_orders,
    current_supply: x.current_supply,
    thin: x.recent_orders < 3,
    cars: (carsByBracket[x.bracket] || [])
      .sort((a, b) => a._sp - b._sp)
      .slice(0, 3)
      .map(c => {
        const lp = c.limit_price != null && c.limit_price !== '' ? parseFloat(c.limit_price) : null;
        return {
          car_name: c.car_name,
          car_link: c.car_link,
          start_price: c.start_price,
          limit_price: lp != null && !isNaN(lp) ? lp : null,
          mileage_km: c.mileage_km,
          fuel_type: c.fuel_type
        };
      })
  }));

  // 整体判词
  let verdict;
  if (topRecommendations.length === 0) {
    verdict = '按你的分位，各价格档历史先例均不足，本期竞争力弱，建议降低预期或观望';
  } else if (topRecommendations.every(x => x.thin)) {
    verdict = '仅在个别档位有少量历史先例，先例较少仅供参考，出价直接顶格';
  } else {
    verdict = '按你的分位有竞争力阶梯可循，退而求其次首选「' + topRecommendations[0].bracket + '」，出价直接顶格';
  }

  return {
    ver: 'v4.0.1',
    rank,
    total,
    user_pct: Math.round(userPct * 10) / 10,
    band_half: half,
    band_sample: bandAll.length,
    deep_count: deep.length,
    recent_periods: recent,
    ladder,
    top_recommendations: topRecommendations,
    overall: { has_pass: topRecommendations.length > 0, verdict },
    latest_zcid: latestZcid,
    current_zcid: CURRENT_ZCID,
    current_period: CURRENT_PERIOD
  };
}

// 档位全集：历史成交档 + 本期在售覆盖的档
function allBrackets(winnersPct, currentCars) {
  const s = {};
  winnersPct.forEach(w => { s[w.bracket] = 1; });
  currentCars.forEach(c => {
    const sp = parseFloat(c.start_price);
    if (isNaN(sp)) return;
    const lo = Math.floor(sp / 50000) * 5;
    s[lo + '-' + (lo + 5) + '万'] = 1;
  });
  return s;
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
