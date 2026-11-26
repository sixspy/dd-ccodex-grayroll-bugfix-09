import { api } from "../api.js";
const { ref, onMounted } = Vue;
export const CompareView = {
  setup() {
    const flagId = ref(1); const envId = ref(3);
    const detail = ref(null); const matrix = ref(null); const err = ref("");
    async function reload() {
      err.value = "";
      try {
        detail.value = await api(`/api/compare/flag/${flagId.value}/env/${envId.value}`);
        matrix.value = await api("/api/compare/matrix");
      } catch (e) { err.value = e.message || String(e); }
    }
    onMounted(reload);
    return { flagId, envId, detail, matrix, err, reload };
  },
  template: `
  <div class="grid">
    <div class="panel span-5">
      <h2>正式 vs 影子</h2>
      <p class="hint">回放加代须同票同事务：未加代的回放一律判假绿。</p>
      <div class="field"><label>开关ID</label><input type="number" v-model.number="flagId" /></div>
      <div class="field"><label>环境ID</label><input type="number" v-model.number="envId" /></div>
      <button class="btn secondary" @click="reload">对比</button>
      <div class="err" v-if="err">{{ err }}</div>
      <div v-if="detail" style="margin-top:0.8rem">
        <p>
          <span class="pill" :class="detail.aligned ? '' : 'danger'">{{ detail.aligned ? '账实相符' : '账实不符' }}</span>
          <span class="pill warn" v-if="detail.ghost_green">假绿回放</span>
          <span class="pill" :class="detail.version_bumped ? '' : 'danger'">
            {{ detail.version_bumped ? '计数器已加一' : '计数器未加一' }}
          </span>
        </p>
        <table>
          <tbody>
            <tr><th>当前代</th><td>{{ detail.generation }}</td></tr>
            <tr v-if="detail.last_replay && detail.last_replay.exists">
              <th>末次回放</th>
              <td>
                {{ detail.last_replay.ticket }}<br/>
                v{{ detail.last_replay.source_version }} → v{{ detail.last_replay.result_version }}
                <span class="pill danger" v-if="detail.last_replay.ghost">ghost</span>
                <span class="pill" v-else>{{ detail.last_replay.state }}</span>
              </td>
            </tr>
            <tr><th>正式版本</th><td v-if="detail.official_rule">v{{ detail.official_rule.version }}（{{ detail.official_rule.percent }}%）</td><td v-else class="muted">无</td></tr>
          </tbody>
        </table>
        <pre v-if="detail.diffs && detail.diffs.length" style="margin-top:0.6rem">{{ detail.diffs }}</pre>
        <p class="muted" v-else>正式与影子无字段差异。</p>
      </div>
    </div>
    <div class="panel span-7">
      <h2>环境矩阵</h2>
      <p class="muted" v-if="matrix">
        假绿格：<b>{{ matrix.ghost_cells }}</b> ·
        <span class="pill" :class="matrix.all_aligned ? '' : 'danger'">{{ matrix.all_aligned ? '全绿' : '有假绿' }}</span>
      </p>
      <div v-if="matrix">
        <table>
          <thead>
            <tr>
              <th>开关</th>
              <th v-for="e in matrix.envs" :key="e.id">{{ e.code }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in matrix.matrix" :key="row.flag_id">
              <td>{{ row.flag_key }}</td>
              <td v-for="c in row.cells" :key="c.env_id">
                <span v-if="c.has_rule">
                  {{ c.percent }}% v{{ c.version }}
                  <span class="pill" v-if="c.generation !== null && c.generation !== undefined">代{{ c.generation }}</span>
                  <span class="pill danger" v-if="c.ghost">假绿</span>
                  <span class="pill warn" v-else-if="!c.aligned">未对齐</span>
                </span>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>`
};
