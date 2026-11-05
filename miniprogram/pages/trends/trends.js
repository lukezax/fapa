// pages/trends/trends.js — 数据分析页
const echarts = require('../../components/ec-canvas/echarts');

Page({
  data: {
    loading: true,
    myBrief: null,
    bracketTimes: [],
    bracketDist: [],
    timesDist: [],
    brandTop: [],
    stats: null,
    timesMedian: null,
    timesGe80Pct: null,
    // 图表 ec 对象：数据到达后再 setData，配合 wx:if 挂载 ec-canvas 触发 onInit
    decisionEc: null
  },

  onLoad() {
    this.loadOverview();
  },

  loadOverview() {
    this.setData({ loading: true });
    getApp().callFunction('trends', { method: 'overview' })
      .then(res => {
        const bracketTimes = res.bracket_times || [];
        const bracketDist = res.bracket_dist || [];
        this.setData({
          loading: false,
          bracketTimes,
          bracketDist,
          timesDist: this.withPercent(res.times_dist || [], 'count'),
          brandTop: this.withPercent(res.brand_top || [], 'count'),
          stats: res.stats || null,
          timesMedian: res.times_median != null ? res.times_median : null,
          timesGe80Pct: res.times_ge80_pct != null ? res.times_ge80_pct : null,
          decisionEc: (bracketTimes.length || bracketDist.length)
            ? { onInit: this.initDecisionChart.bind(this) } : null
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
        if (this._decisionChart) this._decisionChart.setOption(this.buildDecisionOption());
      })
      .catch(() => {});
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

  // ---- 价位段决策图：柱=该档中拍人数，折线=平均摇号次数，参考线=你的次数 ----
  initDecisionChart(canvas, width, height, dpr) {
    const chart = echarts.init(canvas, null, { width, height, devicePixelRatio: dpr });
    canvas.setChart(chart);
    chart.setOption(this.buildDecisionOption());
    this._decisionChart = chart;
    return chart;
  },

  buildDecisionOption() {
    const counts = this.data.bracketDist;
    const timesByBracket = {};
    for (const b of this.data.bracketTimes) timesByBracket[b.bracket] = b;
    const brackets = counts.map(i => i.bracket);
    const pick = (b, key) => (timesByBracket[b] && timesByBracket[b][key] != null) ? timesByBracket[b][key] : null;
    const userTimes = this.data.myBrief ? Number(this.data.myBrief.times) : null;

    const option = {
      color: ['#e74c3c', '#3498db', '#f39c12', '#16a085'],
      legend: {
        top: 0,
        data: ['成交数量', '平均摇号次数', '最高次数', '最低次数'].concat(userTimes ? ['你的次数'] : []),
        textStyle: { fontSize: 10 }
      },
      grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: brackets,
        axisLabel: { fontSize: 9, color: '#57606f', rotate: 30 },
        axisLine: { lineStyle: { color: '#d0d0d8' } }
      },
      yAxis: [
        {
          type: 'value',
          name: '人数',
          nameTextStyle: { fontSize: 9, color: '#57606f' },
          axisLabel: { fontSize: 10, color: '#57606f' },
          splitLine: { lineStyle: { color: '#f0f2f5' } }
        },
        {
          type: 'value',
          name: '次数',
          nameTextStyle: { fontSize: 9, color: '#57606f' },
          axisLabel: { fontSize: 10, color: '#57606f' },
          splitLine: { show: false }
        }
      ],
      series: [
        {
          name: '成交数量',
          type: 'bar',
          data: counts.map(i => i.count),
          barWidth: '45%',
          itemStyle: { color: '#e74c3c', borderRadius: [4, 4, 0, 0] }
        },
        {
          name: '平均摇号次数',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          data: brackets.map(b => pick(b, 'avg_times')),
          itemStyle: { color: '#3498db' },
          lineStyle: { color: '#3498db', width: 3 }
        },
        {
          name: '最高次数',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          data: brackets.map(b => pick(b, 'max_times')),
          itemStyle: { color: '#f39c12' },
          lineStyle: { color: '#f39c12', type: 'dashed' }
        },
        {
          name: '最低次数',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          data: brackets.map(b => pick(b, 'min_times')),
          itemStyle: { color: '#16a085' },
          lineStyle: { color: '#16a085', type: 'dashed' }
        }
      ]
    };

    if (userTimes > 0) {
      option.series[1].markLine = {
        silent: true,
        symbol: 'none',
        data: [{ yAxis: userTimes }],
        lineStyle: { color: '#27ae60', type: 'solid' },
        label: { formatter: '你的次数 ' + userTimes, fontSize: 9, color: '#27ae60' }
      };
    }
    return option;
  }
});