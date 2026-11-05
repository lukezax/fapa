// app.js
App({
  globalData: {
    env: 'cloud1-d6g6tx36h29179055', // TODO: 替换为你的云开发环境 ID
    latestZcid: null,
    openid: null
  },

  onLaunch() {
    if (!wx.cloud) {
      console.error('请使用 2.2.3 或以上的基础库以使用云能力');
      return;
    }
    wx.cloud.init({
      env: this.globalData.env,
      traceUser: true
    });
  },

  // 统一云函数调用封装
  callFunction(name, data = {}) {
    return new Promise((resolve, reject) => {
      wx.cloud.callFunction({ name, data })
        .then(res => {
          const result = res.result;
          if (result && result.error) {
            reject(new Error(result.error.msg || '云函数错误'));
          } else {
            resolve(result);
          }
        })
        .catch(err => reject(err));
    });
  },

  // 获取 openid（惰性缓存）
  getOpenid() {
    if (this.globalData.openid) {
      return Promise.resolve(this.globalData.openid);
    }
    return this.callFunction('login').then(res => {
      this.globalData.openid = res.openid;
      return res.openid;
    });
  }
});
