// pages/rank/rank.js — 排名查询（tab 首页）· v4 竞争力阶梯
// 输入摇号次数 + 注册时间 → 精确排名 + 竞争力阶梯 + 前三档本期车型推荐
const app = getApp();
const { toWan } = require('../../utils/format');

Page({
  data: {
    times: '',
    regDate: '2011-01-01',
    regTime: '08:00',
    regSec: '00',
    regMs: '000',
    loading: false,
    result: null,
    verdict: '',
    ladderRows: [],
    topCards: [],
    goodPicks: [],
    bandNote: ''
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
    app.callFunction('rank', { times, reg_time: regTimeFull })
      .then(res => {
        // fire-and-forget 保存历史（静默失败）
        const first = (res.top_recommendations || [])[0];
        app.callFunction('histories', {
          method: 'add',
          times,
          reg_time: regTimeFull,
          summary: '排名 ' + res.rank + ' / 共 ' + res.total + ' 人'
            + (first ? ' · 竞争力首推 ' + first.bracket : '')
        }).catch(() => {});

        const decorated = this.decorateResult(res);
        this.setData({
          result: res,
          verdict: decorated.verdict,
          ladderRows: decorated.ladderRows,
          topCards: decorated.topCards,
          goodPicks: decorated.goodPicks,
          bandNote: decorated.bandNote,
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
      verdict: '',
      ladderRows: [],
      topCards: [],
      goodPicks: [],
      bandNote: '',
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
    const first = (this.data.topCards && this.data.topCards[0]) || null;
    const title = '我的位置：第' + r.rank + '名/共' + r.total + '人（前' + r.user_pct + '%）'
      + (first ? '，竞争力首推「' + first.bracket + '」' : '');
    const path = '/pages/rank/rank?times=' + encodeURIComponent(this._lastQuery.times)
      + '&reg_time=' + encodeURIComponent(this._lastQuery.regTimeFull);
    return { title, path };
  },

  // ---------- 数据加工 ----------
  decorateResult(res) {
    const ladder = res.ladder || [];
    const ladderRows = ladder.map(x => ({
      bracket: x.bracket,
      score_text: (x.score_pct != null ? x.score_pct : 0).toFixed(2) + '%',
      recent_orders: x.recent_orders || 0,
      supply: x.current_supply || 0,
      star: x.star || 0,
      pass: !!x.pass,
      noSupply: x.fail === 'no_supply',
      thin: x.pass && (x.recent_orders || 0) < 3
    }));

    const topCards = (res.top_recommendations || []).map(rec => ({
      star: rec.star,
      bracket: rec.bracket,
      score_text: (rec.score_pct != null ? rec.score_pct : 0).toFixed(2) + '%',
      recent_orders: rec.recent_orders || 0,
      thin: rec.recent_orders < 3,
      cars: (rec.cars || []).map(c => ({
        car_name: c.car_name,
        car_link: c.car_link,
        start_text: toWan(c.start_price),
        limit_text: c.limit_price != null ? '顶格 ' + toWan(c.limit_price) : '顶格出价',
        meta: [c.fuel_type, c.mileage_km ? (c.mileage_km / 10000).toFixed(1) + '万km' : '']
          .filter(Boolean).join(' · ')
      }))
    }));

    const goodPicks = (res.good_picks || []).map(g => ({
      bracket: g.bracket,
      cars: (g.cars || []).map(c => ({
        car_name: c.car_name,
        car_link: c.car_link,
        limit_text: c.limit_price != null ? toWan(c.limit_price) : '—',
        meta: [c.fuel_type, c.mileage_km ? (c.mileage_km / 10000).toFixed(1) + '万km' : '']
          .filter(Boolean).join(' · '),
        tags: c.tags || []
      }))
    }));

    return {
      verdict: (res.overall && res.overall.verdict) || '',
      ladderRows,
      topCards,
      goodPicks,
      bandNote: '同类人 = 分位与你相近（±' + (res.band_half || 2.5) + '%）且排位不比你好的历史中拍者 '
        + ((res.deep_count || 0)) + ' 人；竞争力分 = 近 4 期「同类获单 ÷ 同期档位成交」的期均'
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
