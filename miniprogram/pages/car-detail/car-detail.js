// pages/car-detail/car-detail.js — 本期在售车辆详情页（仅 202611期 / 2464）
const { toWan, toWanWithComma, formatViolation, formatPeriod, formatRegTime } = require('../../utils/format');
const { AD_UNITS } = require('../../utils/ad');
const { CURRENT_PERIOD } = require('../../utils/constants');

Page({
  data: {
    car: null,
    isFavorite: false,
    display: null,
    bannerUnit: AD_UNITS.bannerDetail
  },

  onLoad(options) {
    const carLink = options.car_link ? decodeURIComponent(options.car_link) : '';
    if (!carLink) {
      this.setData({ car: null });
      return;
    }
    this.carLink = carLink;
    this.fetchDetail();
  },

  fetchDetail() {
    const app = getApp();
    app.callFunction('cars', { method: 'detail', car_link: this.carLink })
      .then(res => {
        const car = res.car;
        this.setData({
          car,
          isFavorite: !!res.is_favorite,
          display: this.buildDisplay(car, res.winner)
        });
      })
      .catch(err => {
        wx.showToast({
          title: err.message || '加载失败',
          icon: 'none',
          duration: 2000
        });
        // 非本期车辆：返回列表
        if (err && /非本期/.test(err.message)) {
          setTimeout(() => wx.navigateBack({
            fail: () => wx.switchTab({ url: '/pages/cars/cars' })
          }), 1500);
        }
      });
  },

  // 预计算展示文案（WXML 不支持函数调用）
  buildDisplay(car, winner) {
    const yesNo = v => (v === '有' || v === '无') ? v : '—';
    const hasVal = v => v !== null && v !== undefined && v !== '' && v !== '—' && v !== '-';
    const winnerPct = winner && winner.total_bidders
      ? (winner.winner_rank / winner.total_bidders * 100).toFixed(1) : '';
    const display = {
      startText: toWan(car.start_price),
      finalText: toWanWithComma(car.final_price),
      licenseText: yesNo(car.has_license),
      registrationText: yesNo(car.has_registration),
      plateText: yesNo(car.has_plate),
      keyText: yesNo(car.has_key),
      useTypeText: car.use_type || '—',
      fuelText: car.fuel_type || '—',
      emissionText: car.emission_standard || '—',
      modelText: car.vehicle_model || '—',
      firstRegText: car.first_reg_date || '—',
      inspectionText: car.inspection_expiry || '—',
      mileageText: car.mileage_km ? car.mileage_km + 'km' : '—',
      violationText: (car.violation_count == null && car.violation_points == null && car.violation_fine == null)
        ? '—' : formatViolation(car.violation_count, car.violation_points, car.violation_fine),
      parkingText: toWan(car.parking_fee),
      repairText: toWan(car.repair_fee),
      extraFeeText: toWan(car.total_extra_fee),
      depositText: toWan(car.deposit),
      courtText: car.court || '—',
      periodText: formatPeriod(car.period),
      itemNoText: car.item_no || '—',
      previewText: car.preview_location || '—'
    };
    display.winner = winner;
    display.winnerTimesText = winner ? (winner.winner_times || 0) + ' 次' : '';
    display.winnerRankText = winner
      ? winner.winner_rank + ' / ' + winner.total_bidders + (winnerPct ? '（前 ' + winnerPct + '%）' : '')
      : '';
    display.winnerRegText = winner ? formatRegTime(winner.winner_reg_time) || '—' : '';
    display.winnerZcidText = winner ? formatPeriod(String(winner.result_zcid)) + '期' : '';
    // 历史期次车无 LLM 详情：整块隐藏全空区块
    display.hasDocs = hasVal(display.licenseText) || hasVal(display.registrationText)
      || hasVal(display.plateText) || hasVal(display.keyText);
    display.hasBasic = hasVal(display.useTypeText) || hasVal(display.fuelText)
      || hasVal(display.emissionText) || hasVal(display.modelText)
      || hasVal(display.firstRegText) || hasVal(display.inspectionText)
      || hasVal(display.mileageText);
    display.hasViolation = hasVal(display.violationText);
    display.hasFees = hasVal(display.parkingText) || hasVal(display.repairText)
      || hasVal(display.extraFeeText) || hasVal(display.depositText);
    return display;
  },

  // 收藏：乐观更新，失败回滚
  onFavoriteTap() {
    const app = getApp();
    const next = !this.data.isFavorite;
    const method = next ? 'add' : 'remove';
    this.setData({ isFavorite: next });
    app.callFunction('favorites', { method, car_link: this.carLink })
      .then(() => {
        wx.showToast({ title: next ? '已收藏' : '已取消收藏', icon: 'none' });
      })
      .catch(err => {
        this.setData({ isFavorite: !next });
        wx.showToast({ title: err.message || '操作失败', icon: 'none' });
      });
  },

  onBannerError() {
    this.setData({ bannerUnit: '' });
  },

  // 车型分享：好友打开直达本车详情
  onShareAppMessage() {
    const car = this.data.car;
    if (!car) {
      return { title: '京慧车讯 · 在历史成交数据中找到适合你的车', path: '/pages/intro/intro' };
    }
    const name = car.car_name.length > 24 ? car.car_name.slice(0, 24) + '…' : car.car_name;
    const price = car.final_price ? (car.final_price / 10000).toFixed(1) + '万' : '';
    return {
      title: name + (price ? ' 成交价 ' + price : ''),
      path: '/pages/car-detail/car-detail?car_link=' + encodeURIComponent(this.carLink)
    };
  }
});