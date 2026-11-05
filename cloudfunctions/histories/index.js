// cloudfunctions/histories/index.js
// 查询历史：add / list / clear
const cloud = require('wx-server-sdk');
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();

exports.main = async (event, context) => {
  const { OPENID } = cloud.getWXContext();
  const method = event.method || 'list';

  try {
    switch (method) {
      case 'add': {
        const { times, reg_time, summary } = event;
        if (!times || !reg_time) return { error: { code: 400, msg: '缺少参数' } };
        // 每人最多保留 30 条，超出删最旧
        await db.collection('histories').add({
          data: { openid: OPENID, times, reg_time, summary: summary || '', created_at: Date.now() }
        });
        const countRes = await db.collection('histories').where({ openid: OPENID }).count();
        if (countRes.total > 30) {
          const overflow = await db.collection('histories')
            .where({ openid: OPENID })
            .orderBy('created_at', 'asc')
            .limit(countRes.total - 30)
            .get();
          for (const doc of overflow.data) {
            await db.collection('histories').doc(doc._id).remove();
          }
        }
        return { ok: true };
      }
      case 'list': {
        const res = await db.collection('histories')
          .where({ openid: OPENID })
          .orderBy('created_at', 'desc')
          .limit(30)
          .get();
        return { list: res.data };
      }
      case 'clear': {
        await db.collection('histories').where({ openid: OPENID }).remove();
        return { ok: true };
      }
      default:
        return { error: { code: 400, msg: `未知方法: ${method}` } };
    }
  } catch (e) {
    return { error: { code: 500, msg: e.message } };
  }
};
