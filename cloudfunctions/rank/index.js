// cloudfunctions/rank/index.js
// 排名查询 v4：竞争力阶梯（纯价格维度）
//
// 算法要点：
// 1. compute_rank：在"最新期次"资格池内 count(times > 输入) + count(times == 输入 AND reg_time < 输入) + 1
// 2. 同类 = 当代"分位带"（用户分位 ±2.5 个百分点起步，带内中拍样本 <30 自动翻倍，上限 ±10 分位）
// 3. 可达深度 = 同类中 分位 ≥ 用户分位（排位不比你好者）——强者的成交推不出用户可达
// 4. 档位概率 = 「分位带在该档成交人数 ÷ 该档全部成交人数」（分带份额），再跨档位归一（Σ=100%）
//    双窗口：历年累计（全史）与最近 6 期
// 5. 达标线 = 归一概率 ≥ 5%（任一窗口）；本期无在售 ⛔
// 6. 前三推荐 = 达标档位按价格升序取前三（用户口径：尽量少花钱，概率同时给出）
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const _ = db.command;

// 价格档排序键
function bracketSortKey(b) {
  const m = /^(\d+)/.exec(String(b || ''));
  return m ? parseInt(m[1], 10) : 9999;
}

// 好车优先级（用户口径，命中越多越靠前，字典序比较）：
// 1. 排放国三以上（不含，即国四/国五/国六）且无抵押
// 2. 有钥匙
// 3. 有车牌
// 4. 额外费用低于 1000
// 5. 证件拍照齐全（行驶证 + 登记证）
const GOOD_FEE_LIMIT = 1000;

function goodCriteria(c) {
  return [
    (c.emission_standard === '国四' || c.emission_standard === '国五' || c.emission_standard === '国六')
      && c.is_mortgaged === '否' ? 1 : 0,
    c.has_key === '有' ? 1 : 0,
    c.has_plate === '有' ? 1 : 0,
    (c.total_extra_fee != null && c.total_extra_fee !== '' && parseFloat(c.total_extra_fee) < GOOD_FEE_LIMIT) ? 1 : 0,
    (c.has_license === '有' && c.has_registration === '有') ? 1 : 0
  ];
}

function goodTags(sc, c) {
  const tags = [];
  if (sc[0]) tags.push(c.emission_standard + '·无抵押');
  if (sc[1]) tags.push('有钥匙');
  if (sc[2]) tags.push('有车牌');
  if (sc[3]) tags.push('额外费用低');
  if (sc[4]) tags.push('证照齐全');
  return tags;
}

function cmpGoodScore(a, b) {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return b[i] - a[i];
  }
  return 0;
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

  // 历史期次 + 近 6 期（近期市场参考）
  const periods = [...new Set(winnersPct.map(w => w.zcid))].sort((a, b) => Number(a) - Number(b));
  const recent = periods.slice(-6);

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

  // 双窗口统计：分带份额 = 带内成交/档位总成交；归一概率 = 份额/各档份额之和
  const totA = {}, totB = {}, cntA = {}, cntB = {};
  for (const w of winnersPct) {
    totA[w.bracket] = (totA[w.bracket] || 0) + 1;
    if (recent.includes(w.zcid)) totB[w.bracket] = (totB[w.bracket] || 0) + 1;
  }
  for (const w of bandAll) {
    cntA[w.bracket] = (cntA[w.bracket] || 0) + 1;
    if (recent.includes(w.zcid)) cntB[w.bracket] = (cntB[w.bracket] || 0) + 1;
  }
  function windowStats(cnt, tot) {
    const share = {}, prob = {};
    let S = 0;
    for (const bk of bks) {
      const T = tot[bk] || 0;
      if (T <= 0) continue;
      share[bk] = (cnt[bk] || 0) / T;
      S += share[bk];
    }
    for (const bk of Object.keys(share)) prob[bk] = share[bk] / S * 100;
    return { share, prob };
  }
  const winA = windowStats(cntA, totA);   // 历年累计
  const winB = windowStats(cntB, totB);   // 最近 6 期

  const r2 = v => v == null ? null : Math.round(v * 100) / 100;
  const PASS_PROB = 5;   // 归一概率达标线（%），九档平均约 11%，5% ≈ 半水位

  const ladder = bks.map(bk => {
    const supply = (carsByBracket[bk] || []).length;
    const probA = winA.prob[bk] == null ? 0 : winA.prob[bk];
    const probB = winB.prob[bk] == null ? 0 : winB.prob[bk];
    const pass = supply > 0 && (probA >= PASS_PROB || probB >= PASS_PROB);
    return {
      bracket: bk,
      prob_pct: r2(winA.prob[bk]),      // 归一概率 · 历年累计（%）
      prob_pct6: r2(winB.prob[bk]),     // 归一概率 · 最近 6 期（%）
      share_pct: r2(winA.share[bk] != null ? winA.share[bk] * 100 : null),   // 分带份额原始值（%）便于口径展示
      share_pct6: r2(winB.share[bk] != null ? winB.share[bk] * 100 : null),
      current_supply: supply,
      pass,
      fail: supply === 0 ? 'no_supply' : (!pass ? 'below_line' : '')
    };
  });

  // 前三 = 达标档位按价格升序（尽量少花钱，概率同时展示）
  const passing = ladder.filter(x => x.pass);
  const top3 = passing.slice(0, 3);
  top3.forEach((x, i) => { x.star = i + 1; });

  // 本期车型推荐（每档起拍价最低 3 台，出价方式统一顶格）
  const topRecommendations = top3.map(x => ({
    bracket: x.bracket,
    star: x.star,
    prob_pct: x.prob_pct,
    prob_pct6: x.prob_pct6,
    current_supply: x.current_supply,
    thin: x.prob_pct != null && x.prob_pct < PASS_PROB,   // 仅近6期口径达标
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

  // 好车推荐：每个价格档位按优先级元组评选，取前 2 台（命中优先级需 ≥1，否则视为无亮点车）
  const goodPicks = bks
    .map(bk => ({
      bracket: bk,
      cars: (carsByBracket[bk] || [])
        .map(c => {
          const sc = goodCriteria(c);
          const lp = c.limit_price != null && c.limit_price !== '' ? parseFloat(c.limit_price) : null;
          return {
            score: sc,
            tags: goodTags(sc, c),
            car_name: c.car_name,
            car_link: c.car_link,
            start_price: c.start_price,
            start_num: c._sp,
            limit_price: lp != null && !isNaN(lp) ? lp : null,
            mileage_km: c.mileage_km,
            fuel_type: c.fuel_type
          };
        })
        .filter(x => x.score.some(v => v === 1))
        .sort((a, b) => cmpGoodScore(a.score, b.score) || a.start_num - b.start_num)
        .slice(0, 2)
        .map(({ score, start_num, ...rest }) => rest)
    }))
    .filter(x => x.cars.length > 0);

  // 整体判词
  let verdict;
  if (topRecommendations.length === 0) {
    verdict = '按你的分位，各档位概率均不达标，本期建议观望或放宽预算';
  } else if (topRecommendations.every(x => x.thin)) {
    verdict = '仅「' + topRecommendations[0].bracket + '」等档位按近 6 期口径达标，历史先例偏薄，仅供参考，出价直接顶格';
  } else {
    verdict = '按你的分位，概率达标的最便宜三档从「' + topRecommendations[0].bracket + '」起（概率 ' + topRecommendations[0].prob_pct + '%），出价直接顶格';
  }

  return {
    ver: 'v4.3.0',
    rank,
    total,
    user_pct: Math.round(userPct * 10) / 10,
    band_half: half,
    band_sample: bandAll.length,
    band_sample6: bandAll.filter(w => recent.includes(w.zcid)).length,
    deep_count: bandAll.length,
    recent_periods: recent,
    ladder,
    top_recommendations: topRecommendations,
    good_picks: goodPicks,
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
