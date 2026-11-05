// pages/cars/cars.js — 车辆筛选列表页
const { DEFAULT_BRANDS, FUEL_TYPES, EMISSIONS, PAGE_SIZE } = require('../../utils/constants');
const { toWan, formatViolation, formatPeriod } = require('../../utils/format');
const { AD_UNITS } = require('../../utils/ad');

// 多选 chips 的 data 键 → 页面 chips 数组名
const CHIP_MAP = {
  brand: 'brandChips',
  court: 'courtChips',
  fuel_type: 'fuelChips',
  emission: 'emissionChips'
};

function defaultFilters() {
  return {
    brand: [], court: [], fuel_type: [], emission: [],
    has_license: null, has_registration: null, has_plate: null, has_key: null, is_mortgaged: null,
    final_price_min: '', final_price_max: '',
    violation_min: '', violation_max: '',
    mileage_max: '',
    parking_max: '', repair_max: '', deposit_max: '', extra_fee_max: ''
  };
}

function defaultSegments() {
  return [
    { key: 'has_license', label: '行驶证', value: null, yes: '有', no: '无' },
    { key: 'has_registration', label: '登记证', value: null, yes: '有', no: '无' },
    { key: 'has_plate', label: '车牌', value: null, yes: '有', no: '无' },
    { key: 'has_key', label: '钥匙', value: null, yes: '有', no: '无' },
    { key: 'is_mortgaged', label: '抵押', value: null, yes: '是', no: '否' }
  ];
}

Page({
  data: {
    currentZcid: null,
    filterOpen: false,
    filters: defaultFilters(),
    segments: defaultSegments(),
    mileageWan: '',
    brandChips: [],
    courtChips: [],
    fuelChips: [],
    emissionChips: [],
    sorts: [
      { key: 'start_price', label: '起拍价' },
      { key: 'final_price', label: '成交价' },
      { key: 'mileage_km', label: '里程' },
      { key: 'violation_count', label: '违章数' }
    ],
    sort: 'start_price',
    dir: 'asc',
    cars: [],
    total: 0,
    page: 0,
    loading: false,
    loadingMore: false,
    noMore: false,
    bannerUnit: AD_UNITS.bannerCars
  },

  onLoad() {
    this._reqSeq = 0;
    // 并行：期次 chips + 列表第 1 页
    this.fetchZcids();
    this.fetchList(1);
  },

  onPullDownRefresh() {
    this.fetchList(1).finally(() => wx.stopPullDownRefresh());
  },

  onReachBottom() {
    if (this.data.loading || this.data.loadingMore || this.data.noMore) return;
    this.fetchList(this.data.page + 1);
  },

  // 期次 chips（默认选中 latest，随后按 latest 重查第 1 页）
  // 只展示最新一期的车（历史期次仅用于推荐与分析）
  fetchZcids() {
    const app = getApp();
    return app.callFunction('cars', { method: 'zcids' })
      .then(res => {
        const latest = res.latest || null;
        this.setData({ currentZcid: latest });
        if (latest !== null) this.fetchList(1);
      })
      .catch(err => {
        wx.showToast({ title: err.message || '期次加载失败', icon: 'none' });
      });
  },

  // 拉取列表（page 1 覆盖，page>1 追加）；seq 防旧请求覆盖新结果
  fetchList(page) {
    const app = getApp();
    const seq = ++this._reqSeq;
    const isFirst = page === 1;
    this.setData(isFirst ? { loading: true } : { loadingMore: true });
    return app.callFunction('cars', {
      method: 'list',
      zcid: this.data.currentZcid,
      page,
      pageSize: PAGE_SIZE,
      filters: this.data.filters,
      sort: this.data.sort,
      dir: this.data.dir
    }).then(res => {
      if (seq !== this._reqSeq) return;
      const cars = (isFirst ? [] : this.data.cars).concat((res.cars || []).map(c => this.decorateCar(c)));
      this.setData({
        cars,
        total: res.total || 0,
        page: res.page || page,
        loading: false,
        loadingMore: false,
        noMore: cars.length >= (res.total || 0)
      });
      this.applyOptions(res.options || {});
    }).catch(err => {
      if (seq !== this._reqSeq) return;
      this.setData({ loading: false, loadingMore: false });
      wx.showToast({ title: err.message || '加载失败', icon: 'none' });
    });
  },

  // 预计算展示文案（WXML 不支持函数调用）
  decorateCar(c) {
    const docs = { 行驶证: c.has_license, 登记证: c.has_registration, 车牌: c.has_plate, 钥匙: c.has_key };
    let docsText = '';
    if (Object.values(docs).some(v => v === '有' || v === '无')) {
      const missing = Object.keys(docs).filter(k => docs[k] === '无');
      docsText = missing.length ? '缺' + missing.join('') : '证件齐';
    }
    return {
      ...c,
      startText: toWan(c.start_price),
      finalText: toWan(c.final_price),
      mileageText: c.mileage_km ? (c.mileage_km / 10000).toFixed(1) + '万km' : '—',
      violationText: formatViolation(c.violation_count, c.violation_points, c.violation_fine),
      periodText: formatPeriod(c.period),
      fuelEmissionText: [c.fuel_type, c.emission_standard].filter(Boolean).join('/'),
      docsText,
      extraFeeText: c.total_extra_fee ? toWan(c.total_extra_fee) : '',
      previewShort: c.preview_location
        ? (c.preview_location.length > 16 ? c.preview_location.slice(0, 16) + '…' : c.preview_location)
        : ''
    };
  },

  // 用后端 options 重建筛选 chips（保留当前选中）
  applyOptions(options) {
    const brands = options.brands && options.brands.length ? options.brands : DEFAULT_BRANDS;
    const courts = options.courts || [];
    const fuels = options.fuel_types && options.fuel_types.length ? options.fuel_types : FUEL_TYPES;
    const emissions = options.emissions && options.emissions.length ? options.emissions : EMISSIONS;
    this.setData({
      brandChips: this.buildChips(brands, this.data.filters.brand),
      courtChips: this.buildChips(courts, this.data.filters.court),
      fuelChips: this.buildChips(fuels, this.data.filters.fuel_type),
      emissionChips: this.buildChips(emissions, this.data.filters.emission)
    });
  },

  buildChips(names, selected) {
    return (names || []).map(n => ({ name: n, selected: (selected || []).indexOf(n) > -1 }));
  },

  // ---- 筛选面板 ----
  toggleFilter() {
    this.setData({ filterOpen: !this.data.filterOpen });
  },

  onChipTap(e) {
    const key = e.currentTarget.dataset.key;
    const name = e.currentTarget.dataset.name;
    const chipsKey = CHIP_MAP[key];
    const chips = this.data[chipsKey].map(c => (c.name === name ? { ...c, selected: !c.selected } : c));
    const selected = chips.filter(c => c.selected).map(c => c.name);
    this.setData({ [chipsKey]: chips, ['filters.' + key]: selected });
  },

  onSegmentTap(e) {
    const key = e.currentTarget.dataset.key;
    const val = e.currentTarget.dataset.val;
    const value = val === '' ? null : val;
    const segments = this.data.segments.map(s => (s.key === key ? { ...s, value } : s));
    this.setData({ segments, ['filters.' + key]: value });
  },

  onInput(e) {
    const key = e.currentTarget.dataset.key;
    this.setData({ ['filters.' + key]: e.detail.value });
  },

  // 里程上限以万公里输入，filters 存公里
  onMileageInput(e) {
    const wan = e.detail.value;
    const km = parseFloat(wan);
    this.setData({
      mileageWan: wan,
      'filters.mileage_max': wan === '' || isNaN(km) ? '' : String(km * 10000)
    });
  },

  onReset() {
    const filters = defaultFilters();
    this.setData({
      filters,
      mileageWan: '',
      segments: defaultSegments(),
      brandChips: this.buildChips(this.data.brandChips.map(c => c.name), []),
      courtChips: this.buildChips(this.data.courtChips.map(c => c.name), []),
      fuelChips: this.buildChips(this.data.fuelChips.map(c => c.name), []),
      emissionChips: this.buildChips(this.data.emissionChips.map(c => c.name), [])
    });
    this.fetchList(1);
  },

  onApply() {
    this.fetchList(1);
  },

  // ---- 排序 ----
  onSortTap(e) {
    const key = e.currentTarget.dataset.key;
    const { sort, dir } = this.data;
    if (sort === key) {
      this.setData({ dir: dir === 'asc' ? 'desc' : 'asc' });
    } else {
      this.setData({ sort: key, dir: 'asc' });
    }
    this.fetchList(1);
  },

  // ---- 列表 ----
  onCardTap(e) {
    const link = e.currentTarget.dataset.link;
    wx.navigateTo({ url: '/pages/car-detail/car-detail?car_link=' + encodeURIComponent(link) });
  },

  onBannerError() {
    this.setData({ bannerUnit: '' });
  }
});