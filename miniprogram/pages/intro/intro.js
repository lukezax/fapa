// pages/intro/intro.js — 应用介绍（默认首页）
Page({
  goRank() {
    wx.switchTab({ url: '/pages/rank/rank' });
  },
  goCars() {
    wx.switchTab({ url: '/pages/cars/cars' });
  },
  onShareAppMessage() {
    return {
      title: '京慧车讯 · 15 期成交数据，帮你选对车',
      path: '/pages/intro/intro'
    };
  }
});
