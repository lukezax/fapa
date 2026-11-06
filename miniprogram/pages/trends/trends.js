// pages/trends/trends.js — 本期（202611期 / 2464）在售车辆分析
// 历史中拍数据只用于 rank 页的推荐，本页只统计本期在售车辆。
const echarts = require('../../components/ec-canvas/echarts');
const { CURRENT_ZCID, CURRENT_PERIOD } = require('../../utils/constants');

Page({
  data: {
    loading: true,
    currentZcid: CURRENT_ZCID,
    currentPeriod: CURRENT_PERIOD,
    myBrief: null,
    total: 0,
    brandTop: [],
    courtTop: [],
    fuelDist: [],
    emissionDist: [],
    priceDist: [],
    mileageDist: [],
    condition: null,
    history: null,
    // 图表 ec 对象：数据到达后再 setData，配合 wx:if 挂载 ec-canvas 触发 onInit
    priceEc: null
  },

  onLoad() {
    this.loadOverview();
  },

  loadOverview() {
    this.setData({ loading: true });
    getApp().callFunction('trends', { method: 'overview' })
      .then(res => {
        const priceDist = this.withPercent(res.price_dist || [], 'count');
        this.setData({
          loading: false,
          total: res.total || 0,
          brandTop: this.withPercent(res.brand_top || [], 'count'),
          courtTop: this.withPercent(res.court_top || [], 'count'),
          fuelDist: res.fuel_dist || [],
          emissionDist: res.emission_dist || [],
          priceDist,
          mileageDist: this.withPercent(res.mileage_dist || [], 'count'),
          condition: res.condition || null,
          history: res.history || null,
          priceEc: priceDist.length ? { onInit: this.initPriceChart.bind(this) } : null
        });
      })
      .catch(err => {
        this.setData({ loading: false });
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' });
      });

    // 我的速览：最近一次排名查询（静默失败）
    getApp().callFunction('histories', { method: 'list' })
      .then(res => {
        const h = (res.list || [])[0];
        if (!h) return;
        const m = /排名 (\d+) \/ 共 (\d+) 人/.exec(h.summary || '');
        this.setData({
          myBrief: {
            times: h.times,
            rankText: m ? `排名 ${m[1]} / ${m[2]} 人` : (h.summary || ''),
            pct: m ? (parseInt(m[1], 10) / parseInt(m[2], 10) * 100).toFixed(1) : ''
          }
        });
      })
      .catch(() => {});
  },

  goCarsTab() {
    wx.switchTab({ url: '/pages/cars/cars' });
  },

  goRankTab() {
    wx.switchTab({ url: '/pages/rank/rank' });
  },

  goRankFull() {
    const b = this.data.myBrief;
    if (!b) return;
    const app = getApp();
    app.callFunction('histories', { method: 'list' })
      .then(res => {
        const h = (res.list || [])[0];
        if (h) app.globalData.pendingRankQuery = { times: h.times, reg_time: h.reg_time };
      })
      .catch(() => {})
      .then(() => wx.switchTab({ url: '/pages/rank/rank' }));
  },

  // 计算每项占最大值的百分比（用于条形宽度）
  withPercent(list, key) {
    const max = list.reduce((m, item) => Math.max(m, item[key] || 0), 0);
    return list.map(item => Object.assign({}, item, {
      percent: max ? Math.round((item[key] || 0) / max * 100) : 0
    }));
  },

  // ---- 本期起拍价档位分布（柱状图）----
  initPriceChart(canvas, width, height, dpr) {
    const chart = echarts.init(canvas, null, { width, height, devicePixelRatio: dpr });
    canvas.setChart(chart);
    chart.setOption(this.buildPriceOption());
    this._priceChart = chart;
    return chart;
  },

  buildPriceOption() {
    const brackets = this.data.priceDist.map(i => i.bracket);
    const counts = this.data.priceDist.map(i => i.count);
    return {
      color: ['#e74c3c'],
      grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: brackets,
        axisLabel: { fontSize: 9, color: '#57606f', rotate: 30 },
        axisLine: { lineStyle: { color: '#d0d0d8' } }
      },
      yAxis: {
        type: 'value',
        name: '台数',
        nameTextStyle: { fontSize: 9, color: '#57606f' },
        axisLabel: { fontSize: 10, color: '#57606f' },
        splitLine: { lineStyle: { color: '#f0f2f5' } }
      },
      series: [{
        name: '在售台数',
        type: 'bar',
        data: counts,
        barWidth: '50%',
        itemStyle: { color: '#e74c3c', borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: 'top', fontSize: 9, color: '#57606f' }
      }]
    };
  }
});
