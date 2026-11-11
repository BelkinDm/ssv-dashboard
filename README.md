# SSV Dashboard

Wall panels, room panels, a phone and a tablet dashboard for Home Assistant — installed and updated from HACS.

Everything on the panels is built from Home Assistant itself: floors → rooms → entities, sorted by **labels**. Nothing is listed by hand, so the same release works on every site.

| Part | What it is |
| --- | --- |
| Wall panel 10″ (`panel.html`) | Home, Rooms with a page per room, Lights, Climate (air conditioning; floor heating as a status line), Heating (heated walls and floor heating), Curtains, Water, Cameras, Intercom, Security, Schedule, night screen, alerts |
| Room panel 4″ (`room.html`) | Light, curtains, climate, WC and water of one room, night mode; the header shows the room's temperature and humidity, on the WC tab the WC's own (sensors labelled Temperature Humidity in the WC) |
| Phone (`phone.html`) | Same logic with bottom tabs Home · Rooms · Lights · Climate · More; on a screen of 600 × 900 or more it switches to the Tablet dashboard |
| User scenes | The owner and users create, change and delete their own scenes from devices labelled **Scene Device** — only with values the device supports; brightness, colour, AC mode, set point and fan speed; each device can start later and go back after N minutes; check boxes choose the panels and the 10″ Home page |
| Schedules | Schedule tab (10″, tablet, phone): device, days and On / Off times. All choices open in panel-style windows, never the white Android lists: **Device** — rooms on the left, devices with a coloured icon on the right (light — amber bulb, boiler — red drop, pump — green, AC — blue snowflake, floor / wall heating — red, curtains — violet, watering — teal); **Action** — On / Off, Open / Close, Heat or Cool / Off (climate rows with Heat / Cool also have a set point); **Time** — 24 h, two fields hours : minutes and a number pad that only lets you type 00–23 and 00–59; Sunrise / Sunset with a shift. Windows open and close softly |
| Floor-heating thermostat | **Make thermostat** on the SSV page: Generic Thermostat on the relay + room sensor, set point 16–35 °C, step 1 °C, 5 min between valve switchings. It heats up to the set point, then waits (Standby) until the room is 2 °C under it (cold tolerance 2, hot tolerance 0); switched on or set higher while the room is under the set point, it opens the valve at once. Panels show three states: Heating (valve open), Standby, Off. Thermostats SSV made earlier get the step and hysteresis (1.6.1) and the 16–35 °C range and hysteresis 2 / 0 (1.6.4) once at the first start of that version |
| Run timers | Run buttons (e.g. 1h / 2h / 3h) for heated walls, hot water and recirculation (floor heating: On / Off, set point and schedules, no Run) — chosen on the SSV Dashboard page; the integration turns the device off when the timer ends |
| `sensor.ssv_time` | Panel clocks follow Home Assistant time, not the tablet's clock |
| Panels | Each screen is a panel with a name, screen type (10″, 4″, Tablet, Phone; 5.5″ Main / Room coming), purpose (residential, hotel room, office, gym, common area), rooms, attached rooms (WC, Shower…) and tabs; each gets its own dashboard and labels `Panel <Name>`, `Panel <Name> <Room>` |
| SSV Dashboard page | Admin page in the sidebar: panels, start page, scene places and order per panel, tablet start files, run times, and a check of the integrations each tab needs with install through HACS |
| Screen care | Panels dim the screen backlight to 20 % after the same idle time as the return to Home, through Fully Kiosk (first touch only wakes); a panel never stays on “404: Not Found” or “Bad Gateway” while Home Assistant starts |

## Install

1. HACS → ⋮ → **Custom repositories** → `https://github.com/BelkinDm/ssv-dashboard`, type **Integration**.
2. Find **SSV Dashboard** → **Download** → restart Home Assistant.
3. **Settings → Devices & services → Add integration → SSV Dashboard**.
4. Open **SSV Dashboard** in the sidebar:
   - **Integrations** shows what every tab needs; missing ones from HACS (Scheduler, WebRTC Camera, kiosk-mode, card-mod) install with one button, then restart and press **Add**;
   - **New panel** — name, screen, purpose, rooms, attached rooms (room panel), tabs, night screen; saving creates the dashboard `/ssv-<id>/main` and the labels `Panel <Name>` / `Panel <Name> <Room>`;
   - **Start page** makes a dashboard the start page for everyone;
   - **Tablet file** downloads the start file of a panel for its tablet (see [Tablets](#tablets-fully-kiosk));
   - in the panel editor, **Scenes** sets how many scene places Home (10″) or the button row (4″) has and the order of the scenes;
   - **Floor heating on relays** — relays / valves with the label UFH; where the room has a temperature sensor (label Temperature Humidity), **Make thermostat** creates Home Assistant's Generic Thermostat (relay + sensor): the panels show the room temperature and the set point; without a sensor the panels show On / Off and Run;
   - **Run timers** — tick heated walls, hot water, recirculation, type the buttons in minutes, press Save;
   - when a new SSV Dashboard is out, the page shows **Update now** and Home Assistant shows a notification (push to a phone: integration options → notify service).

Then put labels on your entities (Settings → Entities → select → Add label). The labels are created by the integration, all named in one style: every word capitalised, spaces between words, abbreviations in capitals (AC, UFH, CCTV, WC). The full list is at the [bottom of this page](#labels); the SSV Dashboard page shows the same list live, with the labels of every panel and where each label is used.

## Tablets (Fully Kiosk)

When the power comes back, a tablet starts faster than Home Assistant. Without help it shows “Unable to connect”, “Bad Gateway” or a white “404: Not Found” and stays there. SSV Dashboard avoids this in two places:

1. **Inside Home Assistant** the dashboards open the panel through `/local/ssv/loader.html` (the integration writes it to `/config/www/ssv/`). Home Assistant serves it even while it is still starting; it shows “Reconnecting…” and opens the panel as soon as SSV Dashboard answers. The loader stays as a guard around the panel: every 15 s it checks that the panel is still there, and if after an update or a restart the panel was left on “404: Not Found”, “Bad Gateway” or a blank screen, it shows “Reconnecting…” · “Your home automation will start soon” and opens the panel again as soon as SSV Dashboard answers — no reload by hand, no Fully Kiosk timer. On a new install `/local` works after one more restart; the SSV Dashboard page then switches the dashboards over by itself.
2. **On the tablet** keep the panel's start file: SSV Dashboard page → panel → **Tablet file** → `ssv-start-<id>.html`. Copy it to the tablet's *Download* folder.

Fully Kiosk Browser settings (menu names can differ a little between Fully versions):

| Setting | Value |
| --- | --- |
| Web Content Settings → Start URL | `file:///sdcard/Download/ssv-start-<id>.html` |
| Web Content Settings → Enable File Access / Allow local files | on |
| Web Auto Reload → Reload on Network Reconnect | on |
| Advanced Web Settings → Enable JavaScript Interface | on — the panel dims the screen backlight to 20 % when idle; without it the screen is not dimmed |
| Device Management → Keep Screen On | on |

The start file shows the time and “Reconnecting…”, checks Home Assistant every few seconds (`/ssv_dashboard/ping.png`) and opens the panel's dashboard only when SSV Dashboard answers. An open panel keeps its last view while the connection is lost and reconnects by itself.

## Panel address parameters

| Parameter | Meaning |
| --- | --- |
| `panel=` | Panel id — everything else comes from the panel's settings on the SSV Dashboard page |
| `room=`, `villa=`, `place=` | Older addresses only: still honoured and win over the stored settings |
| `tablet=` | Phone only: where large screens are sent (default `/ssv-tablet/main`) |
| `stay=1` | Phone only: never switch to Tablet |
| `diag=1` | Installer view: also show unavailable entities |

## Updates

Publish a GitHub release with a higher `version` in `manifest.json`. HACS shows the update; after **Update** and a restart, every open panel reloads itself within 10 minutes. Rooms, labels, users, user scenes and settings are not touched by an update.

## Moving from the old `/local/morea` files

On the SSV Dashboard page, dashboards that still use `/local/morea/…` show **Move to SSV files**. After moving all of them, the old `inex_scenes` integration and the two “INEX Panel – … timer finished” automations can be removed: scenes made with it keep working, and the timers are handled by SSV Dashboard.

Since 1.5 nothing SSV makes carries the old INEX name: at start SSV replaces timer helpers `timer.inex_…` with `timer.ssv_…` (same duration and labels; a timer that is running is replaced after it ends) and gives old user scenes the id `ssv_user_…` (the scene keeps its name and labels). Night switches are `input_boolean.ssv_night_<room>` (the old `inex_night_` still works). Schedules made on the panels get the tag `ssv`.

---

## По-русски кратко

1. HACS → ⋮ → Custom repositories → `https://github.com/BelkinDm/ssv-dashboard`, тип Integration → Download → перезапуск HA.
2. Настройки → Устройства и службы → Добавить интеграцию → **SSV Dashboard**.
3. В боковом меню **SSV Dashboard**:
   - **Integrations** — чего не хватает вкладкам; недостающее из HACS ставится кнопкой, дальше перезапуск и **Add**;
   - **New panel** — название, экран, назначение, комнаты, привязанные помещения, вкладки, ночной экран. При сохранении создаются дашборд `/ssv-<id>/main` и метки `Panel <Имя>`, `Panel <Имя> <Помещение>`; у комнатной панели всегда есть `Panel <Имя> WC`;
   - **Floor heating on relays** — тёплый пол на реле или клапане (метка UFH). Есть датчик температуры в комнате — кнопка **Make thermostat** создаёт термостат HA (реле + датчик): на панели температура и уставка. Датчика нет — на панели только Вкл / Выкл и Run;
   - **Run timers** — отметить тёплые стены, бойлер, рециркуляцию (у тёплых полов таймеров нет: Вкл / Выкл, уставка, расписания), задать кнопки в минутах, Save;
   - **Labels** внизу страницы — все метки SSV, включая метки панелей, и где они уже стоят. Метки окрашены по группам: свет — жёлтые, климат — оранжевые, шторы — фиолетовые, сцены — зелёные, вода — синие, безопасность — красные, панели — бирюзовые, комнаты — серые; цвет, заданный вручную, не меняется;
   - **Tablet file** у панели — стартовый файл для планшета: положить в папку Download и указать в Fully Kiosk как Start URL (`file:///sdcard/Download/ssv-start-<id>.html`). Планшет ждёт HA и не зависает на «Bad Gateway» / «404».
4. Пользовательские сцены делают сами жильцы на панели: яркость, цвет, режим и уставка кондиционера, скорость вентилятора; у каждого устройства своя задержка включения и возврат через N минут; галочками — на каких панелях и на главной 10″.
5. Повесить метки на зоны, устройства и сущности — сами метки создаёт интеграция.

Обновление: новый Release на GitHub → HACS → Обновить → перезапуск. Панели перезагрузятся сами в течение 10 минут; о новой версии SSV сообщает уведомлением в HA. Если после обновления или перезапуска панель осталась на «404: Not Found», «Bad Gateway» или пустом экране, загрузчик это заметит (проверка каждые 15 с), покажет «Reconnecting…» и сам откроет панель, как только SSV ответит.

## Labels

Every label SSV Dashboard reads. Panels look for the **id**; Settings → Labels shows the **name**. Labels are created by the integration — never type an id by hand.

Colours by group, so the list reads at a glance (a colour you set by hand is kept):

| Colour | Labels |
| --- | --- |
| Yellow | Light, On Off Only |
| Orange | Climate, AC, UFH, Heated Wall, Temperature Humidity |
| Purple | Curtain, Net, Blackout, Roller, Shutter, Left, Right, Both Sides |
| Green | Scene, Scene Device, User Scene |
| Blue | Water, Hot Water, Recirculation, Valve, Water Meter |
| Indigo | Schedule |
| Red | CCTV, Alarm, Critical, Doorbell |
| Brown | Home, No Panel |
| Teal | Panel &lt;Name&gt;, Panel &lt;Name&gt; &lt;Room&gt; |
| Grey | room labels (Bedroom 1, Kitchen …) |

| Label | Id | What for |
| --- | --- | --- |
| Light | `light` | Lights shown on the panels (also a switch that drives a light) |
| On Off Only | `on_off_only` | Dimmable light shown as a plain On / Off switch |
| Climate | `climate` | Climate tab: room thermostats |
| AC | `ac` | Air conditioners (with fan speed buttons on room panels) |
| UFH | `ufh` | Floor heating: a climate, or a relay / valve (switch) — On / Off and its schedules (no Run buttons); with a room sensor the SSV page makes a thermostat of it |
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
| Scene Device | `scene_device` | Devices people may use in their own user scenes |
| User Scene | `user_scene` | Put by SSV on user scenes (made on the panels) |
| Home | `home` | Light or tile picked for the Home page; on a scene — one of the scene buttons on Home of the 10″ panels (set by the Home check box in the scene editor) |
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
| Panel &lt;Name&gt; | `panel_<id>` | On an area: the whole room goes to that panel. On a device or entity: just that device, wherever it is installed. On a scene: the scene is shown on that panel (a scene without any Panel label is on every panel) |
| Panel &lt;Name&gt; WC | `panel_<id>_wc` | WC tab of a room panel — every room panel has it |
| Panel &lt;Name&gt; &lt;Room&gt; | `panel_<id>_<room>` | Tab of another attached room (Shower, Balcony…) |
| &lt;Room&gt; (e.g. Bedroom 1) | area id (`bedroom_1`) | Room label for each area of a panel: puts a device in that room on the panels (Home, Climate…) |

Example: panel **Bedroom 3** → Panel Bedroom 3 (`panel_bedroom_3`), Panel Bedroom 3 WC (`panel_bedroom_3_wc`), Panel Bedroom 3 Shower (`panel_bedroom_3_shower`).
