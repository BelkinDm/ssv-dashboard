/* SSV Dashboard — installer page (admin only). Version __SSV_VERSION__
   1.1: panels are objects (name, screen type, purpose, rooms, tabs, night) kept by the integration;
   each gets its own label "Panel · <name>" and its own dashboard. The page also checks the
   integrations every tab needs and can install the missing ones through HACS. */
const FILES = '/ssv_dashboard/';
const KIOSK_GUEST = { kiosk: false, hide_header: true, hide_sidebar: true, hide_menubutton: true, hide_overflow: true,
  block_overflow: true, hide_edit_dashboard: true, ignore_mobile_settings: true, ignore_disable_km: true };
const STYLE_PANEL = 'ha-card{border:none;border-radius:0;background:#070B10;overflow:hidden}';
const STYLE_FULL = 'ha-card{border:none;border-radius:0;background:#070B10;overflow:hidden;height:100vh;height:100dvh} #root{padding-top:0!important;height:100%}';
const TYPES = {
  wall:   { label: 'Wall panel 10″', file: 'panel.html', icon: 'mdi:tablet-dashboard', aspect: '62.5%', style: STYLE_PANEL, admin: { kiosk: false } },
  tablet: { label: 'Tablet',         file: 'panel.html', icon: 'mdi:tablet',           aspect: '62.5%', style: STYLE_PANEL, admin: { kiosk: true } },
  room:   { label: 'Room panel 4″',  file: 'room.html',  icon: 'mdi:tablet-android',   aspect: '100%',  style: STYLE_PANEL, admin: { kiosk: false } },
  phone:  { label: 'Phone',          file: 'phone.html', icon: 'mdi:cellphone',        aspect: '100%',  style: STYLE_FULL,  admin: { kiosk: true } },
};
const TABS = [['rooms', 'Rooms'], ['lights', 'Lights'], ['climate', 'Climate'], ['heating', 'Heating'], ['curtains', 'Curtains'],
  ['water', 'Water'], ['cameras', 'Cameras'], ['intercom', 'Intercom'], ['security', 'Security'], ['schedule', 'Schedule']];
/* purpose = which tabs are on by default and whether the screen goes to night mode */
const PURPOSES = {
  residential: { label: 'Residential (villa, apartment)', off: [], night: true },
  hotel_room:  { label: 'Hotel / guest room',             off: ['cameras', 'security', 'schedule'], night: true },
  office:      { label: 'Office',                         off: ['water'], night: false },
  gym:         { label: 'Gym / spa',                      off: ['water', 'cameras', 'intercom', 'security'], night: false },
  common:      { label: 'Lobby / common area',            off: ['water', 'heating'], night: false },
  custom:      { label: 'Custom',                         off: [], night: true },
};
const HACS_FRONTEND = [
  { key: 'kiosk', name: 'kiosk-mode', repo: 'NemesisRE/kiosk-mode', re: /kiosk-mode/i, for: 'Hides the HA header and sidebar on panels', need: 'required' },
  { key: 'cardmod', name: 'card-mod', repo: 'thomasloven/lovelace-card-mod', re: /card-mod/i, for: 'Removes the frame around the panel', need: 'recommended' },
];
const NEED = { required: 'Required', tab: 'For a tab', recommended: 'Recommended' };
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const slug = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^\w\s-]/g, '').trim().replace(/[\s_-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
const dashPath = (id) => 'ssv-' + id.replace(/_/g, '-');

function panelUrl(p) {
  const q = new URLSearchParams({ panel: p.id });
  return FILES + TYPES[p.type].file + '?' + q.toString();
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
function newPanel() { return { id: '', name: '', type: 'wall', purpose: 'residential', areas: [], room: '', tabs: {}, night: { enabled: true, from: 22, to: 7 }, villa: '', place: '' }; }

class SSVSetup extends HTMLElement {
  constructor() {
    super(); this.attachShadow({ mode: 'open' });
    this.st = { busy: false, log: [], ed: null, restart: false };
    this._loaded = false;
    this.shadowRoot.addEventListener('click', (e) => this.click(e));
    this.shadowRoot.addEventListener('change', (e) => this.change(e));
    this.shadowRoot.addEventListener('input', (e) => this.input(e));
  }
  set hass(h) { this._hass = h; if (!this._loaded) { this._loaded = true; this.load(); } }
  get hass() { return this._hass; }
  set panel(p) { this._panel = p; }
  set narrow(n) { this._narrow = n; }
  ws(msg) { return this._hass.callWS(msg); }
  log(t, bad) { this.st.log.unshift({ t: new Date().toLocaleTimeString(), m: t, bad }); this.st.log = this.st.log.slice(0, 30); }

  async load() {
    const S = this.st;
    try {
      const [info, dashes, areas, ents, resources, sys, panels, hacs] = await Promise.all([
        this.ws({ type: 'ssv_dashboard/info' }),
        this.ws({ type: 'lovelace/dashboards/list' }),
        this.ws({ type: 'config/area_registry/list' }),
        this.ws({ type: 'config/entity_registry/list_for_display' }).catch(() => ({ entities: [] })),
        this.ws({ type: 'lovelace/resources' }).catch(() => []),
        this.ws({ type: 'frontend/get_system_data', key: 'core' }).catch(() => null),
        this.ws({ type: 'ssv_dashboard/panels/list' }),
        this.ws({ type: 'hacs/repositories/list' }).catch(() => null),
      ]);
      S.info = info; S.areas = areas.sort((a, b) => a.name.localeCompare(b.name));
      S.resources = resources; S.defaultPanel = (sys && sys.value && sys.value.default_panel) || null;
      S.ents = ents.entities || []; S.panels = panels.panels || []; S.runs = panels.runs || { wall: 180, per: {} };
      S.hacs = hacs; S.dashList = dashes;
      S.legacy = [];
      for (const d of dashes) {
        if (d.mode !== 'storage') continue;
        const cfg = await this.ws({ type: 'lovelace/config', url_path: d.url_path }).catch(() => null);
        const c = ssvCard(cfg);
        if (c && (c.legacy || !S.panels.some(p => dashPath(p.id) === d.url_path))) S.legacy.push({ d, cfg, c });
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
  async writeDash(p) {
    const path = dashPath(p.id), title = p.name;
    const exists = (await this.ws({ type: 'lovelace/dashboards/list' })).some(d => d.url_path === path);
    if (!exists) await this.ws({ type: 'lovelace/dashboards/create', url_path: path, title, icon: TYPES[p.type].icon,
      show_in_sidebar: true, require_admin: false, mode: 'storage' });
    await this.ws({ type: 'lovelace/config/save', url_path: path, config: buildConfig(p.type, title, panelUrl(p)) });
    return path;
  }
  async savePanel() {
    const p = this.st.ed;
    if (!p.name.trim()) throw new Error('Type a name');
    p.id = p.id || slug(p.name);
    if (!/^[a-z0-9][a-z0-9_]{0,40}$/.test(p.id)) throw new Error('Id: latin letters, digits and _ only');
    if (p.type === 'room' && !p.areas.length) throw new Error('A room panel needs its room');
    const body = { id: p.id, name: p.name.trim(), type: p.type, purpose: p.purpose, areas: p.areas, room: p.room || p.areas[0] || null,
      tabs: p.tabs, night: { enabled: !!p.night.enabled, from: +p.night.from, to: +p.night.to },
      villa: p.villa || null, place: p.place || null, dashboard: dashPath(p.id) };
    const r = await this.ws({ type: 'ssv_dashboard/panels/save', panel: body });
    const path = await this.writeDash(body);
    this.st.ed = null;
    return `${body.name} saved · dashboard /${path} · label ${r.label}`;
  }
  async moveLegacy(x) {
    /* old dashboard → same page from the integration's files, same parameters */
    const t = x.c.file === 'room' ? 'room' : x.c.file === 'phone' ? 'phone' : (x.d.url_path.includes('tablet') ? 'tablet' : 'wall');
    const q = x.c.query; q.delete('v');
    const url = FILES + TYPES[t].file + (q.toString() ? '?' + q.toString().replace(/\+/g, '%20') : '');
    await this.ws({ type: 'lovelace/config/save', url_path: x.d.url_path, config: buildConfig(t, x.cfg.title || x.d.title, url) });
    return '/' + x.d.url_path + ' → ' + url;
  }
  async setDefault(path) {
    const cur = await this.ws({ type: 'frontend/get_system_data', key: 'core' }).catch(() => null);
    await this.ws({ type: 'frontend/set_system_data', key: 'core', value: Object.assign({}, cur && cur.value, { default_panel: path }) });
    return 'start page for everyone: /' + path;
  }
  hacsRepo(full) { return (this.st.hacs || []).find(r => String(r.full_name).toLowerCase() === full.toLowerCase()); }
  async hacsInstall(full) {
    const r = this.hacsRepo(full);
    if (!r) throw new Error(full + ' not found in HACS — add it in HACS → Custom repositories');
    await this.ws({ type: 'hacs/repository/download', repository: String(r.id) });
    if (r.category === 'integration') this.st.restart = true;
    return full + ' downloaded' + (r.category === 'integration' ? ' · restart Home Assistant, then press Add' : '');
  }

  /* ---------------------------------------------------------------- events */
  input(e) {
    const ed = this.st.ed; if (!ed) return; const f = e.target.dataset.f; if (!f) return;
    if (f === 'name') { ed.name = e.target.value; if (!ed._idTouched && !ed._existing) { ed.id = slug(ed.name); const el = this.shadowRoot.getElementById('pid'); if (el) el.value = ed.id; } }
    else if (f === 'id') { ed.id = e.target.value.trim().toLowerCase(); ed._idTouched = true; }
    else if (f === 'villa' || f === 'place') ed[f] = e.target.value;
    else if (f === 'from' || f === 'to') ed.night[f] = +e.target.value;
    else if (f === 'run') { const v = +e.target.value; if (e.target.dataset.eid) { if (v) this.st.runs.per[e.target.dataset.eid] = v; else delete this.st.runs.per[e.target.dataset.eid]; } else this.st.runs.wall = v || 180; }
  }
  change(e) {
    const ed = this.st.ed; const t = e.target; const f = t.dataset.f; if (!f || !ed) return;
    if (f === 'type') { ed.type = t.value; }
    else if (f === 'purpose') { ed.purpose = t.value; const P = PURPOSES[t.value]; ed.tabs = {}; P.off.forEach(k => ed.tabs[k] = false); ed.night.enabled = P.night; }
    else if (f === 'area') { const a = t.value; ed.areas = t.checked ? [...new Set([...ed.areas, a])] : ed.areas.filter(x => x !== a); if (!ed.areas.includes(ed.room)) ed.room = ed.areas[0] || ''; }
    else if (f === 'room') ed.room = t.value;
    else if (f === 'tab') { if (t.checked) delete ed.tabs[t.value]; else ed.tabs[t.value] = false; }
    else if (f === 'night') ed.night.enabled = t.checked;
    else return;
    this.render();
  }
  click(e) {
    const b = e.target.closest('button,a[data-act]'); if (!b || b.disabled) return;
    const a = b.dataset, S = this.st;
    if (a.act === 'labels') return this.run('Labels', async () => { const r = await this.ws({ type: 'ssv_dashboard/create_labels' }); return r.created.length ? 'created ' + r.created.join(', ') : 'nothing to create'; });
    if (a.act === 'sync') return this.run('Run timers', async () => { const r = await this.ws({ type: 'ssv_dashboard/sync_timers' }); return r.changes.length ? r.changes.join(', ') : 'nothing to change'; });
    if (a.act === 'runs') return this.run('Run times', async () => { await this.ws({ type: 'ssv_dashboard/runs/save', runs: S.runs }); return 'saved'; });
    if (a.hacs) return this.run('HACS', () => this.hacsInstall(a.hacs));
    if (a.act === 'restart') return this.run('Restart', async () => { await this._hass.callService('homeassistant', 'restart', {}); return 'Home Assistant is restarting'; });
    if (a.act === 'new') { S.ed = newPanel(); return this.render(); }
    if (a.edit) { const p = S.panels.find(x => x.id === a.edit); S.ed = Object.assign(newPanel(), JSON.parse(JSON.stringify(p)), { _existing: true }); S.ed.night = Object.assign({ enabled: true, from: 22, to: 7 }, p.night || {}); return this.render(); }
    if (a.act === 'cancel') { S.ed = null; return this.render(); }
    if (a.act === 'save') return this.run('Panel', () => this.savePanel());
    if (a.del) return this.run('Panel removed', async () => { await this.ws({ type: 'ssv_dashboard/panels/delete', panel: a.del }); return a.del + ' (its dashboard and label are kept)'; });
    if (a.legacy != null) return this.run('Move', () => this.moveLegacy(S.legacy[+a.legacy]));
    if (a.default) return this.run('Start page', () => this.setDefault(a.default));
  }

  /* ---------------------------------------------------------------- view */
  render() {
    const S = this.st, I = S.info || {};
    const lab = I.labels || {}; const missing = Object.keys(lab).filter(k => !lab[k]);
    const res = (S.resources || []).map(r => r.url || '');
    const ok = (v) => v ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>';
    const hacsOn = !!S.hacs;
    const areaName = (id) => ((S.areas || []).find(a => a.area_id === id) || {}).name || id;
    const act = (c) => {
      if (c.ok) return '';
      const r = c.hacs && this.hacsRepo(c.hacs);
      if (r && !r.installed) return `<button data-hacs="${esc(c.hacs)}">Install via HACS</button>`;
      if (c.domain) return `<a class="btn" href="/config/integrations/dashboard/add?domain=${esc(c.domain)}" target="_top">Add</a>`;
      if (c.key === 'scene_yaml') return '<span class="dim">Add the line to configuration.yaml</span>';
      if (c.hacs && !hacsOn) return '<span class="dim">Install HACS first</span>';
      return '';
    };
    const checkRows = (I.checks || []).map(c => `<tr><td>${esc(c.name)}</td><td>${esc(c.for)}</td><td>${NEED[c.need] || ''}</td><td>${ok(c.ok)}</td><td class="act">${act(c)}</td></tr>`).join('')
      + HACS_FRONTEND.map(f => { const has = res.some(u => f.re.test(u)); const r = this.hacsRepo(f.repo);
        return `<tr><td>${esc(f.name)}</td><td>${esc(f.for)}</td><td>${NEED[f.need]}</td><td>${ok(has)}</td><td class="act">${has ? '' : r ? `<button data-hacs="${esc(f.repo)}">Install via HACS</button>` : '<span class="dim">HACS → Frontend</span>'}</td></tr>`; }).join('')
      + `<tr><td>Labels</td><td>Lights, curtains, scenes, water…</td><td>Required</td><td>${ok(!missing.length)}</td><td class="act">${missing.length ? '<button data-act="labels">Create ' + missing.length + ' missing</button>' : ''}</td></tr>`;

    const panelRows = (S.panels || []).map(p => {
      const path = dashPath(p.id), def = S.defaultPanel === path;
      const rooms = (p.areas || []).length ? p.areas.map(areaName).join(', ') : 'Whole house';
      return `<tr><td><a href="/${esc(path)}/main" target="_top">${esc(p.name)}</a>${def ? ' <span class="tag">start page</span>' : ''}<div class="mono dim">panel_${esc(p.id)}</div></td>
        <td>${esc(TYPES[p.type] ? TYPES[p.type].label : p.type)}</td><td>${esc((PURPOSES[p.purpose] || {}).label || p.purpose)}</td><td>${esc(rooms)}</td>
        <td class="act"><button data-edit="${esc(p.id)}">Edit</button><button data-default="${esc(path)}"${def ? ' disabled' : ''}>Start page</button><button class="sec" data-del="${esc(p.id)}">Remove</button></td></tr>`;
    }).join('') || '<tr><td colspan="5" class="dim">No panels yet — press “New panel”.</td></tr>';
    const legacyRows = (S.legacy || []).map((x, i) => `<tr><td><a href="/${esc(x.d.url_path)}/main" target="_top">${esc(x.d.title)}</a></td><td>${esc(x.c.file)}.html</td><td class="mono" colspan="2">${esc(x.c.url)}</td>
        <td class="act">${x.c.legacy ? `<button class="warn" data-legacy="${i}">Move to SSV files</button>` : ''}<button data-default="${esc(x.d.url_path)}"${S.defaultPanel === x.d.url_path ? ' disabled' : ''}>Start page</button></td></tr>`).join('');

    const walls = Object.keys(this._hass.states).filter(id => id.startsWith('climate.') && ((S.ents || []).find(e => e.ei === id) || {}).lb && S.ents.find(e => e.ei === id).lb.includes('heated_wall'));
    const runRows = walls.map(id => `<tr><td>${esc(this._hass.states[id].attributes.friendly_name || id)}</td><td class="mono">timer.inex_wall_${esc(id.split('.')[1])}</td><td>${ok(!!this._hass.states['timer.inex_wall_' + id.split('.')[1]])}</td><td><input type="number" min="5" step="5" data-f="run" data-eid="${esc(id)}" placeholder="${S.runs ? S.runs.wall : 180}" value="${S.runs && S.runs.per[id] ? S.runs.per[id] : ''}"></td></tr>`).join('')
      || '<tr><td colspan="4" class="dim">No climate labelled Heated Wall yet.</td></tr>';

    this.shadowRoot.innerHTML = `<style>
      :host{display:block;min-height:100vh;background:var(--primary-background-color,#fafafa);color:var(--primary-text-color,#212121);font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif)}
      .wrap{max-width:1150px;margin:0 auto;padding:16px}
      h1{font-size:24px;font-weight:400;margin:8px 0 16px}
      .card{background:var(--card-background-color,#fff);border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid var(--divider-color,#ddd)}
      h2{font-size:18px;font-weight:500;margin:0 0 8px}
      table{width:100%;border-collapse:collapse;table-layout:fixed}
      td,th{padding:8px 6px;border-bottom:1px solid var(--divider-color,#ddd);text-align:left;vertical-align:middle;overflow-wrap:anywhere}
      th{font-weight:500;color:var(--secondary-text-color,#666);font-size:13px}
      .mono{font-family:ui-monospace,monospace;font-size:12px}
      .act{text-align:right} .act button,.act .btn{margin:2px 0 2px 6px}
      button,.btn{font:inherit;font-size:14px;padding:7px 12px;border-radius:8px;border:1px solid var(--primary-color,#03a9f4);background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);cursor:pointer;text-decoration:none;display:inline-block}
      button[disabled]{opacity:.45;cursor:default} button.sec{background:transparent;color:var(--primary-color,#03a9f4)} button.warn{background:var(--warning-color,#f39c12);border-color:var(--warning-color,#f39c12)}
      .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;align-items:start}
      label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--secondary-text-color,#666)}
      label.chk{flex-direction:row;align-items:center;gap:6px;color:var(--primary-text-color,#212121);font-size:14px}
      input,select{font:inherit;padding:8px;border-radius:8px;border:1px solid var(--divider-color,#ddd);background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)}
      input[type=checkbox]{padding:0;width:18px;height:18px} input[type=number]{width:90px}
      .ok{color:var(--success-color,#2e7d32);font-weight:700}.bad{color:var(--error-color,#c62828);font-weight:700}.dim{color:var(--secondary-text-color,#666)}
      .tag{font-size:11px;padding:2px 6px;border-radius:6px;background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff)}
      .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
      .box{border:1px solid var(--divider-color,#ddd);border-radius:10px;padding:10px;display:flex;flex-wrap:wrap;gap:6px 16px;max-height:220px;overflow:auto}
      .log{font-family:ui-monospace,monospace;font-size:12px;max-height:180px;overflow:auto}
      p{margin:4px 0 12px;color:var(--secondary-text-color,#666)}
      .note{background:var(--warning-color,#f39c12);color:#fff;padding:10px 12px;border-radius:8px;margin-bottom:12px;display:flex;gap:12px;align-items:center;justify-content:space-between}
    </style><div class="wrap">
      <h1>SSV Dashboard <span class="dim">v${esc(I.version || '?')}</span></h1>
      ${S.restart ? '<div class="note">An integration was downloaded. Restart Home Assistant, then come back and press Add.<button data-act="restart">Restart now</button></div>' : ''}

      <div class="card"><h2>Integrations</h2>
        <p>What each part of the panels needs. A tab without its integration is simply not shown.</p>
        <table><tr><th style="width:24%">Integration</th><th>Needed for</th><th style="width:12%">Need</th><th style="width:7%">State</th><th style="width:20%"></th></tr>${checkRows}</table>
        ${hacsOn ? '' : '<p class="dim" style="margin-top:8px">HACS is not installed or not reachable — install buttons are hidden.</p>'}
      </div>

      <div class="card"><h2>Panels</h2>
        <p>A panel is one screen: what it is, where it hangs, which rooms it controls and which tabs it shows. Each panel gets its own dashboard and its own label <span class="mono">Panel · name</span> — put that label on a room or on a single device to add it to this panel.</p>
        <table><tr><th style="width:24%">Panel</th><th style="width:13%">Screen</th><th style="width:18%">Purpose</th><th>Rooms</th><th style="width:27%"></th></tr>${panelRows}</table>
        <div class="row" style="margin-top:12px"><button data-act="new">New panel</button></div>
        ${this.editor()}
      </div>

      ${legacyRows ? `<div class="card"><h2>Other dashboards with SSV pages</h2><p>Made before 1.1 or by hand. They keep working; “Move to SSV files” switches dashboards that still use /local/morea.</p>
        <table><tr><th style="width:24%">Dashboard</th><th style="width:13%">Page</th><th colspan="2">Address</th><th style="width:27%"></th></tr>${legacyRows}</table></div>` : ''}

      <div class="card"><h2>Run timers</h2>
        <p>Every climate labelled Heated Wall and every water function (Water + Hot Water / Recirculation) gets its run timer by itself; when the label is removed, the timer is removed. SSV Dashboard turns the device off when the timer ends.</p>
        <div class="row" style="margin-bottom:10px"><label class="chk">Heated wall run, minutes <input type="number" min="5" step="5" data-f="run" value="${S.runs ? S.runs.wall : 180}"></label></div>
        <table><tr><th>Heated wall</th><th>Timer entity</th><th style="width:8%">Exists</th><th style="width:18%">Own run, min</th></tr>${runRows}</table>
        <div class="row" style="margin-top:12px"><button data-act="runs">Save run times</button><button class="sec" data-act="sync">Check timers now</button></div>
      </div>

      <div class="card"><h2>Log</h2><div class="log">${S.log.map(l => `<div class="${l.bad ? 'bad' : ''}">${esc(l.t)} · ${esc(l.m)}</div>`).join('') || '<span class="dim">—</span>'}</div></div>
    </div>`;
    if (S.busy) this.shadowRoot.querySelectorAll('button').forEach(b => b.disabled = true);
  }

  editor() {
    const ed = this.st.ed; if (!ed) return '';
    const areas = this.st.areas || [];
    const areaBoxes = areas.map(a => `<label class="chk"><input type="checkbox" data-f="area" value="${esc(a.area_id)}"${ed.areas.includes(a.area_id) ? ' checked' : ''}>${esc(a.name)}</label>`).join('') || '<span class="dim">No areas in Home Assistant yet</span>';
    const tabBoxes = TABS.map(([k, n]) => `<label class="chk"><input type="checkbox" data-f="tab" value="${k}"${ed.tabs[k] === false ? '' : ' checked'}>${n}</label>`).join('');
    const roomOpts = ed.areas.map(id => `<option value="${esc(id)}"${id === ed.room ? ' selected' : ''}>${esc((areas.find(a => a.area_id === id) || {}).name || id)}</option>`).join('');
    const hours = (v) => Array.from({ length: 24 }, (_, h) => `<option value="${h}"${+v === h ? ' selected' : ''}>${String(h).padStart(2, '0')}:00</option>`).join('');
    return `<div class="card" style="margin-top:16px;border-color:var(--primary-color,#03a9f4)"><h2>${ed._existing ? 'Edit panel' : 'New panel'}</h2>
      <div class="grid">
        <label>Name<input data-f="name" value="${esc(ed.name)}" placeholder="Gym, Office, Kitchen…"></label>
        <label>Id (address and label)<input id="pid" data-f="id" value="${esc(ed.id)}"${ed._existing ? ' disabled' : ''} placeholder="gym"></label>
        <label>Screen<select data-f="type">${Object.entries(TYPES).map(([k, v]) => `<option value="${k}"${k === ed.type ? ' selected' : ''}>${v.label}</option>`).join('')}</select></label>
        <label>Purpose<select data-f="purpose">${Object.entries(PURPOSES).map(([k, v]) => `<option value="${k}"${k === ed.purpose ? ' selected' : ''}>${v.label}</option>`).join('')}</select></label>
      </div>
      <p style="margin-top:12px">Rooms this panel controls ${ed.type === 'room' ? '(a room panel needs at least one)' : '(none = whole house)'}:</p>
      <div class="box">${areaBoxes}</div>
      <div class="grid" style="margin-top:12px">
        <label>Room shown big on Home<select data-f="room"><option value="">—</option>${roomOpts}</select></label>
        <label>Villa name (header)<input data-f="villa" value="${esc(ed.villa || '')}" placeholder="${esc((this.st.info || {}).location_name || '')}"></label>
        <label>Line under the name<input data-f="place" value="${esc(ed.place || '')}" placeholder="${esc(ed.name || 'Gym')}"></label>
      </div>
      <p style="margin-top:12px">Tabs (shown only when there is something for them):</p>
      <div class="box">${tabBoxes}</div>
      <div class="row" style="margin-top:12px"><label class="chk"><input type="checkbox" data-f="night"${ed.night.enabled ? ' checked' : ''}>Night screen</label>
        <label class="chk">from <select data-f="from">${hours(ed.night.from)}</select></label><label class="chk">to <select data-f="to">${hours(ed.night.to)}</select></label></div>
      <div class="row" style="margin-top:16px"><button data-act="save">Save panel and dashboard</button><button class="sec" data-act="cancel">Cancel</button></div>
    </div>`;
  }
}
if (!customElements.get('ssv-setup')) customElements.define('ssv-setup', SSVSetup);
