<template>
  <main class="about">
    <section class="about-card">
      <h1>雾都疑云 · CoC 跑团助手</h1>
      <p class="tagline">局域网联机的《克苏鲁的呼唤》第七版跑团 Web 应用</p>
      <p class="desc">
        1 名守秘人（KP）+ 2~4 名玩家，浏览器即开即玩：七版规则建卡与检定、
        房间实时联机（WebSocket + 断线重连 + 存档续玩）、双聊天框（剧情 / 闲聊分离）、
        检定下放（KP 定技能难度，玩家本人掷骰），以及双模式 AI 主持
        （协同建议 / 全自动主持，LLM 可随时降级纯人工）。
      </p>
      <ul class="stack">
        <li>前端：Vue 3 + Vite + TypeScript + Pinia + Element Plus</li>
        <li>后端：FastAPI + SQLModel（SQLite），LLM 走 OpenAI 兼容协议</li>
        <li>部署：前后端分离开发，Vite 代理联调；构建产物可由 FastAPI 单端口托管</li>
      </ul>
      <p class="note">
        项目文档见仓库 <code>README.md</code> 与 <code>goal.md</code>（总控）；
        规则笔记见 <code>docs/coc7-rules.md</code>。
      </p>
    </section>
  </main>
</template>

<style scoped>
.about {
  min-height: calc(100vh - 55px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: #f5f7fa;
}

.about-card {
  max-width: 640px;
  padding: 32px 36px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
}

h1 {
  margin: 0 0 6px;
  font-size: 24px;
  color: #303133;
}

.tagline {
  margin: 0 0 16px;
  font-size: 14px;
  color: #909399;
}

.desc {
  margin: 0 0 16px;
  font-size: 14px;
  line-height: 1.8;
  color: #606266;
}

.stack {
  margin: 0 0 16px;
  padding-left: 20px;
  font-size: 13px;
  line-height: 2;
  color: #606266;
}

.note {
  margin: 0;
  font-size: 12px;
  color: #909399;
}

.note code {
  padding: 1px 5px;
  background: #f0f2f5;
  border-radius: 4px;
}
</style>
