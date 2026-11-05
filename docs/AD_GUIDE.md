# 广告接入指引（开屏 + Banner）

> 目标：给小程序接入**开屏广告**和 **Banner 广告**。
> 注册、认证、流量主开通等资质/申请工作不涉及，只讲从"有账号"到"广告展示出来"怎么做。
> 项目现状：`miniprogram/utils/ad.js` 已有广告位配置和两个加载函数（占位 ID 需替换）。

---

## 0. 三种广告与选择

| 广告 | 微信官方名称 | 需要写代码？ | 本项目角色 |
|---|---|---|---|
| 开屏广告 | **封面广告**（Cover Ad） | **否**，后台开关即上线 | 用户打开小程序时的全屏广告，**正解** |
| Banner 广告 | Banner 广告 | 是（组件或 API） | 列表页/详情页/我的页底部 |
| 插屏广告 | 插屏广告 | 是 | 备选：代码控制弹出时机（有频控，不推荐当开屏用） |

> ⚠️ 更正旧注释：`utils/ad.js` 里写"微信无标准开屏组件"已过时。
> 微信官方已有「封面广告」（即开屏广告），免开发、在流量主后台开个开关就上线。
> 插屏广告有展示频率限制（微信自动控频），**不适合**作为开屏替代，本项目应按封面广告接入。

---

## 1. 前置：开通流量主（一次性）

广告展示依赖"流量主"资格，在 [mp.weixin.qq.com](https://mp.weixin.qq.com) 完成：

1. 登录小程序后台 → 左侧「**推广 → 流量主**」
2. 满足条件后按页面提示开通：
   - 小程序**累计独立访客（UV）≥ 1000**
   - 无严重违规记录
3. 开通后需**签约**（流量主协议）并**绑定结算账户**（对公/个人结算，月结）

> 如果流量主页面提示资格不足：先让小程序有真实访客量（开发版/体验版不计 UV，需正式发布或测试版实际打开）。
> 个人主体小程序通常可开通流量主，若你后台没有入口，以页面实际提示为准。

---

## 2. 创建广告位，拿到 adunit ID

流量主页面 →「**广告管理 → 新建广告位**」，按需创建：

| 广告位类型 | 数量 | 建议名称 | 用途 |
|---|---|---|---|
| Banner | 2-3 个 | cars 列表 Banner / 详情页 Banner / 我的页 Banner | 各页面一个独立广告位 |
| 插屏 | 1 个 | 插屏（备用） | 代码控制弹出 |

创建后每个广告位有一个 **adunit ID**（形如 `adunit-xxxxxxxxxxxxxxxx`），复制备用。

> 封面广告**无需创建广告位**：流量主 →「广告管理 → **封面广告**」→ 打开开关即可（见第 3 步）。

---

## 3. 开屏广告（封面广告）— 免开发

### 3.1 打开开关

流量主后台 →「广告管理 → 封面广告」→ 打开「封面广告开关」。

打开后**无需任何代码**：用户打开小程序时，系统自动全屏展示广告，右上角可跳过。
展示逻辑（频控、跳过、素材）由微信广告统一控制。

### 3.2 可选：播控（控制哪些入口不展示）

微信支持精细化播控（安卓 8.0.37+ / iOS 8.0.40+ / 基础库 2.32.3+），按需配置：

- **页面路径参数**：分享时给 path 加 `isShowSplashAd=false`，从该路径进入不展示开屏：

```js
// 例如某些场景不希望用户看到开屏广告
onShareAppMessage() {
  return {
    title: '分享',
    path: '/pages/rank/rank?isShowSplashAd=false'
  };
}
```

- **小程序码**：生成小程序码时传 `show_splash_ad: false`，扫码进入不展示开屏。
- 默认全部场景展示；后台「场景设置」可整体关闭某些场景。

### 3.3 验证

开屏广告**必须在真机上验证**（开发者工具模拟器不展示封面广告）：
开发版预览扫码打开小程序 → 进入时如出现全屏广告即生效。

> 封面上线后，广告素材审核通过才会展示（审核中/无匹配广告时自动跳过，不影响使用）。

---

## 4. Banner 广告 — 代码接入

Banner 有**两种写法**，推荐组件方式（简单、自动适配布局）；API 方式适合需要代码控制位置/显示隐藏的场景（本项目 `utils/ad.js` 已有雏形）。

### 4.1 方式一：`<ad>` 组件（推荐，用于列表/详情页固定位置）

**步骤 1**：页面 `.json` 不需要配置，直接在 `.wxml` 需要的位置放组件（如 cars 列表底部）：

```xml
<!-- pages/cars/cars.wxml，列表底部 -->
<view class="banner-wrap">
  <ad unit-id="{{bannerAdUnit}}" ad-intervals="30" binderror="onBannerError"></ad>
</view>
```

**步骤 2**：页面 `.js` 里注入广告位 ID 并处理错误（错误时隐藏容器，避免留白）：

```js
// pages/cars/cars.js
const { AD_UNITS } = require('../../utils/ad');

Page({
  data: {
    bannerAdUnit: AD_UNITS.bannerCars
  },
  onBannerError(e) {
    console.warn('Banner加载失败', e.detail);
    this.setData({ bannerAdUnit: '' }); // 隐藏广告容器
  }
});
```

> 广告组件加载失败时**不占高度**（官方特性），页面不会留白。

**步骤 3**：wxss 调整样式（宽度自适应、距底部留安全距离）：

```css
.banner-wrap {
  margin: 20rpx 0 0;
  overflow: hidden;
}
.banner-wrap ad {
  width: 100%;
}
```

### 4.2 方式二：`wx.createBannerAd` API（程序化控制）

完善 `miniprogram/utils/ad.js`（现有版本缺 show/hide/onLoad/销毁）：

```js
// utils/ad.js — 完整版 Banner 加载
function createBannerAd(unitId, style = { width: 320 }) {
  if (!wx.createBannerAd) return null;
  const ad = wx.createBannerAd({
    adUnitId: unitId,
    adIntervals: 30,          // 自动刷新，>=30 秒
    style
  });
  ad.onError(err => {
    console.warn('Banner广告错误', err);
    ad.hide();                // 出错隐藏，避免占位
  });
  ad.onLoad(() => {
    ad.show();                // 加载成功再显示
  });
  return ad;
}
```

页面使用示例（如 mine 页 onShow 显示、onHide 隐藏）：

```js
// pages/mine/mine.js
const { AD_UNITS, createBannerAd } = require('../../utils/ad');

Page({
  onLoad() {
    this.bannerAd = createBannerAd(AD_UNITS.bannerMine, { top: 0, width: 320 });
  },
  onShow() {
    if (this.bannerAd) this.bannerAd.show();
  },
  onHide() {
    if (this.bannerAd) this.bannerAd.hide();
  },
  onUnload() {
    if (this.bannerAd) { this.bannerAd.destroy(); this.bannerAd = null; }
  }
});
```

### 4.3 Banner 放置位置（本项目）

| 广告位 | 页面 | 建议写法 |
|---|---|---|
| bannerCars | `pages/cars/cars` 列表底部 | `<ad>` 组件 |
| bannerDetail | `pages/car-detail/car-detail` 底部 | `<ad>` 组件 |
| bannerMine | `pages/mine/mine` 底部 | API（`createBannerAd`） |

> 合规红线：Banner 不得遮挡内容/功能按钮、不得诱导点击（微信对误触有处罚）。参考「流量主应用规范」。

---

## 5. 插屏广告（备选，不要当开屏）

若仍想保留代码控制的"开屏替代"（例如封面广告未开通前），用插屏：

```js
// utils/ad.js 已有 createInterstitialAd
const { AD_UNITS, createInterstitialAd } = require('../../utils/ad');

Page({
  onReady() {
    this.interstitialAd = createInterstitialAd(AD_UNITS.interstitial);
  },
  // 在合适时机（如从详情返回列表时）弹出，不要一进小程序就弹
  showInterstitial() {
    if (!this.interstitialAd) return;
    this.interstitialAd.show().catch(err => {
      console.warn('插屏展示失败（频控/无广告）', err);
    });
  }
});
```

注意：
- 微信对插屏有**频率控制**（自动限频），一天能展示的次数有限，属正常
- 打开小程序立即弹插屏体验差且**有违规风险**，建议在页面切换/操作完成后展示
- 项目原计划"rank 页首次进入弹插屏当开屏"——有封面广告后此方案降级为可选

---

## 6. 替换真实广告位 ID（必做）

编辑 `miniprogram/utils/ad.js`，把占位符换成第 2 步创建的真实 ID：

```js
const AD_UNITS = {
  bannerCars: 'adunit-xxxxxxxxxxxxxxxx',   // ← 替换成真实 ID
  bannerDetail: 'adunit-xxxxxxxxxxxxxxxx',
  bannerMine: 'adunit-xxxxxxxxxxxxxxxx',
  interstitial: 'adunit-xxxxxxxxxxxxxxxx'  // 不用可留空/删除
};
```

> 占位 ID 不替换 → 真机报错码 **1002（广告单元无效）**，广告不展示。

---

## 7. 测试与验证

1. **真机预览**（封面/Banner/插屏均需真机，模拟器只出测试物料或报错）
2. 逐项检查：
   - 打开小程序 → 出现封面广告（开屏）
   - cars 列表滚到底 → 出现 Banner
   - 详情页、我的页 → 对应 Banner
   - 后台「广告管理 → 广告位状态」能看到广告位正常（非审核中/驳回）
3. 广告素材需要**审核**：新广告位首次展示前有审核期（错误码 1005 = 审核中，正常等待）
4. 无匹配广告（错误码 1004）属正常：该用户不在广告投放人群定向内，组件自动不占位

---

## 8. 常见问题

| 错误码 | 含义 | 处理 |
|---|---|---|
| 1000 | 后端错误 | 忽略，稍后自动恢复 |
| 1001 | 参数错误 | 检查 unit-id 传参 |
| **1002** | 广告单元无效 | ID 拼错/用了占位符/用了别的小程序 ID → 回流量主后台核对 |
| 1003 | 内部错误 | 忽略，稍后重试 |
| 1004 | 无适合的广告 | 正常，该用户不在定向内，不占位 |
| 1005 | 广告组件审核中 | 新广告位正常现象，等待审核通过 |
| 1006 | 广告被驳回 | 去流量主后台看驳回原因 |
| 1007 | 广告被封禁 | 检查违规（遮挡/诱导点击等） |
| 1008 | 广告单元已关闭 | 后台重新打开广告位开关 |

其他：
- **封面上线多久能见？** 打开开关后，素材审核通过即开始展示，一般 1-3 天
- **开发版能看到广告吗？** 真机开发版/体验版均可看到广告，模拟器不可靠
- **收入在哪看？** 流量主后台「数据统计」，按月结算至绑定账户
- **收益低/没广告？** 广告按展示和点击计费，与用户量、定向有关；优先保证封面广告开关已打开

---

## 9. 上线检查清单

- [ ] 流量主已开通、已签约、已绑结算账户
- [ ] 封面广告开关已打开（开屏）
- [ ] Banner 广告位已创建，`utils/ad.js` 已替换为真实 ID
- [ ] cars / car-detail / mine 三处 Banner 已按第 4 节接入
- [ ] 真机逐页验证广告展示正常，无遮挡、无误触
- [ ] 广告位审核状态正常（非驳回/封禁）
- [ ] 不需要的开屏入口已按第 3.2 节配置播控
