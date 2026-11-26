import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const DashboardView = {
  setup() {
    const data = ref(null); const health = ref(null); const err = ref("");
    async function reload() {
      err.value = "";
      try {
        health.value = await api("/api/health");
        data.value = await api("/api/dashboard");
      } catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { data, health, err, reload };
  },
  template: `
  <div class="grid">
    <div class="panel span-12">
      <h2>发布控制台</h2>
      <p class="muted">{{ health && health.skeleton }}</p>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div class="panel span-4" v-if="data"><div class="muted">开关数</div><p class="stat">{{ data.flags }}</p></div>
    <div class="panel span-4" v-if="data"><div class="muted">已生效</div><p class="stat">{{ data.active }}</p></div>
    <div class="panel span-4" v-if="data"><div class="muted">开放影子</div><p class="stat">{{ data.open_shadows }}</p></div>
    <div class="panel span-4" v-if="data">
      <div class="muted">回放票</div>
      <p class="stat" :class="data.replay_ghost ? 'danger' : ''">{{ data.replay_tickets }}</p>
    </div>
    <div class="panel span-4" v-if="data">
      <div class="muted">假绿回放</div>
      <p class="stat" :class="data.replay_ghost ? 'danger' : ''">{{ data.replay_ghost }}</p>
      <p class="muted" v-if="data.replay_ghost">存在未加代回放，请查回放账本与对比矩阵。</p>
    </div>
    <div class="panel span-4" v-if="data">
      <div class="muted">生效覆盖</div><p class="stat">{{ data.active_overrides }}</p>
    </div>
    <div class="panel span-6" v-if="data">
      <h2>状态分布</h2>
      <table><thead><tr><th>状态</th><th>数量</th></tr></thead>
      <tbody><tr v-for="s in data.by_status" :key="s.status"><td>{{ s.label }}</td><td>{{ s.c }}</td></tr></tbody></table>
    </div>
    <div class="panel span-6" v-if="data">
      <h2>最近变更</h2>
      <table><thead><tr><th>动作</th><th>详情</th><th>操作者</th></tr></thead>
      <tbody><tr v-for="h in data.recent" :key="h.id"><td>{{ h.action }}</td><td>{{ h.detail }}</td><td>{{ h.actor }}</td></tr></tbody></table>
      <button class="btn secondary" style="margin-top:0.7rem" @click="reload">刷新</button>
    </div>
    <div class="panel span-12" v-if="data && data.replays.length">
      <h2>回放账本摘要</h2>
      <table>
        <thead><tr><th>票</th><th>开关</th><th>环境</th><th>旧代→新代</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="r in data.replays" :key="r.id">
            <td><code>{{ r.ticket }}</code></td>
            <td>{{ r.flag_key || r.flag_id }}</td><td>{{ r.env_code || r.env_id }}</td>
            <td>v{{ r.source_version }} → v{{ r.result_version }}</td>
            <td><span class="pill" :class="r.state === 'ok' ? '' : (r.state === 'ghost' ? 'danger' : 'warn')">{{ r.state }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>`
};
