// pages/intro/intro.js — 应用介绍（默认首页）
const { enableShareMenu, isSinglePage, guideTimelineShare, singlePageTip } = require('../../utils/share');

Page({
  data: {
    singlePage: false   // 朋友圈单页模式：tabBar 隐藏，switchTab 不可用
  },

  onLoad() {
    this.setData({ singlePage: isSinglePage() });
    enableShareMenu();
  },

  onShow() {
    enableShareMenu();
  },

  goRank() {
    if (this.data.singlePage) { singlePageTip(); return; }
    wx.switchTab({ url: '/pages/rank/rank' });
  },
  goCars() {
    if (this.data.singlePage) { singlePageTip(); return; }
    wx.switchTab({ url: '/pages/cars/cars' });
  },
  onTimelineTap() {
    guideTimelineShare();
  },
  onShareAppMessage() {
    return {
      title: '京慧车讯 · 15 期成交数据，帮你选本期好车',
      path: '/pages/intro/intro'
    };
  },

  onShareTimeline() {
    return {
      title: '京慧车讯 · 15 期成交数据，帮你选本期好车',
      query: ''
    };
  }
});
