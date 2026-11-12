// utils/share.js — 分享（好友 / 朋友圈）公共逻辑
//
// 微信限制：小程序**无法**用代码直接触发「分享到朋友圈」。
// 只能在页面里实现 onShareTimeline，然后由用户点右上角 ··· →「分享到朋友圈」。
// 所以页面上的「分享到朋友圈」按钮只负责唤起菜单 + 给一句提示。

// 朋友圈单页模式 scene（此时无 tabBar、不可跳转、**无登录态**）
//
// 重要：单页模式下云开发默认不可用，需在云开发控制台开启「未登录访问」，
// wx.cloud.callFunction 才能返回数据。未开启时页面会回退到分享链接自带的摘要
// （rank 的 r/t/u/b/p 参数、car-detail 的 n/p 参数）。
const TIMELINE_SCENE = 1154;

// 让「···」菜单同时出现「转发给朋友」和「分享到朋友圈」
function enableShareMenu() {
  if (typeof wx.showShareMenu !== 'function') return;
  wx.showShareMenu({
    withShareTicket: false,
    menus: ['shareAppMessage', 'shareTimeline'],
    fail() { /* 低版本基础库忽略 */ }
  });
}

// 是否处于朋友圈单页模式
function isSinglePage() {
  try {
    const opts = (wx.getLaunchOptionsSync && wx.getLaunchOptionsSync()) || {};
    return Number(opts.scene) === TIMELINE_SCENE;
  } catch (e) {
    return false;
  }
}

// 引导用户分享到朋友圈
function guideTimelineShare() {
  if (typeof wx.showShareMenu === 'function') {
    wx.showShareMenu({ menus: ['shareAppMessage', 'shareTimeline'], fail() {} });
  }
  wx.showModal({
    title: '分享到朋友圈',
    content: '点右上角 ··· ，选择「分享到朋友圈」即可。',
    showCancel: false,
    confirmText: '知道了'
  });
}

// 单页模式下跳转被拦截时的统一提示
function singlePageTip() {
  wx.showToast({
    title: '朋友圈单页模式不支持跳转，请在小程序中打开',
    icon: 'none',
    duration: 2500
  });
}

module.exports = {
  TIMELINE_SCENE,
  enableShareMenu,
  isSinglePage,
  guideTimelineShare,
  singlePageTip
};
