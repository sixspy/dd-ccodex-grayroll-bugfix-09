import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const HistoryView = {
  setup() {
    const items = ref([]); const replays = ref([]); const summary = ref(null);
    const err = ref("");
    async function reload() {
      err.value = "";
      try {
        items.value = (await api("/api/history")).items || [];
        const rp = await api("/api/history/replays");
        replays.value = rp.items || []; summary.value = rp.summary;
      } catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { items, replays, summary, err, reload };
  },
  template: `
  <div class="grid">
    <div class="panel span-12">
      <h2>回放账本（跨表联查）</h2>
      <p class="muted" v-if="summary">
        票数 {{ summary.total }} · 相符 {{ summary.ok }} ·
        <span class="pill danger" v-if="summary.ghost">假绿 {{ summary.ghost }}</span>
        <span class="pill warn" v-if="summary.broken">断链 {{ summary.broken }}</span>
        <span class="pill" v-if="summary.superseded">已越过 {{ summary.superseded }}</span>
      </p>
      <p class="hint">source→result 必须严格加一，且正式规则/发布/审计/历史同票可联查；未加代即 ghost。</p>
      <table>
        <thead><tr><th>票</th><th>开关</th><th>环境</th><th>来源</th><th>旧代→新代</th><th>正式规则</th><th>发布</th><th>审计/历史</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="r in replays" :key="r.id">
            <td><code>{{ r.ticket }}</code></td>
            <td>{{ r.flag_key || r.flag_id }}</td><td>{{ r.env_code || r.env_id }}</td>
            <td>{{ r.source }}</td>
            <td>v{{ r.source_version }} → v{{ r.result_version }}</td>
            <td>{{ r.rule_version === null || r.rule_version === undefined ? '—' : 'v'+r.rule_version }}</td>
            <td>{{ r.release_version === null || r.release_version === undefined ? '—' : 'v'+r.release_version }}</td>
            <td>{{ r.audit_refs }}/{{ r.history_refs }}</td>
            <td>
              <span class="pill" :class="r.state === 'ok' ? '' : (r.state === 'ghost' ? 'danger' : 'warn')">
                {{ r.state }}{{ r.counter_bumped ? '' : ' · 未加一' }}
              </span>
            </td>
          </tr>
          <tr v-if="!replays.length"><td colspan="9" class="muted">暂无回放票。</td></tr>
        </tbody>
      </table>
    </div>
    <div class="panel span-12">
      <h2>变更历史</h2>
      <div class="err" v-if="err">{{ err }}</div>
      <table>
        <thead><tr><th>动作</th><th>开关</th><th>环境</th><th>详情</th><th>操作者</th></tr></thead>
        <tbody>
          <tr v-for="it in items" :key="it.id">
            <td>{{ it.action }}</td><td>{{ it.flag_key || '-' }}</td><td>{{ it.env_code || '-' }}</td>
            <td>{{ it.detail }}</td><td>{{ it.actor }}</td>
          </tr>
        </tbody>
      </table>
      <button class="btn secondary" style="margin-top:0.7rem" @click="reload">刷新</button>
    </div>
  </div>`
};
