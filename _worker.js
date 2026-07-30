// Cloudflare Worker — 静态资源服务
// 通过 ASSETS 绑定托管 dist/ 下的全部静态文件
//   /            → 跳转至 /web/
//   /web/        → dist/web/index.html
//   /web/*       → dist/web/*
//   /data/raw/*  → dist/data/raw/*  （飞行模型数据）
//   其他路径     → 由 ASSETS 自动匹配文件

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 根路径 → 302 重定向到 /web/，用户直接访问时落到应用入口
    if (url.pathname === '/' || url.pathname === '') {
      return new Response(null, {
        status: 302,
        headers: { Location: '/web/' },
      });
    }

    // 其余路径交给 ASSETS 处理（自动匹配 dist/ 下的文件）
    return env.ASSETS.fetch(request);
  },
};
