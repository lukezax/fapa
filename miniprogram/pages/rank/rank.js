// pages/rank/rank.js — 排名查询（tab 首页）
// 输入摇号次数 + 注册时间 → 精确排名 + 各价格档位推荐 + 期次趋势
const app = getApp();
const { PRICE_BRACKETS } = require('../../utils/constants');
const { toWan, formatPeriod } = require('../../utils/format');

Page({
  data: {
    times: '',
    regDate: '2011-01-01',
    regTime: '08:00',
    regSec: '00',
    regMs: '000',
    loading: false,
    result: null,
    panoramaRows: [],
    bracketCards: [],
    periodTrend: [],
    minFinalPriceText: '',
    sampleNote: '',
    windowPct: 10
  },

  // 从 mine 页历史点击进入：options.times / options.reg_time（已 encodeURIComponent）
  onLoad(options) {
    if (options && options.times && options.reg_time) {
      const times = decodeURIComponent(options.times);
      const regTimeFull = decodeURIComponent(options.reg_time);
      const p = this.parseRegTime(regTimeFull);
      this.setData({
        times,
        regDate: p.date,
        regTime: p.time,
        regSec: p.sec,
        regMs: p.ms
      });
      this.doQuery(times, regTimeFull);
    }
  },

  // 数据分析页「查看完整推荐」跳转：消费全局待查询参数
  onShow() {
    const q = getApp().globalData.pendingRankQuery;
    if (!q || !q.times || !q.reg_time) return;
    getApp().globalData.pendingRankQuery = null;
    if (this.data.loading) return;
    const p = this.parseRegTime(q.reg_time);
    this.setData({
      times: q.times,
      regDate: p.date,
      regTime: p.time,
      regSec: p.sec,
      regMs: p.ms
    });
    this.doQuery(String(q.times), q.reg_time);
  },

  // ---------- 输入 ----------
  onTimesInput(e) {
    this.setData({ times: e.detail.value });
  },
  onDateChange(e) {
    this.setData({ regDate: e.detail.value });
  },
  onTimeChange(e) {
    this.setData({ regTime: e.detail.value });
  },
  onSecInput(e) {
    this.setData({ regSec: e.detail.value });
  },
  onMsInput(e) {
    this.setData({ regMs: e.detail.value });
  },

  onQuery() {
    if (this.data.loading) return;
    const { times, regDate, regTime, regSec, regMs } = this.data;

    const t = Number(String(times).trim());
    if (!/^\d+$/.test(String(times).trim()) || !Number.isInteger(t) || t < 1) {
      wx.showToast({ title: '请输入有效的摇号次数（≥1 的整数）', icon: 'none' });
      return;
    }
    if (!/^\d{1,2}$/.test(String(regSec).trim()) || Number(regSec) > 59) {
      wx.showToast({ title: '秒需为 00-59', icon: 'none' });
      return;
    }
    if (!/^\d{1,3}$/.test(String(regMs).trim()) || Number(regMs) > 999) {
      wx.showToast({ title: '毫秒需为 000-999', icon: 'none' });
      return;
    }

    const sec = this.padNum(regSec, 2);
    const ms = this.padNum(regMs, 3);
    const regTimeFull = regDate + ' ' + regTime + ':' + sec + '.' + ms;
    this.doQuery(String(t), regTimeFull);
  },

  // ---------- 查询 ----------
  doQuery(times, regTimeFull) {
    this.setData({ loading: true });
    this._lastQuery = { times, regTimeFull };
    app.callFunction('rank', { times, reg_time: regTimeFull, window_pct: 10 })
      .then(res => {
        // fire-and-forget 保存历史（静默失败）
        app.callFunction('histories', {
          method: 'add',
          times,
          reg_time: regTimeFull,
          summary: '排名 ' + res.rank + ' / 共 ' + res.total + ' 人'
        }).catch(() => {});

        const decorated = this.decorateResult(res);
        this.setData({
          result: res,
          panoramaRows: decorated.panoramaRows,
          bracketCards: decorated.bracketCards,
          periodTrend: decorated.periodTrend,
          minFinalPriceText: decorated.minFinalPriceText,
          loading: false
        });
      })
      .catch(err => {
        this.setData({ loading: false });
        wx.showToast({ title: (err && err.message) || '查询失败', icon: 'none' });
      });
  },

  onReset() {
    this.setData({
      result: null,
      panoramaRows: [],
      bracketCards: [],
      periodTrend: [],
      minFinalPriceText: '',
      sampleNote: '',
      windowPct: 10,
      loading: false
    });
  },

  onCarTap(e) {
    const link = e.currentTarget.dataset.link;
    if (!link) return;
    wx.navigateTo({
      url: '/pages/car-detail/car-detail?car_link=' + encodeURIComponent(link)
    });
  },

  // 结果分享：路径携带完整查询参数，好友打开自动复现结果
  onShareAppMessage() {
    if (!this.data.result || !this._lastQuery) {
      return {
        title: '京慧车讯 · 在历史成交数据中找到适合你的车',
        path: '/pages/intro/intro'
      };
    }
    const r = this.data.result;
    const top = (this.data.bracketCards && this.data.bracketCards[0]) || null;
    const title = '我的位置：第' + r.rank + '名/共' + r.total + '人（前' + r.user_pct + '%）'
      + (top ? '，重点关注「' + top.bracket + '」' : '');
    const path = '/pages/rank/rank?times=' + encodeURIComponent(this._lastQuery.times)
      + '&reg_time=' + encodeURIComponent(this._lastQuery.regTimeFull);
    return { title, path };
  },

  // ---------- 数据加工 ----------
  // 全景图：与 PRICE_BRACKETS 9 档对齐，panorama 缺失的档补 0 灰条，多出的档追加在后
  alignPanorama(panorama) {
    const list = panorama || [];
    const byBracket = {};
    list.forEach(p => { byBracket[p.bracket] = p; });
    const rows = [];
    PRICE_BRACKETS.forEach(b => {
      const p = byBracket[b];
      rows.push(p ? this.panoRow(p) : { bracket: b, success_rate: 0, barClass: 'rank-bar-gray' });
    });
    list.forEach(p => {
      if (PRICE_BRACKETS.indexOf(p.bracket) === -1) rows.push(this.panoRow(p));
    });
    return rows;
  },

  panoRow(p) {
    const pct = Math.min(100, p.success_rate || 0);
    return {
      bracket: p.bracket,
      success_rate: pct,
      barClass: this.barClassFor(pct)
    };
  },

  barClassFor(pct) {
    if (pct >= 70) return 'rank-bar-red';
    if (pct >= 40) return 'rank-bar-orange';
    return 'rank-bar-gray';
  },

  decorateBracket(p, userTimes, historyPeriods) {
    const topBrands = p.top_brands || {};
    const brandChips = Object.keys(topBrands)
      .slice(0, 5)
      .map(brand => ({ brand, count: topBrands[brand] }));
    const top5 = (p.top5 || []).map(m => ({
      car_name: m.car_name,
      car_link: m.car_link,
      final_price_text: toWan(m.final_price),
      times_text: (m.winner_times || 0) + '次',
      result_zcid: m.result_zcid
    }));
    const avgTimes = p.avg_winner_times || 0;
    const diff = Math.round(((userTimes || 0) - avgTimes) * 10) / 10;
    const currentCars = (p.current_cars || []).map(c => ({
      car_name: c.car_name,
      car_link: c.car_link,
      start_text: toWan(c.start_price),
      pred_text: c.predicted_final_price ? '预计 ' + toWan(c.predicted_final_price) : '',
      bid_text: c.suggested_bid != null
        ? '建议 ' + toWan(c.suggested_bid) + (c.capped ? '（顶格）' : '')
          + (c.success_rate != null ? ' · 成功率 ' + c.success_rate + '%' : '')
        : '',
      meta: [c.fuel_type, c.mileage_km ? (c.mileage_km / 10000).toFixed(1) + '万km' : '']
        .filter(Boolean).join(' · ')
    }));
    return {
      bracket: p.bracket,
      recommendation: p.recommendation || '',
      recClass: this.recClassFor(p.recommendation),
      successText: (p.success_rate || 0) + '%',
      coverText: (p.periods_covered || 0) + '/' + (historyPeriods || 15) + ' 期',
      match_count: p.match_count || 0,
      avgFinalText: toWan(p.avg_final_price),
      avgTimesText: avgTimes ? String(avgTimes) : '—',
      timesDiffText: avgTimes && userTimes ? '你' + (diff >= 0 ? '+' : '') + diff + '次' : '',
      timesDiffClass: diff >= 0 ? 'rank-diff-plus' : 'rank-diff-minus',
      periods_covered: p.periods_covered || 0,
      brandChips,
      currentCars,
      top5
    };
  },

  recClassFor(rec) {
    switch (rec) {
      case '强烈推荐': return 'rank-rec-strong';
      case '推荐': return 'rank-rec-good';
      case '可考虑': return 'rank-rec-maybe';
      default: return 'rank-rec-wait';
    }
  },

  decorateResult(res) {
    const userTimes = parseInt(this.data.times, 10) || 0;
    const historyPeriods = res.history_periods || 15;
    const panoramaRows = this.alignPanorama(res.panorama);
    const bracketCards = (res.panorama || []).map(p => this.decorateBracket(p, userTimes, historyPeriods));
    const periodTrend = (res.period_trend || []).map(t => {
      const row = {
        zcid: t.zcid,
        zcid_text: formatPeriod(t.zcid),
        total_bidders: t.total_bidders,
        winner_count: t.winner_count,
        user_equiv_rank: t.user_equiv_rank,
        matched_car: null
      };
      if (t.matched_car) {
        row.matched_car = {
          car_name: t.matched_car.car_name,
          car_link: t.matched_car.car_link,
          final_price_text: toWan(t.matched_car.final_price)
        };
      }
      return row;
    });
    const top = bracketCards[0] || null;
    return {
      panoramaRows,
      bracketCards,
      topAdvice: top ? {
        bracket: top.bracket,
        success: top.successText,
        cover: top.coverText,
        times: top.avgTimesText,
        diff: (top.timesDiffText || '').replace('你', '')
      } : null,
      sampleNote: res.sample_insufficient
        ? '同分位历史样本较少（' + (res.peer_count || 0) + ' 人），推荐仅供参考'
        : '',
      windowPct: res.window_pct || 10,
      periodTrend,
      minFinalPriceText: toWan(res.min_final_price)
    };
  },

  // ---------- 工具 ----------
  parseRegTime(rt) {
    const parts = String(rt || '').split(' ');
    const date = parts[0] || '2011-01-01';
    const timePart = parts[1] || '08:00:00.000';
    const t = timePart.split(':');
    const hh = t[0] || '08';
    const mm = t[1] || '00';
    const secMs = (t[2] || '00.000').split('.');
    return {
      date,
      time: hh + ':' + mm,
      sec: secMs[0] || '00',
      ms: secMs[1] || '000'
    };
  },

  padNum(v, len) {
    let s = String(v == null ? '' : v).trim();
    while (s.length < len) s = '0' + s;
    return s;
  }
});