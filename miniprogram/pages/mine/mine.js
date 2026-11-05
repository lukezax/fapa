// pages/mine/mine.js — 我的页
const format = require('../../utils/format');
const ad = require('../../utils/ad');

Page({
  data: {
    loading: true,
    favorites: [],
    favoriteTotal: 0,
    histories: [],
    bannerMine: ad.AD_UNITS.bannerMine,
    bannerError: false
  },

  // 每次显示都刷新（收藏/历史会变）
  onShow() {
    this.loadData();
  },

  loadData() {
    this.setData({ loading: true });
    const app = getApp();
    Promise.all([
      app.callFunction('favorites', { method: 'list' }),
      app.callFunction('histories', { method: 'list' })
    ])
      .then(results => {
        const favList = results[0].list || [];
        const hisList = results[1].list || [];
        const histories = hisList.map((h, idx) => Object.assign({}, h, {
          _key: idx,
          regTimeText: format.formatRegTime(h.reg_time),
          createdText: this.formatTime(h.created_at)
        }));
        this.setData({
          loading: false,
          favoriteTotal: favList.length,
          histories
        });
        // 前 20 条并发取车辆详情，其余只计数
        this.loadFavoriteDetails(favList.slice(0, 20));
      })
      .catch(err => {
        this.setData({ loading: false });
        wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' });
      });
  },

  // 并发拉取收藏车辆详情（失败项降级显示 car_link 本身）
  loadFavoriteDetails(links) {
    const app = getApp();
    Promise.all(links.map(link =>
      app.callFunction('cars', { method: 'detail', car_link: link })
        .then(res => {
          const price = res && res.final_price;
          return {
            car_link: link,
            car_name: (res && res.car_name) || link,
            finalPriceText: price ? format.toWan(price) : ''
          };
        })
        .catch(() => ({
          car_link: link,
          car_name: link,
          finalPriceText: ''
        }))
    )).then(favorites => {
      this.setData({ favorites });
    });
  },

  // created_at → "yyyy-MM-dd HH:mm"（兼容 Date / 时间戳 / 字符串）
  formatTime(t) {
    if (!t) return '';
    let d = t;
    if (typeof t === 'number') d = new Date(t);
    else if (typeof t === 'string') d = new Date(t);
    if (!(d instanceof Date) || isNaN(d.getTime())) return String(t);
    const pad = n => (n < 10 ? '0' + n : '' + n);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  },

  onFavTap(e) {
    const link = e.currentTarget.dataset.link;
    if (!link) return;
    wx.navigateTo({ url: '/pages/car-detail/car-detail?car_link=' + encodeURIComponent(link) });
  },

  onHisTap(e) {
    const times = e.currentTarget.dataset.times;
    const regTime = e.currentTarget.dataset.regTime;
    if (times == null || !regTime) return;
    wx.navigateTo({
      url: '/pages/rank/rank?times=' + times + '&reg_time=' + encodeURIComponent(regTime)
    });
  },

  clearHistory() {
    wx.showModal({
      title: '清空查询历史',
      content: '确定要清空全部查询历史吗？',
      confirmText: '清空',
      confirmColor: '#e74c3c',
      success: res => {
        if (!res.confirm) return;
        getApp().callFunction('histories', { method: 'clear' })
          .then(() => {
            wx.showToast({ title: '已清空', icon: 'success' });
            this.loadData();
          })
          .catch(err => {
            wx.showToast({ title: (err && err.message) || '清空失败', icon: 'none' });
          });
      }
    });
  },

  onBannerError() {
    this.setData({ bannerError: true });
  }
});