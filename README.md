# SSV Dashboard

Wall panels, room panels, a phone and a tablet dashboard for Home Assistant — installed and updated from HACS.

Everything on the panels is built from Home Assistant itself: floors → rooms → entities, sorted by **labels**. Nothing is listed by hand, so the same release works on every site.

| Part | What it is |
| --- | --- |
| Wall panel 10″ (`panel.html`) | Home, Rooms with a page per room, Lights, Climate, Heating, Curtains, Water, Cameras, Intercom, Security, Schedule, night screen, alerts |
| Room panel 4″ (`room.html`) | Light, curtains, climate, WC and water of one room, night mode |
| Phone (`phone.html`) | Same logic with bottom tabs Home · Rooms · Lights · Climate · More; on a screen of 600 × 900 or more it switches to the Tablet dashboard |
| User scenes | Guests create, change and delete their own scenes from devices labelled **Scene Device** — only with values the device supports |
| Run timers | Run buttons (e.g. 1h / 2h / 3h) for heated walls, floor heating, hot water and recirculation — chosen on the SSV Dashboard page; the integration turns the device off when the timer ends |
| `sensor.ssv_time` | Panel clocks follow Home Assistant time, not the tablet's clock |
| Panels | Each screen is a panel with a name, screen type (10″, 4″, Tablet, Phone; 5.5″ Main / Room coming), purpose (residential, hotel room, office, gym, common area), rooms, attached rooms (WC, Shower…) and tabs; each gets its own dashboard and labels `Panel <Name>`, `Panel <Name> <Room>` |
| SSV Dashboard page | Admin page in the sidebar: panels, start page, run times, and a check of the integrations each tab needs with install through HACS |

## Install

1. HACS → ⋮ → **Custom repositories** → `https://github.com/BelkinDm/ssv-dashboard`, type **Integration**.
2. Find **SSV Dashboard** → **Download** → restart Home Assistant.
3. **Settings → Devices & services → Add integration → SSV Dashboard**.
4. Open **SSV Dashboard** in the sidebar:
   - **Integrations** shows what every tab needs; missing ones from HACS (Scheduler, WebRTC Camera, kiosk-mode, card-mod) install with one button, then restart and press **Add**;
   - **New panel** — name, screen, purpose, rooms, attached rooms (room panel), tabs, night screen; saving creates the dashboard `/ssv-<id>/main` and the labels `Panel <Name>` / `Panel <Name> <Room>`;
   - **Start page** makes a dashboard the start page for everyone;
   - **Run timers** — tick heated walls, floor heating, hot water, recirculation, type the buttons in minutes, press Save;
   - when a new SSV Dashboard is out, the page shows **Update now** and Home Assistant shows a notification (push to a phone: integration options → notify service).

Then put labels on your entities (Settings → Entities → select → Add label). The labels are created by the integration, all named in one style: every word capitalised, spaces between words, abbreviations in capitals (AC, UFH, CCTV, WC). The full list is at the [bottom of this page](#labels); the SSV Dashboard page shows the same list live, with the labels of every panel and where each label is used.

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

1. HACS → ⋮ → Custom repositories → `https://github.com/BelkinDm/ssv-dashboard`, тип Integration → Download → перезапуск HA.
2. Настройки → Устройства и службы → Добавить интеграцию → **SSV Dashboard**.
3. В боковом меню **SSV Dashboard**:
   - **Integrations** — чего не хватает вкладкам; недостающее из HACS ставится кнопкой, дальше перезапуск и **Add**;
   - **New panel** — название, экран, назначение, комнаты, привязанные помещения, вкладки, ночной экран. При сохранении создаются дашборд `/ssv-<id>/main` и метки `Panel <Имя>`, `Panel <Имя> <Помещение>`; у комнатной панели всегда есть `Panel <Имя> WC`;
   - **Run timers** — отметить тёплые стены, тёплые полы, бойлер, рециркуляцию, задать кнопки в минутах, Save;
   - **Labels** внизу страницы — все метки SSV, включая метки панелей, и где они уже стоят.
4. Повесить метки на зоны, устройства и сущности — сами метки создаёт интеграция.

Обновление: новый Release на GitHub → HACS → Обновить → перезапуск. Панели перезагрузятся сами в течение 10 минут; о новой версии SSV сообщает уведомлением в HA.

## Labels

Every label SSV Dashboard reads. Panels look for the **id**; Settings → Labels shows the **name**. Labels are created by the integration — never type an id by hand.

| Label | Id | What for |
| --- | --- | --- |
| Light | `light` | Lights shown on the panels (also a switch that drives a light) |
| On Off Only | `on_off_only` | Dimmable light shown as a plain On / Off switch |
| Climate | `climate` | Climate tab: room thermostats |
| AC | `ac` | Air conditioners (with fan speed buttons on room panels) |
| UFH | `ufh` | Floor heating (climate or switch); can get Run buttons |
| Heated Wall | `heated_wall` | Heated walls; can get Run buttons |
| Temperature Humidity | `t_h` | Temperature / humidity sensors for the room header |
| Curtain | `curtain` | Curtains |
| Net | `net` | Curtain look: sheer |
| Blackout | `blackout` | Curtain look: blackout |
| Roller | `roller` | Roller blinds |
| Shutter | `shutter` | Shutters |
| Left | `left` | Curtain opens to the left |
| Right | `right` | Curtain opens to the right |
| Both Sides | `both_side` | Curtain opens to both sides |
| Scene | `scene` | Ready scenes (script.* shown as a scene) |
| Scene Device | `scene_device` | Devices guests may use in their own scenes |
| User Scene | `user_scene` | Put by SSV on scenes made by guests |
| Home | `home` | Light or tile picked for the Home page |
| Water | `water` | Water tab (together with a function label) |
| Hot Water | `hot_water` | Water function: hot water / boiler; can get Run buttons |
| Recirculation | `recirculation` | Water function: recirculation; can get Run buttons |
| Valve | `valve` | Water function: main valves |
| Water Meter | `water_meter` | Water function: meters |
| Schedule | `schedule` | Devices offered on the Schedule tab |
| CCTV | `cctv` | Cameras on the Cameras tab |
| Alarm | `alarm` | Alarm panel on the Security tab |
| Critical | `critical` | Leak / smoke / gas sensors: alert on every panel |
| Doorbell | `doorbell` | Intercom device (and its camera) |
| No Panel | `no_panel` | Never shown on any panel |

Made with each panel on the SSV Dashboard page (the live list with every panel's labels is at the bottom of that page):

| Label | Id | What for |
| --- | --- | --- |
| Panel &lt;Name&gt; | `panel_<id>` | On an area: the whole room goes to that panel. On a device or entity: just that device, wherever it is installed |
| Panel &lt;Name&gt; WC | `panel_<id>_wc` | WC tab of a room panel — every room panel has it |
| Panel &lt;Name&gt; &lt;Room&gt; | `panel_<id>_<room>` | Tab of another attached room (Shower, Balcony…) |

Example: panel **Bedroom 3** → Panel Bedroom 3 (`panel_bedroom_3`), Panel Bedroom 3 WC (`panel_bedroom_3_wc`), Panel Bedroom 3 Shower (`panel_bedroom_3_shower`).
