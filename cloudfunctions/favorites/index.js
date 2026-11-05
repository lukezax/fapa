// cloudfunctions/favorites/index.js
// 收藏管理：add / remove / list
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();

exports.main = async (event, context) => {
  const { OPENID } = cloud.getWXContext();
  const method = event.method || 'list';

  try {
    switch (method) {
      case 'add': {
        const { car_link } = event;
        if (!car_link) return { error: { code: 400, msg: '缺少 car_link' } };
        // 幂等：已存在则忽略
        const existing = await db.collection('favorites')
          .where({ openid: OPENID, car_link })
          .count();
        if (existing.total === 0) {
          await db.collection('favorites').add({
            data: { openid: OPENID, car_link, created_at: Date.now() }
          });
        }
        return { ok: true };
      }
      case 'remove': {
        const { car_link } = event;
        if (!car_link) return { error: { code: 400, msg: '缺少 car_link' } };
        await db.collection('favorites')
          .where({ openid: OPENID, car_link })
          .remove();
        return { ok: true };
      }
      case 'list': {
        const res = await db.collection('favorites')
          .where({ openid: OPENID })
          .orderBy('created_at', 'desc')
          .limit(200)
          .get();
        return { list: res.data.map(d => d.car_link) };
      }
      case 'status': {
        const { car_link } = event;
        const res = await db.collection('favorites')
          .where({ openid: OPENID, car_link })
          .count();
        return { is_favorite: res.total > 0 };
      }
      default:
        return { error: { code: 400, msg: `未知方法: ${method}` } };
    }
  } catch (e) {
    return { error: { code: 500, msg: e.message } };
  }
};
