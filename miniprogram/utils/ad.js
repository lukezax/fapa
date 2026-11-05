// utils/ad.js — 广告位配置与加载
//
// 上线前必做：
// 1. 在微信公众平台 → 流量主 → 广告位管理 创建广告位，获取真实 unit-id
// 2. 将下方测试 ID 替换为真实 ID
// 3. 开屏广告：微信无标准开屏组件，本方案用插屏广告（wx.createInterstitialAd）
//    在 rank 页首次进入时展示，作为开屏替代

// 微信官方测试广告位 ID（仅开发调试用，上线必须替换）
const AD_UNITS = {
  bannerCars: 'adunit-2f4b8c9d0e1a',      // cars 列表底部 Banner
  bannerDetail: 'adunit-3a5c7e9f0b2d',    // 车辆详情页 Banner
  bannerMine: 'adunit-4b6d8f0a1c3e',      // 我的页 Banner
  interstitial: 'adunit-5c7e9f1b3d5f'     // 插屏广告（开屏替代）
};

// 加载 Banner 广告
function createBannerAd(unitId) {
  if (!wx.createBannerAd) return null;
  const ad = wx.createBannerAd({
    adUnitId: unitId,
    style: { width: 320 }
  });
  ad.onError(err => {
    console.warn('Banner广告错误', err);
  });
  return ad;
}

// 加载插屏广告（开屏替代）
function createInterstitialAd(unitId) {
  if (!wx.createInterstitialAd) return null;
  const ad = wx.createInterstitialAd({ adUnitId: unitId });
  ad.onError(err => {
    console.warn('插屏广告错误', err);
  });
  return ad;
}

module.exports = {
  AD_UNITS,
  createBannerAd,
  createInterstitialAd
};
