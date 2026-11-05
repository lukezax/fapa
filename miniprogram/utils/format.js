// utils/format.js — 展示格式化工具
module.exports = {
  // 金额 → 万（保留2位）
  toWan(val) {
    const n = Number(val);
    if (isNaN(n) || n === 0) return '-';
    return (n / 10000).toFixed(2) + '万';
  },

  // 金额 → 万元（带千分位）
  toWanWithComma(val) {
    const n = Number(val);
    if (isNaN(n) || n === 0) return '-';
    const wan = (n / 10000).toFixed(2);
    return wan.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '万';
  },

  // 违章格式化："N起N分N元"
  formatViolation(count, points, fine) {
    const c = Number(count) || 0;
    const p = Number(points) || 0;
    const f = Number(fine) || 0;
    if (c === 0 && p === 0 && f === 0) return '无违章';
    const parts = [];
    if (c) parts.push(`${c}起`);
    if (p) parts.push(`${p}分`);
    if (f) parts.push(`${f}元`);
    return parts.join(' ');
  },

  // 日期归一化展示（去掉毫秒）
  formatRegTime(rt) {
    if (!rt) return '';
    // 兼容带空格格式 "2011-01-29 20: 04: 34. 627"
    const cleaned = rt.replace(/(\d):\s/g, '$1:').replace(/\.\s/g, '.');
    return cleaned.split('.')[0];
  },

  // 期次显示
  formatPeriod(period) {
    if (!period) return '';
    return period.replace('期', '');
  }
};
