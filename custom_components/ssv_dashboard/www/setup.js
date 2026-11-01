/* SSV Dashboard — installer page (admin only). Version __SSV_VERSION__
   Creates the dashboards, the start page and the run timers with Home Assistant's own
   WebSocket commands, so nothing has to be typed in YAML. */
const FILES = '/ssv_dashboard/';
const KIOSK_GUEST = { kiosk: false, hide_header: true, hide_sidebar: true, hide_menubutton: true, hide_overflow: true,
  block_overflow: true, hide_edit_dashboard: true, ignore_mobile_settings: true, ignore_disable_km: true };
const STYLE_PANEL = 'ha-card{border:none;border-radius:0;background:#070B10;overflow:hidden}';
const STYLE_FULL = 'ha-card{border:none;border-radius:0;background:#070B10;overflow:hidden;height:100vh;height:100dvh} #root{padding-top:0!important;height:100%}';
const TYPES = {
  wall:   { label: 'Wall panel 10″',  file: 'panel.html', icon: 'mdi:tablet-dashboard', aspect: '62.5%', style: STYLE_PANEL, admin: { kiosk: false } },
  tablet: { label: 'Tablet',          file: 'panel.html', icon: 'mdi:tablet',           aspect: '62.5%', style: STYLE_PANEL, admin: { kiosk: true } },
  room:   { label: 'Room panel 4″',   file: 'room.html',  icon: 'mdi:tablet-android',   aspect: '100%',  style: STYLE_PANEL, admin: { kiosk: false } },
  phone:  { label: 'Phone',           file: 'phone.html', icon: 'mdi:cellphone',        aspect: '100%',  style: STYLE_FULL,  admin: { kiosk: true } },
};
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const slug = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^\w\s-]/g, '').trim().replace(/[\s_-]+/g, '_').replace(/^_+|_+$/g, '');

function buildUrl(t, o) {
  const q = new URLSearchParams();
  if (t === 'room') { q.set('room', o.room); q.set('panel', o.panel || 'panel_' + o.room); }
  else if (t === 'phone') { if (o.panel) q.set('panel', o.panel); if (o.tablet) q.set('tablet', o.tablet); }
  else { q.set('panel', o.panel || 'living'); if (o.room) q.set('room', o.room); }
  if (o.villa) q.set('villa', o.villa);
  if (o.place) q.set('place', o.place);
  return FILES + TYPES[t].file + '?' + q.toString().replace(/\+/g, '%20');
}
function buildConfig(t, title, url) {
  const T = TYPES[t];
  return {
    title,
    kiosk_mode: { admin_settings: T.admin, non_admin_settings: KIOSK_GUEST },
    views: [{ title, path: 'main', icon: T.icon, type: 'panel',
      cards: [{ type: 'iframe', url, aspect_ratio: T.aspect, card_mod: { style: T.style } }] }],
  };
}
/* which SSV page a dashboard shows (also recognises the older /local/morea/ files) */
function ssvCard(cfg) {
  const c = cfg && cfg.views && cfg.views[0] && cfg.views[0].cards && cfg.views[0].cards[0];
  if (!c || c.type !== 'iframe' || typeof c.url !== 'string') return null;
  const m = c.url.match(/^(\/ssv_dashboard\/|\/local\/morea\/)(panel|room|phone)\.html(\?.*)?$/);
  if (!m) return null;
  return { legacy: m[1] !== FILES, file: m[2], query: new URLSearchParams(m[3] || ''), url: c.url };
}

class SSVSetup extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: 'open' }); this.st = { busy: false, log: [] }; this._loaded = false; this.shadowRoot.addEventListener('click', (e) => this.click(e)); }
  set hass(h) { this._hass = h; if (!this._loaded) { this._loaded = true; this.load(); } }
  get hass() { return this._hass; }
  set panel(p) { this._panel = p; }
  set narrow(n) { this._narrow = n; }
  ws(msg) { return this._hass.callWS(msg); }
  log(t, bad) { this.st.log.unshift({ t: new Date().toLocaleTimeString(), m: t, bad }); this.st.log = this.st.log.slice(0, 30); }

  async load() {
    const S = this.st;
    try {
      const [info, dashes, areas, ents, resources, sys] = await Promise.all([
        this.ws({ type: 'ssv_dashboard/info' }),
        this.ws({ type: 'lovelace/dashboards/list' }),
        this.ws({ type: 'config/area_registry/list' }),
        this.ws({ type: 'config/entity_registry/list_for_display' }).catch(() => ({ entities: [] })),
        this.ws({ type: 'lovelace/resources' }).catch(() => []),
        this.ws({ type: 'frontend/get_system_data', key: 'core' }).catch(() => null),
      ]);
      S.info = info; S.areas = areas.sort((a, b) => a.name.localeCompare(b.name));
      S.resources = resources; S.defaultPanel = sys && sys.value && sys.value.default_panel || null;
      S.ents = ents.entities || [];
      S.dashes = [];
      for (const d of dashes) {
        if (d.mode !== 'storage') continue;
        const cfg = await this.ws({ type: 'lovelace/config', url_path: d.url_path }).catch(() => null);
        const c = ssvCard(cfg);
        if (c) S.dashes.push({ d, cfg, c });
      }
    } catch (e) { this.log('Cannot read Home Assistant: ' + (e.message || e.code || e), true); }
    this.render();
  }

  /* ---------------------------------------------------------------- actions */
  async run(label, fn) {
    if (this.st.busy) return; this.st.busy = true; this.render();
    try { const r = await fn(); this.log(label + (r ? ' · ' + r : '')); }
    catch (e) { this.log(label + ' · ' + (e.message || e.code || JSON.stringify(e)), true); }
    this.st.busy = false; await this.load();
  }
  async createDash(t, title, path, opts) {
    const url = buildUrl(t, opts);
    const exists = (await this.ws({ type: 'lovelace/dashboards/list' })).some(d => d.url_path === path);
    if (!exists) await this.ws({ type: 'lovelace/dashboards/create', url_path: path, title, icon: TYPES[t].icon,
      show_in_sidebar: true, require_admin: false, mode: 'storage' });
    await this.ws({ type: 'lovelace/config/save', url_path: path, config: buildConfig(t, title, url) });
    return (exists ? 'updated ' : 'created ') + '/' + path;
  }
  async refreshDash(x) {
    const t = x.c.file === 'room' ? 'room' : x.c.file === 'phone' ? 'phone' : (x.d.url_path.includes('tablet') ? 'tablet' : 'wall');
    const q = x.c.query; q.delete('v');
    const url = FILES + TYPES[t].file + (q.toString() ? '?' + q.toString().replace(/\+/g, '%20') : '');
    const cfg = buildConfig(t, x.cfg.title || x.d.title, url);
    await this.ws({ type: 'lovelace/config/save', url_path: x.d.url_path, config: cfg });
    return '/' + x.d.url_path + ' → ' + url;
  }
  async setDefault(path) {
    const cur = await this.ws({ type: 'frontend/get_system_data', key: 'core' }).catch(() => null);
    const value = Object.assign({}, cur && cur.value, { default_panel: path });
    await this.ws({ type: 'frontend/set_system_data', key: 'core', value });
    return 'start page for everyone: /' + path;
  }
  async makeTimers() {
    const S = this.st; const made = [];
    const states = this._hass.states; const reg = {}; S.ents.forEach(e => reg[e.ei] = e);
    const labelsOf = (id) => (reg[id] && reg[id].lb) || [];
    const walls = Object.keys(states).filter(id => id.startsWith('climate.') && labelsOf(id).includes('heated_wall'));
    for (const id of walls) {
      const obj = id.split('.')[1];
      if (states['timer.inex_wall_' + obj] || states['timer.ssv_wall_' + obj]) continue;
      await this.ws({ type: 'timer/create', name: 'inex_wall_' + obj, duration: '03:00:00', restore: true });
      made.push('timer.inex_wall_' + obj);
    }
    for (const fn of ['hot_water', 'recirculation']) {
      const devs = Object.keys(states).filter(id => labelsOf(id).includes('water') && labelsOf(id).includes(fn));
      if (!devs.length) continue;
      if (devs.some(id => id.startsWith('timer.'))) continue;
      const tid = 'timer.inex_water_' + fn;
      if (!states[tid]) await this.ws({ type: 'timer/create', name: 'inex_water_' + fn, duration: '01:00:00', restore: true });
      await new Promise(r => setTimeout(r, 400));
      await this.ws({ type: 'config/entity_registry/update', entity_id: tid, labels: ['water', fn] }).catch(() => {});
      made.push(tid);
    }
    return made.length ? made.join(', ') : 'nothing missing';
  }

  /* ---------------------------------------------------------------- view */
  render() {
    const S = this.st, I = S.info || {};
    const lab = I.labels || {}; const missing = Object.keys(lab).filter(k => !lab[k]);
    const res = (S.resources || []).map(r => r.url || '');
    const hasKiosk = res.some(u => /kiosk-mode/i.test(u)), hasCardMod = res.some(u => /card-mod/i.test(u));
    const areaOpts = (sel) => '<option value="">—</option>' + (S.areas || []).map(a => `<option value="${esc(a.area_id)}"${a.area_id === sel ? ' selected' : ''}>${esc(a.name)}</option>`).join('');
    const ok = (b) => b ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>';
    const dashRows = (S.dashes || []).map((x, i) => {
      const def = S.defaultPanel === x.d.url_path;
      return `<tr><td><a href="/${esc(x.d.url_path)}/main" target="_top">${esc(x.d.title)}</a>${def ? ' <span class="tag">start page</span>' : ''}</td>
        <td>${esc(x.c.file)}.html</td><td class="mono">${esc(x.c.url)}</td>
        <td class="act"><button data-refresh="${i}"${x.c.legacy ? ' class="warn"' : ''}>${x.c.legacy ? 'Move to SSV files' : 'Rewrite'}</button>
        <button data-default="${esc(x.d.url_path)}"${def ? ' disabled' : ''}>Start page</button></td></tr>`;
    }).join('') || '<tr><td colspan="4" class="dim">No SSV dashboards yet — add one below.</td></tr>';
    const log = S.log.map(l => `<div class="${l.bad ? 'bad' : ''}">${esc(l.t)} · ${esc(l.m)}</div>`).join('');
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;min-height:100vh;background:var(--primary-background-color);color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif)}
      .wrap{max-width:1100px;margin:0 auto;padding:16px}
      h1{font-size:24px;font-weight:400;margin:8px 0 16px}
      .card{background:var(--card-background-color,#fff);border-radius:12px;padding:16px;margin-bottom:16px;box-shadow:var(--ha-card-box-shadow,none);border:1px solid var(--divider-color,#ddd)}
      h2{font-size:18px;font-weight:500;margin:0 0 12px}
      table{width:100%;border-collapse:collapse;table-layout:fixed}
      td,th{padding:8px 6px;border-bottom:1px solid var(--divider-color,#ddd);text-align:left;vertical-align:middle;overflow-wrap:anywhere}
      th{font-weight:500;color:var(--secondary-text-color,#666);font-size:13px}
      .mono{font-family:ui-monospace,monospace;font-size:12px}
      .act{text-align:right} .act button{margin:2px 0 2px 6px}
      button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--primary-color,#03a9f4);background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);cursor:pointer}
      button[disabled]{opacity:.45;cursor:default} button.sec{background:transparent;color:var(--primary-color,#03a9f4)} button.warn{background:var(--warning-color,#f39c12);border-color:var(--warning-color,#f39c12)}
      .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;align-items:end}
      label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--secondary-text-color,#666)}
      input,select{font:inherit;padding:8px;border-radius:8px;border:1px solid var(--divider-color,#ddd);background:var(--card-background-color,#fff);color:var(--primary-text-color)}
      .ok{color:var(--success-color,#2e7d32);font-weight:700}.bad{color:var(--error-color,#c62828)}.dim{color:var(--secondary-text-color,#666)}
      .tag{font-size:11px;padding:2px 6px;border-radius:6px;background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff)}
      .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
      .log{font-family:ui-monospace,monospace;font-size:12px;max-height:180px;overflow:auto}
      p{margin:4px 0 12px;color:var(--secondary-text-color,#666)}
    </style><div class="wrap">
      <h1>SSV Dashboard <span class="dim">v${esc(I.version || '?')}</span></h1>
      <div class="card"><h2>Status</h2><table>
        <tr><th>Item</th><th>State</th><th style="width:40%">What to do</th></tr>
        <tr><td>Labels</td><td>${ok(!missing.length)} ${missing.length ? missing.length + ' missing: ' + esc(missing.join(', ')) : Object.keys(lab).length + ' labels present'}</td><td class="act">${missing.length ? '<button data-act="labels">Create missing labels</button>' : ''}</td></tr>
        <tr><td>kiosk-mode (HACS)</td><td>${ok(hasKiosk)} ${hasKiosk ? 'installed' : 'not found in dashboard resources'}</td><td class="dim">${hasKiosk ? '' : 'HACS → Frontend → kiosk-mode → Download'}</td></tr>
        <tr><td>card-mod (HACS)</td><td>${ok(hasCardMod)} ${hasCardMod ? 'installed' : 'not found in dashboard resources'}</td><td class="dim">${hasCardMod ? '' : 'Optional: removes the frame around the panel'}</td></tr>
        <tr><td>Start page for everyone</td><td>${S.defaultPanel ? '/' + esc(S.defaultPanel) : '<span class="dim">Overview (HA default)</span>'}</td><td class="dim">Use “Start page” in the table below</td></tr>
      </table></div>

      <div class="card"><h2>Dashboards</h2>
        <table><tr><th style="width:22%">Dashboard</th><th style="width:12%">Page</th><th>Address</th><th style="width:30%"></th></tr>${dashRows}</table>
      </div>

      <div class="card"><h2>Add a dashboard</h2>
        <p>Creates the dashboard (or rewrites it if the address already exists) with one full-screen panel and kiosk settings for guests.</p>
        <div class="grid">
          <label>Type<select id="t">${Object.entries(TYPES).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select></label>
          <label>Title<input id="title" placeholder="Living & Kitchen"></label>
          <label>Address<input id="path" placeholder="ssv-living"></label>
          <label>Room<select id="room">${areaOpts('')}</select></label>
          <label>Panel id<input id="panel" placeholder="living"></label>
          <label>Villa name<input id="villa" placeholder="${esc(I.location_name || '')}"></label>
          <label>Place (sub-line)<input id="place" placeholder="Living & Kitchen"></label>
          <div><button data-act="add">Create dashboard</button></div>
        </div>
        <p style="margin-top:12px">Room panel 4″: choose the room. Wall panel and Tablet: Room is the room shown big on Home (optional). Phone switches to <span class="mono">/ssv-tablet/main</span> on large screens.</p>
        <div class="row"><button class="sec" data-act="std">Quick start: Living & Kitchen + Tablet + Phone</button></div>
      </div>

      <div class="card"><h2>Run timers</h2>
        <p>“Run 3h” on heated walls and “Run” on hot water / recirculation need a timer. This creates the missing ones for every climate labelled Heated Wall and for water functions labelled Water + Hot Water / Recirculation. SSV Dashboard turns the device off when the timer ends.</p>
        <button data-act="timers">Create missing timers</button>
      </div>

      <div class="card"><h2>Log</h2><div class="log">${log || '<span class="dim">—</span>'}</div></div>
    </div>`;
    const $ = (id) => this.shadowRoot.getElementById(id);
    this.shadowRoot.querySelectorAll('button').forEach(b => { if (S.busy) b.disabled = true; });
    const title = $('title'), path = $('path'), panel = $('panel'), t = $('t');
    const auto = () => { const s = slug(title.value); if (!path.dataset.touched) path.value = s ? 'ssv-' + s.replace(/_/g, '-') : ''; if (!panel.dataset.touched) panel.value = t.value === 'room' ? '' : s.split('_')[0]; };
    title.addEventListener('input', auto); t.addEventListener('change', auto);
    path.addEventListener('input', () => path.dataset.touched = 1); panel.addEventListener('input', () => panel.dataset.touched = 1);
  }

  click(e) {
    const b = e.target.closest('button'); if (!b || b.disabled) return;
    const $ = (id) => this.shadowRoot.getElementById(id); const S = this.st; const a = b.dataset;
    if (a.act === 'labels') return this.run('Labels', async () => { const r = await this.ws({ type: 'ssv_dashboard/create_labels' }); return r.created.length ? 'created ' + r.created.join(', ') : 'nothing to create'; });
    if (a.act === 'timers') return this.run('Timers', () => this.makeTimers());
    if (a.refresh != null) return this.run('Rewrite', () => this.refreshDash(S.dashes[+a.refresh]));
    if (a.default) return this.run('Start page', () => this.setDefault(a.default));
    if (a.act === 'add') {
      const t = $('t').value, title = $('title').value.trim(), path = $('path').value.trim().toLowerCase();
      const o = { room: $('room').value, panel: $('panel').value.trim(), villa: $('villa').value.trim(), place: $('place').value.trim() };
      if (!title) { this.log('Type a title', true); return this.render(); }
      if (!/^[a-z0-9]+-[a-z0-9-]+$/.test(path)) { this.log('Address must have a dash, e.g. ssv-living', true); return this.render(); }
      if (t === 'room' && !o.room) { this.log('Choose the room for a room panel', true); return this.render(); }
      return this.run('Dashboard ' + title, () => this.createDash(t, title, path, o));
    }
    if (a.act === 'std') return this.run('Quick start', async () => {
      const v = (S.info && S.info.location_name) || '';
      const r1 = await this.createDash('wall', 'Living & Kitchen', 'ssv-living', { panel: 'living', villa: v, place: 'Living & Kitchen' });
      const r2 = await this.createDash('tablet', 'Tablet', 'ssv-tablet', { panel: 'living', villa: v, place: 'Living & Kitchen' });
      const r3 = await this.createDash('phone', 'Phone', 'ssv-phone', { villa: v });
      return [r1, r2, r3].join(', ');
    });
  }
}
if (!customElements.get('ssv-setup')) customElements.define('ssv-setup', SSVSetup);
