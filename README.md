# SSV Dashboard

Wall panels, room panels, a phone and a tablet dashboard for Home Assistant — installed and updated from HACS.

Everything on the panels is built from Home Assistant itself: floors → rooms → entities, sorted by **labels**. Nothing is listed by hand, so the same release works on every site.

| Part | What it is |
| --- | --- |
| Wall panel 10″ (`panel.html`) | Home, Rooms with a page per room, Lights, Climate, Heating, Curtains, Water, Cameras, Intercom, Security, Schedule, night screen, alerts |
| Room panel 4″ (`room.html`) | Light, curtains, climate, WC and water of one room, night mode |
| Phone (`phone.html`) | Same logic with bottom tabs Home · Rooms · Lights · Climate · More; on a screen of 600 × 900 or more it switches to the Tablet dashboard |
| User scenes | Guests create, change and delete their own scenes from devices labelled **Scene Device** — only with values the device supports |
| Run timers | “Run 3h” on heated walls and hot water / recirculation; the integration turns the device off when the timer ends |
| `sensor.ssv_time` | Panel clocks follow Home Assistant time, not the tablet's clock |
| Panels | Each screen is a panel with a name, screen type (10″, 4″, Tablet, Phone), purpose (residential, hotel room, office, gym, common area), rooms and tabs; each gets its own dashboard and label `Panel · <name>` |
| SSV Dashboard page | Admin page in the sidebar: panels, start page, run times, and a check of the integrations each tab needs with install through HACS |

## Install

1. HACS → ⋮ → **Custom repositories** → `https://github.com/BelkinDm/ssv-dashboard`, type **Integration**.
2. Find **SSV Dashboard** → **Download** → restart Home Assistant.
3. **Settings → Devices & services → Add integration → SSV Dashboard**.
4. Open **SSV Dashboard** in the sidebar:
   - **Integrations** shows what every tab needs; missing ones from HACS (Scheduler, WebRTC Camera, kiosk-mode, card-mod) install with one button, then restart and press **Add**;
   - **New panel** — name, screen, purpose, rooms, tabs, night screen; saving creates the dashboard `/ssv-<id>/main` and the label `Panel · <name>`;
   - **Start page** makes a dashboard the start page for everyone;
   - **Run timers** are created and removed by themselves as labels change; set the run time here.

Then put labels on your entities (Settings → Entities → select → Add label). The labels are created by the integration.

| Label | Put it on |
| --- | --- |
| `light`, `on_off_only` | Lights; dimmable light shown as a plain switch |
| `climate`, `ac`, `ufh`, `heated_wall`, `t_h` | AC, floor heating, heated walls, temperature / humidity sensors |
| `curtain`, `net`, `blackout`, `roller`, `shutter`, `left`, `right`, `both_side` | Curtains and their look |
| `scene`, `scene_device` | Ready scenes; devices guests may use in their own scenes |
| `water`, `hot_water`, `recirculation`, `valve`, `water_meter` | Water functions |
| `cctv`, `alarm`, `doorbell`, `critical` | Cameras, alarm, intercom, leak / smoke sensors |
| `home`, `schedule`, `no_panel` | Tile on Home, Scheduler entities, hide from all panels |
| `panel_<id>` | Made with each panel. On an area: the whole room goes to that panel. On a device or entity: just that device, wherever it is installed |

## Panel address parameters

| Parameter | Meaning |
| --- | --- |
| `panel=` | Panel id — everything else comes from the panel's settings on the SSV Dashboard page |
| `room=`, `villa=`, `place=` | Older addresses only: still honoured and win over the stored settings |
| `tablet=` | Phone only: where large screens are sent (default `/ssv-tablet/main`) |
| `stay=1` | Phone only: never switch to Tablet |
| `diag=1` | Installer view: also show unavailable entities |

## Updates

Publish a GitHub release with a higher `version` in `manifest.json`. HACS shows the update; after **Update** and a restart, every open panel reloads itself within 10 minutes. Rooms, labels, users, guests' scenes and settings are not touched by an update.

## Moving from the old `/local/morea` files

On the SSV Dashboard page, dashboards that still use `/local/morea/…` show **Move to SSV files**. After moving all of them, the old `inex_scenes` integration and the two “INEX Panel – … timer finished” automations can be removed: scenes made with it keep working (`inex_user_…` ids are accepted), and the timers are handled by SSV Dashboard.

---

## По-русски кратко

1. HACS → ⋮ → Custom repositories → адрес репозитория, тип Integration → Download → перезапуск HA.
2. Настройки → Устройства и службы → Добавить интеграцию → **SSV Dashboard**.
3. В боковом меню **SSV Dashboard**: Quick start (Living & Kitchen, Tablet, Phone), «Add a dashboard» для комнатных панелей, «Start page» — стартовая для всех, «Create missing timers» — таймеры для кнопок Run.
4. Из HACS (Frontend) поставить **kiosk-mode** и при желании **card-mod**.
5. Повесить метки на сущности — сами метки интеграция создаёт.

Обновление: новый Release на GitHub → HACS → Обновить → перезапуск. Панели перезагрузятся сами в течение 10 минут.
