/**
 * Norman shades card.
 *
 * Every Norman blind, grouped by room, drawn as a window with its shade hanging in it. The
 * picture is the control: each rail has a pull tab, and dragging it moves that rail. A
 * two-rail (day/night) blind has two -- the middle rail between the two fabrics, and the
 * bottom rail -- and they stack and part the way the real rails do.
 *
 * Written as a plain custom element with no build step and no external dependencies, so the
 * file that ships is the file that runs. The picture is drawn in CSS with its geometry in
 * percent, so it follows the theme, stays crisp at any pixel density and scales with the card.
 *
 * Discovery is automatic: the card finds Norman cover entities through the entity registry
 * (via the hass object's `entities` map) and groups them by the area Home Assistant has each
 * device in, which the integration seeds from the hub's own room names. Nothing has to be
 * listed in the card configuration. With more than one hub, `config_entry_id` limits the card
 * to one of them and sends its presets and refreshes to that hub.
 *
 * The integration also shows this card full screen as a sidebar panel (norman-panel.js).
 * There it carries a `panel` attribute and a `narrow` property from Home Assistant: on phones
 * it runs edge to edge and its header gains the button that opens Home Assistant's sidebar.
 */

// The integration stamps its release version onto the resource URL as ?v= (the cache-bust),
// so the card reports exactly which build the browser actually loaded rather than a constant
// that can silently drift from manifest.json. "unknown" means the resource was added by hand
// without the stamp -- which is also the state a stale browser cache leaves behind.
const CARD_VERSION = new URL(import.meta.url).searchParams.get("v") || "unknown";

const DOMAIN = "norman";
const STEP = 10;

// The shade's geometry, as percentages of the window opening's height: the headrail's depth
// and each rail's thickness. The CSS tokens --n-head and --n-rail draw the same two numbers,
// so if they disagree the fabric detaches from its rails. Keep them equal.
const SHADE_HEAD_PCT = 9;
const SHADE_RAIL_PCT = 4.5;

// How long a position the user chose is drawn before the hub must have taken it up. Past this
// the card shows the hub's own values again, so a command the hub dropped is visible.
const PENDING_MS = 15000;
// How long a rail counts as moving once the hub reports a new target. A blind reports its new
// position when it stops, 10-45 s after a command, and the integration's watchdog gives a
// silent one three sends, 70 s apart (const.py: MOVE_TIMEOUT + MOVE_REPORT_WAIT, MOVE_ATTEMPTS).
// Past this the hub has not heard the blind arrive, and may not for hours: the blind missed the
// command, or carried it out and its report was lost. So the card stops saying "Closing" and
// says the move is not confirmed.
const MOVE_WINDOW_MS = 3 * (60 + 10) * 1000;
// Keyboard moves are gathered into one write: the hub drops commands sent closer together
// than about 1.6 s, so one write per key press would lose most of them.
const KEY_COMMIT_MS = 900;
// How far (px) a press must travel before it becomes a drag, so a tap never moves a blind.
const DRAG_SLOP = 4;

// Entities are identified by their translation key, which the entity registry sends to the
// frontend as `tk`. NOT by unique_id: the registry's display payload
// (EntityRegistryEntry._as_display_dict in homeassistant/helpers/entity_registry.py) carries
// only entity_id, platform, area/device/labels, icon, translation_key and a few flags --
// `unique_id` is never sent, so reading it yields undefined for every entity.
const KEY_BOTTOM_RAIL = "bottom_rail";
const KEY_MIDDLE_RAIL = "middle_rail";
// A Shutter's one cover: its louvers, driven through the cover's tilt.
const KEY_LOUVERS = "louvers";
const KEY_BOTTOM_POSITION = "bottom_rail_position";
const KEY_MIDDLE_POSITION = "middle_rail_position";
const KEY_BATTERY = "battery_level";
// A scene saved in one of the hub's rooms, on that room's device, listed with the room. A
// scene group sits on the hub's device and acts on several rooms, so it goes in the header
// with the whole-house presets instead.
const KEY_ROOM_SCENE = "room_scene";
const KEY_SCENE_GROUP = "scene_group";
// Home Assistant's own icon for a scene.
const SCENE_ICON = "mdi:palette";
// A blind's Request status button, found by its translation key like the KEY_* entities: it
// asks the blind to report in, and nothing moves. The hub's and rooms' Report battery levels
// buttons can close shades, so the card offers none of them.
const BUTTON_REQUEST_STATUS = "request_status";
const REFRESH_ICON = "mdi:refresh";
// A refresh control's icon turns once when pressed, to say the request went. The answers come
// later -- a blind's within seconds, a whole hub's over a couple of minutes -- and the card
// redraws as they arrive.
const REFRESH_SPIN_MS = 1000;
// A second press of the same refresh control within this long is ignored: each press queues
// status requests at the hub's pace, and repeats only push the answers back.
const REFRESH_HOLD_MS = 5000;
// Entities only the hub device carries, which is how the card tells the hub from the rest:
// each of the hub's rooms is a Norman device without a cover as well. Several, because the
// frontend registry leaves out disabled entities and any one of these can be disabled.
const HUB_KEYS = new Set([
  "mac_address",
  "time_zone",
  "wifi_ssid",
  "wifi_rssi",
  "pairing_mode",
  "refresh_blinds",
  "start_pairing",
]);

// The card's own words, in the integration's languages (custom_components/norman/translations).
// Home Assistant gives a custom card no translation catalogue, so they live here. The rail,
// preset and battery words match the entity names in those files, and the Japanese and Chinese
// follow the Norman app, as the entity names do. `{name}` is filled in by translate(); a key
// ending `_one` / `_other` is chosen by count. A language missing a key falls back to English.
const STRINGS = {
  en: {
    card_name: "Norman Shades",
    card_description: "Norman blinds grouped by room, each drawn as a window you drag to move.",
    heading_fallback: "Shades",
    unassigned: "Unassigned",
    empty: "No Norman blinds found. Set up the Norman integration, or check that its cover entities are not hidden.",
    open_sidebar: "Open the sidebar",
    preset_privacy: "Privacy",
    preset_privacy_title: "Best privacy",
    preset_view: "View",
    preset_view_title: "Best view",
    preset_favorite: "Favorite",
    preset_favorite_title: "Favorite",
    preset_every_room: "{preset} — every room",
    preset_in_room: "{preset} — {room}",
    room_presets: "Presets for {room}",
    room_open: "Open every blind in {room}",
    room_stop: "Stop every blind in {room}",
    room_close: "Close every blind in {room}",
    room_refresh: "Refresh every blind in {room}",
    room_more: "More for {room}",
    home_refresh: "Refresh every blind",
    refresh: "Refresh",
    refresh_blind: "Refresh {name}",
    blind_details: "{name} details",
    stop: "Stop",
    stop_blind: "Stop {name}",
    bottom_rail: "Bottom rail",
    middle_rail: "Middle rail",
    bottom_short: "Bottom",
    middle_short: "Middle",
    louvers: "Louvers",
    position: "Position",
    blind_rail: "{name} {rail}",
    blind_louvers: "{name} louvers",
    blind_left_half: "{name} left half",
    blind_right_half: "{name} right half",
    percent: "{value}%",
    percent_open: "{value}% open",
    unavailable: "Unavailable",
    position_unknown: "Position unknown",
    open: "Open",
    closed: "Closed",
    privacy: "Privacy",
    opening: "Opening · {value}%",
    closing: "Closing · {value}%",
    opening_rail: "Opening · {rail} {value}%",
    closing_rail: "Closing · {rail} {value}%",
    two_rails: "{middle_rail} {middle}% · {bottom_rail} {bottom}%",
    unconfirmed: "Not confirmed",
    shades_one: "{count} shade",
    shades_other: "{count} shades",
    all_closed: "all closed",
    one_open: "open",
    all_open: "all open",
    some_open_one: "{count} open",
    some_open_other: "{count} open",
    moving: "{count} moving",
    low_battery_one: "{count} low battery",
    low_battery_other: "{count} low batteries",
    battery: "Battery {value}",
    battery_unknown: "Battery level unknown",
    editor_title: "Title (leave empty to use the hub's name)",
    editor_hub: "Hub (only needed with more than one)",
    editor_hide_picture: "List layout (sliders instead of windows)",
    editor_hide_battery: "Hide battery levels",
    editor_hide_room_names: "Hide room headings",
    editor_hide_room_controls: "Hide room open / stop / close",
    editor_hide_room_presets: "Hide room presets and scenes",
    editor_hide_home_controls: "Hide whole-house presets and scene groups",
    editor_hide_refresh: "Hide refresh buttons",
  },
  de: {
    card_name: "Norman-Rollos",
    card_description: "Norman-Rollos nach Raum gruppiert, jedes als Fenster gezeichnet, das du zum Bewegen ziehst.",
    heading_fallback: "Rollos",
    unassigned: "Nicht zugeordnet",
    empty: "Keine Norman-Rollos gefunden. Richte die Norman-Integration ein oder prüfe, ob ihre Abdeckungs-Entitäten ausgeblendet sind.",
    open_sidebar: "Seitenleiste öffnen",
    preset_privacy: "Privatsphäre",
    preset_privacy_title: "Beste Privatsphäre",
    preset_view: "Aussicht",
    preset_view_title: "Beste Aussicht",
    preset_favorite: "Favorit",
    preset_favorite_title: "Favoritenposition",
    preset_every_room: "{preset} – alle Räume",
    preset_in_room: "{preset} – {room}",
    room_presets: "Voreinstellungen für {room}",
    room_open: "Alle Rollos in {room} öffnen",
    room_stop: "Alle Rollos in {room} stoppen",
    room_close: "Alle Rollos in {room} schließen",
    room_refresh: "Alle Rollos in {room} aktualisieren",
    room_more: "Mehr für {room}",
    home_refresh: "Alle Rollos aktualisieren",
    refresh: "Aktualisieren",
    refresh_blind: "{name} aktualisieren",
    blind_details: "Details zu {name}",
    stop: "Stopp",
    stop_blind: "{name} stoppen",
    bottom_rail: "Untere Schiene",
    middle_rail: "Mittlere Schiene",
    bottom_short: "Unten",
    middle_short: "Mitte",
    louvers: "Lamellen",
    position: "Position",
    blind_rail: "{name}, {rail}",
    blind_louvers: "{name}, Lamellen",
    blind_left_half: "{name}, linke Hälfte",
    blind_right_half: "{name}, rechte Hälfte",
    percent: "{value} %",
    percent_open: "{value} % offen",
    unavailable: "Nicht verfügbar",
    position_unknown: "Position unbekannt",
    open: "Offen",
    closed: "Geschlossen",
    privacy: "Privatsphäre",
    opening: "Öffnet · {value} %",
    closing: "Schließt · {value} %",
    opening_rail: "Öffnet · {rail} {value} %",
    closing_rail: "Schließt · {rail} {value} %",
    two_rails: "{middle_rail} {middle} % · {bottom_rail} {bottom} %",
    unconfirmed: "Nicht bestätigt",
    shades_one: "{count} Rollo",
    shades_other: "{count} Rollos",
    all_closed: "alle geschlossen",
    one_open: "offen",
    all_open: "alle offen",
    some_open_one: "{count} offen",
    some_open_other: "{count} offen",
    moving: "{count} in Bewegung",
    low_battery_one: "{count} Batterie schwach",
    low_battery_other: "{count} Batterien schwach",
    battery: "Batterie {value}",
    battery_unknown: "Batteriestand unbekannt",
    editor_title: "Titel (leer lassen, um den Namen des Hubs zu verwenden)",
    editor_hub: "Hub (nur bei mehr als einem nötig)",
    editor_hide_picture: "Listenansicht (Schieberegler statt Fenster)",
    editor_hide_battery: "Batteriestände ausblenden",
    editor_hide_room_names: "Raumüberschriften ausblenden",
    editor_hide_room_controls: "Öffnen / Stopp / Schließen der Räume ausblenden",
    editor_hide_room_presets: "Voreinstellungen und Szenen der Räume ausblenden",
    editor_hide_home_controls: "Voreinstellungen und Szenengruppen für das ganze Haus ausblenden",
    editor_hide_refresh: "Schaltflächen zum Aktualisieren ausblenden",
  },
  es: {
    card_name: "Persianas Norman",
    card_description: "Persianas Norman agrupadas por habitación, cada una dibujada como una ventana que arrastras para moverla.",
    heading_fallback: "Persianas",
    unassigned: "Sin asignar",
    empty: "No se encontraron persianas Norman. Configura la integración Norman o comprueba que sus entidades de cubierta no estén ocultas.",
    open_sidebar: "Abrir la barra lateral",
    preset_privacy: "Privacidad",
    preset_privacy_title: "Máxima privacidad",
    preset_view: "Vista",
    preset_view_title: "Mejor vista",
    preset_favorite: "Favorita",
    preset_favorite_title: "Posición favorita",
    preset_every_room: "{preset} — todas las habitaciones",
    preset_in_room: "{preset} — {room}",
    room_presets: "Preajustes de {room}",
    room_open: "Abrir todas las persianas de {room}",
    room_stop: "Detener todas las persianas de {room}",
    room_close: "Cerrar todas las persianas de {room}",
    room_refresh: "Actualizar todas las persianas de {room}",
    room_more: "Más opciones de {room}",
    home_refresh: "Actualizar todas las persianas",
    refresh: "Actualizar",
    refresh_blind: "Actualizar {name}",
    blind_details: "Detalles de {name}",
    stop: "Detener",
    stop_blind: "Detener {name}",
    bottom_rail: "Riel inferior",
    middle_rail: "Riel intermedio",
    bottom_short: "Inferior",
    middle_short: "Intermedio",
    louvers: "Lamas",
    position: "Posición",
    blind_rail: "{name}, {rail}",
    blind_louvers: "{name}, lamas",
    blind_left_half: "{name}, mitad izquierda",
    blind_right_half: "{name}, mitad derecha",
    percent: "{value}%",
    percent_open: "abierta al {value}%",
    unavailable: "No disponible",
    position_unknown: "Posición desconocida",
    open: "Abierta",
    closed: "Cerrada",
    privacy: "Privacidad",
    opening: "Abriendo · {value}%",
    closing: "Cerrando · {value}%",
    opening_rail: "Abriendo · {rail} {value}%",
    closing_rail: "Cerrando · {rail} {value}%",
    two_rails: "{middle_rail} {middle}% · {bottom_rail} {bottom}%",
    unconfirmed: "Sin confirmar",
    shades_one: "{count} persiana",
    shades_other: "{count} persianas",
    all_closed: "todas cerradas",
    one_open: "abierta",
    all_open: "todas abiertas",
    some_open_one: "{count} abierta",
    some_open_other: "{count} abiertas",
    moving: "{count} en movimiento",
    low_battery_one: "{count} con batería baja",
    low_battery_other: "{count} con batería baja",
    battery: "Batería {value}",
    battery_unknown: "Nivel de batería desconocido",
    editor_title: "Título (déjalo vacío para usar el nombre del hub)",
    editor_hub: "Hub (solo si hay más de uno)",
    editor_hide_picture: "Vista de lista (controles deslizantes en lugar de ventanas)",
    editor_hide_battery: "Ocultar los niveles de batería",
    editor_hide_room_names: "Ocultar los títulos de las habitaciones",
    editor_hide_room_controls: "Ocultar abrir / detener / cerrar de las habitaciones",
    editor_hide_room_presets: "Ocultar los preajustes y escenas de las habitaciones",
    editor_hide_home_controls: "Ocultar los preajustes y grupos de escenas de toda la casa",
    editor_hide_refresh: "Ocultar los botones de actualizar",
  },
  fr: {
    card_name: "Stores Norman",
    card_description: "Les stores Norman regroupés par pièce, chacun dessiné comme une fenêtre que l'on fait glisser pour le déplacer.",
    heading_fallback: "Stores",
    unassigned: "Non attribué",
    empty: "Aucun store Norman trouvé. Configurez l'intégration Norman ou vérifiez que ses entités de volet ne sont pas masquées.",
    open_sidebar: "Ouvrir la barre latérale",
    preset_privacy: "Intimité",
    preset_privacy_title: "Intimité maximale",
    preset_view: "Vue",
    preset_view_title: "Meilleure vue",
    preset_favorite: "Favori",
    preset_favorite_title: "Position favorite",
    preset_every_room: "{preset} — toutes les pièces",
    preset_in_room: "{preset} — {room}",
    room_presets: "Préréglages pour {room}",
    room_open: "Ouvrir tous les stores de {room}",
    room_stop: "Arrêter tous les stores de {room}",
    room_close: "Fermer tous les stores de {room}",
    room_refresh: "Actualiser tous les stores de {room}",
    room_more: "Plus d'options pour {room}",
    home_refresh: "Actualiser tous les stores",
    refresh: "Actualiser",
    refresh_blind: "Actualiser {name}",
    blind_details: "Détails de {name}",
    stop: "Arrêt",
    stop_blind: "Arrêter {name}",
    bottom_rail: "Rail inférieur",
    middle_rail: "Rail intermédiaire",
    bottom_short: "Bas",
    middle_short: "Milieu",
    louvers: "Lames",
    position: "Position",
    blind_rail: "{name}, {rail}",
    blind_louvers: "{name}, lames",
    blind_left_half: "{name}, moitié gauche",
    blind_right_half: "{name}, moitié droite",
    percent: "{value} %",
    percent_open: "ouvert à {value} %",
    unavailable: "Indisponible",
    position_unknown: "Position inconnue",
    open: "Ouvert",
    closed: "Fermé",
    privacy: "Intimité",
    opening: "Ouverture · {value} %",
    closing: "Fermeture · {value} %",
    opening_rail: "Ouverture · {rail} {value} %",
    closing_rail: "Fermeture · {rail} {value} %",
    two_rails: "{middle_rail} {middle} % · {bottom_rail} {bottom} %",
    unconfirmed: "Non confirmé",
    shades_one: "{count} store",
    shades_other: "{count} stores",
    all_closed: "tous fermés",
    one_open: "ouvert",
    all_open: "tous ouverts",
    some_open_one: "{count} ouvert",
    some_open_other: "{count} ouverts",
    moving: "{count} en mouvement",
    low_battery_one: "{count} batterie faible",
    low_battery_other: "{count} batteries faibles",
    battery: "Batterie {value}",
    battery_unknown: "Niveau de batterie inconnu",
    editor_title: "Titre (laisser vide pour utiliser le nom du hub)",
    editor_hub: "Hub (seulement s'il y en a plusieurs)",
    editor_hide_picture: "Affichage en liste (curseurs au lieu de fenêtres)",
    editor_hide_battery: "Masquer les niveaux de batterie",
    editor_hide_room_names: "Masquer les titres des pièces",
    editor_hide_room_controls: "Masquer ouvrir / arrêter / fermer des pièces",
    editor_hide_room_presets: "Masquer les préréglages et scènes des pièces",
    editor_hide_home_controls: "Masquer les préréglages et groupes de scènes de toute la maison",
    editor_hide_refresh: "Masquer les boutons d'actualisation",
  },
  ja: {
    card_name: "Norman ブラインド",
    card_description: "Norman のブラインドを部屋ごとにまとめ、それぞれを窓として表示します。ドラッグして動かせます。",
    heading_fallback: "ブラインド",
    unassigned: "未割り当て",
    empty: "Norman のブラインドが見つかりません。Norman インテグレーションを設定するか、カバーエンティティが非表示になっていないか確認してください。",
    open_sidebar: "サイドバーを開く",
    preset_privacy: "プライバシー",
    preset_privacy_title: "プライバシー重視",
    preset_view: "眺望",
    preset_view_title: "眺望重視",
    preset_favorite: "お気に入り",
    preset_favorite_title: "お気に入り位置",
    preset_every_room: "{preset} — すべての部屋",
    preset_in_room: "{preset} — {room}",
    room_presets: "{room}のプリセット",
    room_open: "{room}のブラインドをすべて開く",
    room_stop: "{room}のブラインドをすべて停止",
    room_close: "{room}のブラインドをすべて閉じる",
    room_refresh: "{room}のブラインドをすべて更新",
    room_more: "{room}のその他の操作",
    home_refresh: "すべてのブラインドを更新",
    refresh: "更新",
    refresh_blind: "{name}を更新",
    blind_details: "{name}の詳細",
    stop: "停止",
    stop_blind: "{name}を停止",
    bottom_rail: "ボトムレール",
    middle_rail: "ミッドレール",
    bottom_short: "ボトム",
    middle_short: "ミッド",
    louvers: "ルーバー",
    position: "位置",
    blind_rail: "{name} {rail}",
    blind_louvers: "{name} ルーバー",
    blind_left_half: "{name} 左半分",
    blind_right_half: "{name} 右半分",
    percent: "{value}%",
    percent_open: "開度 {value}%",
    unavailable: "利用不可",
    position_unknown: "位置不明",
    open: "全開",
    closed: "全閉",
    privacy: "プライバシー",
    opening: "開いています · {value}%",
    closing: "閉じています · {value}%",
    opening_rail: "開いています · {rail} {value}%",
    closing_rail: "閉じています · {rail} {value}%",
    two_rails: "{middle_rail} {middle}% · {bottom_rail} {bottom}%",
    unconfirmed: "未確認",
    shades_one: "ブラインド {count} 台",
    shades_other: "ブラインド {count} 台",
    all_closed: "すべて閉じています",
    one_open: "開いています",
    all_open: "すべて開いています",
    some_open_one: "{count} 台が開いています",
    some_open_other: "{count} 台が開いています",
    moving: "{count} 台が動作中",
    low_battery_one: "{count} 台がバッテリー残量低下",
    low_battery_other: "{count} 台がバッテリー残量低下",
    battery: "バッテリー {value}",
    battery_unknown: "バッテリー残量不明",
    editor_title: "タイトル（空欄の場合はハブの名前を使用）",
    editor_hub: "ハブ（複数ある場合のみ）",
    editor_hide_picture: "リスト表示（窓の代わりにスライダー）",
    editor_hide_battery: "バッテリー残量を非表示",
    editor_hide_room_names: "部屋の見出しを非表示",
    editor_hide_room_controls: "部屋の開く／停止／閉じるを非表示",
    editor_hide_room_presets: "部屋のプリセットとシーンを非表示",
    editor_hide_home_controls: "家全体のプリセットとシーングループを非表示",
    editor_hide_refresh: "更新ボタンを非表示",
  },
  "zh-Hans": {
    card_name: "Norman 窗帘",
    card_description: "按房间分组的 Norman 窗帘，每个都画成一扇窗户，拖动即可移动。",
    heading_fallback: "窗帘",
    unassigned: "未分配",
    empty: "未找到 Norman 窗帘。请设置 Norman 集成，或检查其窗帘实体是否被隐藏。",
    open_sidebar: "打开侧边栏",
    preset_privacy: "隐私",
    preset_privacy_title: "最佳隐私",
    preset_view: "视野",
    preset_view_title: "最佳视野",
    preset_favorite: "最爱",
    preset_favorite_title: "我的最爱位置",
    preset_every_room: "{preset} — 所有房间",
    preset_in_room: "{preset} — {room}",
    room_presets: "{room}的预设",
    room_open: "打开{room}的所有窗帘",
    room_stop: "停止{room}的所有窗帘",
    room_close: "关闭{room}的所有窗帘",
    room_refresh: "刷新{room}的所有窗帘",
    room_more: "{room}的更多操作",
    home_refresh: "刷新所有窗帘",
    refresh: "刷新",
    refresh_blind: "刷新{name}",
    blind_details: "{name}详情",
    stop: "停止",
    stop_blind: "停止{name}",
    bottom_rail: "下梁",
    middle_rail: "中梁",
    bottom_short: "下梁",
    middle_short: "中梁",
    louvers: "叶片",
    position: "位置",
    blind_rail: "{name} {rail}",
    blind_louvers: "{name} 叶片",
    blind_left_half: "{name} 左半边",
    blind_right_half: "{name} 右半边",
    percent: "{value}%",
    percent_open: "已打开 {value}%",
    unavailable: "不可用",
    position_unknown: "位置未知",
    open: "已打开",
    closed: "已关闭",
    privacy: "隐私",
    opening: "正在打开 · {value}%",
    closing: "正在关闭 · {value}%",
    opening_rail: "正在打开 · {rail} {value}%",
    closing_rail: "正在关闭 · {rail} {value}%",
    two_rails: "{middle_rail} {middle}% · {bottom_rail} {bottom}%",
    unconfirmed: "未确认",
    shades_one: "{count} 个窗帘",
    shades_other: "{count} 个窗帘",
    all_closed: "全部关闭",
    one_open: "已打开",
    all_open: "全部打开",
    some_open_one: "{count} 个已打开",
    some_open_other: "{count} 个已打开",
    moving: "{count} 个正在移动",
    low_battery_one: "{count} 个电量低",
    low_battery_other: "{count} 个电量低",
    battery: "电量 {value}",
    battery_unknown: "电量未知",
    editor_title: "标题（留空则使用网关名称）",
    editor_hub: "网关（仅在有多个时需要）",
    editor_hide_picture: "列表布局（用滑块代替窗户）",
    editor_hide_battery: "隐藏电量",
    editor_hide_room_names: "隐藏房间标题",
    editor_hide_room_controls: "隐藏房间的打开 / 停止 / 关闭",
    editor_hide_room_presets: "隐藏房间预设和场景",
    editor_hide_home_controls: "隐藏全屋预设和场景组",
    editor_hide_refresh: "隐藏刷新按钮",
  },
  "zh-Hant": {
    card_name: "Norman 窗簾",
    card_description: "依房間分組的 Norman 窗簾，每個都畫成一扇窗戶，拖曳即可移動。",
    heading_fallback: "窗簾",
    unassigned: "未指派",
    empty: "找不到 Norman 窗簾。請設定 Norman 整合，或檢查其窗簾實體是否已隱藏。",
    open_sidebar: "開啟側邊欄",
    preset_privacy: "隱私",
    preset_privacy_title: "最佳隱私",
    preset_view: "視野",
    preset_view_title: "最佳視野",
    preset_favorite: "最愛",
    preset_favorite_title: "我的最愛位置",
    preset_every_room: "{preset} — 所有房間",
    preset_in_room: "{preset} — {room}",
    room_presets: "{room}的預設",
    room_open: "開啟{room}的所有窗簾",
    room_stop: "停止{room}的所有窗簾",
    room_close: "關閉{room}的所有窗簾",
    room_refresh: "重新整理{room}的所有窗簾",
    room_more: "{room}的更多操作",
    home_refresh: "重新整理所有窗簾",
    refresh: "重新整理",
    refresh_blind: "重新整理{name}",
    blind_details: "{name}詳細資訊",
    stop: "停止",
    stop_blind: "停止{name}",
    bottom_rail: "下樑",
    middle_rail: "中樑",
    bottom_short: "下樑",
    middle_short: "中樑",
    louvers: "葉片",
    position: "位置",
    blind_rail: "{name} {rail}",
    blind_louvers: "{name} 葉片",
    blind_left_half: "{name} 左半邊",
    blind_right_half: "{name} 右半邊",
    percent: "{value}%",
    percent_open: "已開啟 {value}%",
    unavailable: "無法使用",
    position_unknown: "位置未知",
    open: "已開啟",
    closed: "已關閉",
    privacy: "隱私",
    opening: "正在開啟 · {value}%",
    closing: "正在關閉 · {value}%",
    opening_rail: "正在開啟 · {rail} {value}%",
    closing_rail: "正在關閉 · {rail} {value}%",
    two_rails: "{middle_rail} {middle}% · {bottom_rail} {bottom}%",
    unconfirmed: "未確認",
    shades_one: "{count} 個窗簾",
    shades_other: "{count} 個窗簾",
    all_closed: "全部關閉",
    one_open: "已開啟",
    all_open: "全部開啟",
    some_open_one: "{count} 個已開啟",
    some_open_other: "{count} 個已開啟",
    moving: "{count} 個正在移動",
    low_battery_one: "{count} 個電量低",
    low_battery_other: "{count} 個電量低",
    battery: "電量 {value}",
    battery_unknown: "電量未知",
    editor_title: "標題（留空則使用集線器名稱）",
    editor_hub: "集線器（僅在有多個時需要）",
    editor_hide_picture: "清單版面（以滑桿取代窗戶）",
    editor_hide_battery: "隱藏電量",
    editor_hide_room_names: "隱藏房間標題",
    editor_hide_room_controls: "隱藏房間的開啟 / 停止 / 關閉",
    editor_hide_room_presets: "隱藏房間預設和場景",
    editor_hide_home_controls: "隱藏全屋預設和場景群組",
    editor_hide_refresh: "隱藏重新整理按鈕",
  },
};

/**
 * Which of STRINGS to use: the user's language in Home Assistant (their profile setting),
 * else the page's, else English. A regional variant uses its base language ("de-CH" is "de",
 * "en-GB" is "en"), and Chinese picks its script from the tag ("zh-TW" and "zh-HK" are
 * Traditional, anything else Simplified).
 */
const languageOf = (hass) => {
  const wanted = String(
    hass?.locale?.language || hass?.language || globalThis.document?.documentElement?.lang || "en",
  );
  if (STRINGS[wanted]) return wanted;
  const [base, ...rest] = wanted.split(/[-_]/);
  if (base.toLowerCase() === "zh") {
    return rest.some((part) => /^(hant|tw|hk|mo)$/i.test(part)) ? "zh-Hant" : "zh-Hans";
  }
  return STRINGS[base.toLowerCase()] ? base.toLowerCase() : "en";
};

/** A string in `language`, with its `{placeholders}` filled from `vars`. */
const translate = (language, key, vars = {}) => {
  const strings = STRINGS[language] || STRINGS.en;
  let text = strings[key] ?? STRINGS.en[key];
  if (text === undefined) {
    // A counted key: the language's plural category for the count, "one" or "other".
    const category = new Intl.PluralRules(language).select(Number(vars.count)) === "one" ? "one" : "other";
    text = strings[`${key}_${category}`] ?? STRINGS.en[`${key}_${category}`] ?? key;
  }
  return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? ""));
};

// The Norman app's three presets. The short label is what is printed; the title is the full
// name, used for the tooltip and for assistive technology. Both are keys into STRINGS.
const PRESETS = [
  { command: "best_privacy", icon: "mdi:blinds-horizontal", label: "preset_privacy", title: "preset_privacy_title" },
  { command: "best_view", icon: "mdi:weather-sunny", label: "preset_view", title: "preset_view_title" },
  { command: "favorite", icon: "mdi:star", label: "preset_favorite", title: "preset_favorite_title" },
];

// A room's open / stop / close: the icon, the cover service, and the tooltip's STRINGS key.
const ROOM_ACTIONS = [
  ["mdi:arrow-up", "open_cover", "room_open"],
  ["mdi:stop", "stop_cover", "room_stop"],
  ["mdi:arrow-down", "close_cover", "room_close"],
];

const clamp = (value, low = 0, high = 100) => Math.max(low, Math.min(high, value));
const clampToStep = (value, step = STEP) => Math.round(clamp(Number(value) || 0) / step) * step;
// The config entries a device belongs to. Newer Home Assistant versions name one
// (`config_entry_id`); older ones list them (`config_entries`).
const entriesOf = (device) =>
  device?.config_entry_id ? [device.config_entry_id] : device?.config_entries || [];
// A Shutter's louvers open in five steps (closed, a quarter ... fully open), so they move in 25s.
const LOUVER_STEP = 25;
const LOUVER_COUNT = 9;
// How far the louvers turn at fully open: nearly edge-on, as a real louver stops short.
const LOUVER_OPEN_DEG = 78;
// The part of the opening a drag has to cover to take the louvers from closed to open.
const LOUVER_TRAVEL_PCT = 70;
// Below this raw Position the hub reports the louvers turned the other way (the app's 0-2).
const LOUVER_HORIZONTAL = 3;
const stepOf = (rail) => (rail.louvers ? LOUVER_STEP : STEP);

// A roller shade's fabric winds onto a roll at the top: thickest with the shade up, thinnest
// with it down. In percent of the opening's height. Fully up, the roll's underside is where a
// cellular shade's headrail ends, so the bottom bar tucks beneath it the same way.
const ROLL_TOP_PCT = 0.5;
const ROLL_MIN_PCT = 4;
const ROLL_MAX_PCT = SHADE_HEAD_PCT - ROLL_TOP_PCT;

// A SmartDrape: fabric vanes on a sheer, hung from a track and drawn across the window
// sideways. Widths are percent of the opening's width.
const DRAPE_VANES = 14; // across the whole window; a split drape has half on each side
const DRAPE_STACK_PCT = 16; // how much of the window the drape covers gathered to one side
const DRAPE_TRACK_PCT = 4.5; // the track's depth, in percent of the opening's height
const DRAPE_VANE_OVERLAP = 1.15; // a vane's width over its share of the closed drape
// How far the vanes turn at fully open: nearly edge-on to the window, as the real ones stop.
const VANE_OPEN_DEG = 75;
// The sides a drape gathers to when open, by the cover's `stack` attribute.
const STACK_SIDES = { left: ["left"], right: ["right"], split: ["left", "right"] };

// A Roman shade (flat fold, batten back): one flat panel with a seam at each batten, which
// folds up from the bottom as the shade rises. The folds hang loose, half a section deep,
// until every section is folded, then pack tighter as the shade goes the rest of the way up.
// The CSS draws the seams at the same count. In percent of the opening's height.
const ROMAN_SECTIONS = 5;
const ROMAN_STACK_PCT = 24; // the folds' depth with the shade fully up
const ROMAN_LAP_PCT = 0.6; // how far the flat panel runs on under the top fold, so no sky shows at the join

// A PerfectSheer: soft fabric vanes between two sheers, rolled up into a cassette. With the
// shade fully down the vanes open, each to a band this much of its pitch; raised, they are
// closed, as the shade closes them before it rolls up.
const SHEER_VANES = 11;
const SHEER_VANE_OPEN = 0.42;

// Which picture a blind gets, from its device's model_id: the hub's ModuleType/ModuleDetail
// ("48/1"), as the integration records it. The roller family (48 and 49) is a roller shade,
// a Roman shade (detail 2) or a PerfectSheer (detail 3), and a SmartDrape is 80; each is
// drawn as itself. Anything else is drawn as a cellular shade.
const ROLLER_FAMILY = { 2: "roman", 3: "perfectsheer" };
const productOf = (device) => {
  const [type, detail] = String(device?.model_id ?? "").split("/").map(Number);
  if (type === 80) return "drape";
  if (type === 48 || type === 49) return ROLLER_FAMILY[detail] || "roller";
  return null;
};
const round3 = (value) => Math.round(value * 1000) / 1000;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// Write a node's text or an attribute only when it changes. The card patches every tile on
// each change to one of its entities, and a write of the same text still costs the browser a
// fresh layout of the tile.
const setText = (node, text) => {
  if (node.textContent !== text) node.textContent = text;
};
const setAttr = (node, name, value) => {
  if (node.getAttribute(name) !== value) node.setAttribute(name, value);
};

const haIcon = (name) => {
  const node = document.createElement("ha-icon");
  node.setAttribute("icon", name);
  return node;
};

const batteryIcon = (level) => {
  if (level === null || level === undefined || Number.isNaN(level)) return "mdi:battery-unknown";
  const rounded = Math.round(level / 10) * 10;
  if (rounded >= 100) return "mdi:battery";
  if (rounded <= 0) return "mdi:battery-outline";
  return `mdi:battery-${rounded}`;
};

const batteryClass = (level) => {
  if (level === null || level === undefined || Number.isNaN(level)) return "unknown";
  if (level <= 15) return "critical";
  if (level <= 30) return "low";
  return "ok";
};

// The view through the window follows the sun, so the picture reads like the real window.
const skyOf = (sun) => {
  if (!sun) return "day";
  const elevation = Number(sun.attributes?.elevation);
  if (Number.isNaN(elevation)) return sun.state === "below_horizon" ? "night" : "day";
  if (elevation > 8) return "day";
  if (elevation > 0) return "golden";
  if (elevation > -6) return "dusk";
  return "night";
};

const STYLES = `
  :host {
    --n-fg-rgb: var(--rgb-primary-text-color, 33, 33, 33);
    --n-accent: var(--primary-color, #03a9f4);
    --n-accent-rgb: var(--rgb-primary-color, 3, 169, 244);
    --n-muted: var(--secondary-text-color, #6f7378);
    --n-tile: 112px;
    /* Shade geometry, in percent of the window opening. SHADE_HEAD_PCT and SHADE_RAIL_PCT
       in the script are the same numbers. */
    --n-head: 9%;
    --n-rail: 4.5%;
    --n-pleat: 6px;
    --n-ease: cubic-bezier(0.2, 0.7, 0.2, 1);
    display: block;
  }
  [hidden] { display: none !important; }

  /* The illustration's palette: painted trim, aluminium rails, a see-through light-filtering
     fabric and an ivory cloth for everything else -- a single-rail shade and a two-rail
     shade's blackout alike. Dark themes dim the trim so the window does not glare. */
  ha-card {
    --n-trim: #f3f0ea;
    --n-trim-hi: #fdfcfa;
    --n-trim-lo: #dcd6cc;
    --n-trim-edge: rgba(92, 78, 58, 0.22);
    --n-rail-hi: #ffffff;
    --n-rail-face: #eeebe5;
    --n-rail-lo: #cbc5ba;
    --n-rail-edge: rgba(70, 60, 45, 0.35);
    --n-sheer-hi: rgba(255, 253, 248, 0.5);
    --n-sheer: rgba(248, 244, 236, 0.4);
    --n-sheer-lo: rgba(232, 225, 212, 0.52);
    --n-sheer-crease: rgba(176, 164, 144, 0.7);
    --n-cloth-hi: #fbf9f4;
    --n-cloth: #f0ebe2;
    --n-cloth-lo: #ddd5c7;
    --n-cloth-crease: #bdb2a0;
    container-type: inline-size;
    padding: 16px 16px 18px;
    overflow: visible;
  }
  /* In the sidebar panel on a phone the card is the page: edge to edge, with no frame. */
  :host([panel][narrow]) ha-card { border: none; border-radius: 0; box-shadow: none; }
  ha-card[data-theme="dark"] {
    --n-trim: #45484d;
    --n-trim-hi: #53575c;
    --n-trim-lo: #34373b;
    --n-trim-edge: rgba(0, 0, 0, 0.45);
    --n-rail-hi: #f2f0ec;
    --n-rail-face: #d9d5ce;
    --n-rail-lo: #aba497;
    --n-cloth-hi: #e6e1d8;
    --n-cloth: #d6cfc3;
    --n-cloth-lo: #c0b7a8;
    --n-cloth-crease: #a39886;
  }

  /* ---- header ---------------------------------------------------------------------- */
  .header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px 16px;
  }
  .titles { flex: 1 1 160px; min-width: 0; }
  .header-text {
    font-size: var(--ha-card-header-font-size, 20px);
    font-weight: var(--ha-card-header-font-weight, 500);
    line-height: 1.25;
    color: var(--ha-card-header-color, var(--primary-text-color));
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .summary {
    margin-top: 2px;
    font-size: 13px;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
  }
  .summary > span:not(.sep) { white-space: nowrap; }
  .summary .warn { color: var(--warning-color, #e39700); }
  .summary .live { color: var(--n-accent); }

  /* The app's presets, as one segmented control rather than three loose buttons. */
  .segmented {
    display: inline-flex;
    flex: none;
    gap: 2px;
    padding: 3px;
    border-radius: 12px;
    background: rgba(var(--n-fg-rgb), 0.06);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 12px 0 10px;
    border: 0;
    border-radius: 9px;
    background: transparent;
    color: var(--primary-text-color);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    line-height: 1;
    white-space: nowrap;
    cursor: pointer;
    transition: background-color 0.15s, box-shadow 0.15s, color 0.15s;
  }
  .chip ha-icon { --mdc-icon-size: 17px; color: var(--n-muted); transition: color 0.15s; }
  .chip:hover {
    background: var(--card-background-color, #fff);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.14), 0 0 0 0.5px rgba(0, 0, 0, 0.06);
  }
  .chip:hover ha-icon, .chip.sent ha-icon, .chip.sent { color: var(--n-accent); }
  .chip:active { transform: scale(0.97); }
  .chip:focus-visible, .icon-btn:focus-visible, .name:focus-visible, .stop:focus-visible, .refresh:focus-visible {
    outline: 2px solid var(--n-accent);
    outline-offset: 1px;
  }
  @container (max-width: 400px) {
    .home-buttons .chip span { display: none; }
    .home-buttons .chip { padding: 0 10px; }
  }

  /* ---- rooms ----------------------------------------------------------------------- */
  .room { margin-top: 22px; }
  .room:first-child { margin-top: 18px; }
  .room-head {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 34px;
    margin-bottom: 12px;
  }
  .room-name {
    flex: 1;
    min-width: 0;
    font-size: 15px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .icon-group {
    display: inline-flex;
    flex: none;
    border-radius: 10px;
    background: rgba(var(--n-fg-rgb), 0.05);
  }
  .icon-btn {
    display: grid;
    place-items: center;
    width: 34px;
    height: 32px;
    padding: 0;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--primary-text-color);
    cursor: pointer;
    transition: background-color 0.15s, color 0.15s;
  }
  .icon-btn ha-icon { --mdc-icon-size: 18px; }
  .icon-btn:hover { background: rgba(var(--n-fg-rgb), 0.08); }
  .icon-btn:active { transform: scale(0.94); }
  .icon-btn.more { flex: none; }
  .icon-btn.more.open { background: rgba(var(--n-accent-rgb), 0.14); color: var(--n-accent); }
  .icon-btn.menu { flex: none; margin: 0 -6px 0 -8px; }
  .icon-btn.menu ha-icon { --mdc-icon-size: 24px; }
  .tray { display: flex; flex-wrap: wrap; gap: 8px; margin: -4px 0 14px; }
  .tray .segmented { display: flex; width: fit-content; max-width: 100%; }
  /* A room's scenes after its presets, and the hub's scene groups after the whole-house
     presets: as many as the app has, so they wrap. The groups keep their words on a narrow
     card, where the presets beside them shrink to icons, since one palette looks like
     another. */
  .room-scenes, .home-scenes { flex-wrap: wrap; max-width: 100%; }
  .room-scenes .chip, .home-scenes .chip { max-width: 100%; }
  .room-scenes .chip span, .home-scenes .chip span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chip:disabled { opacity: 0.45; cursor: default; pointer-events: none; }

  /* ---- a blind: the window, then its name and state --------------------------------- */
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(var(--n-tile), 1fr));
    gap: 20px 14px;
  }
  .tile { position: relative; min-width: 0; }
  .meta { margin-top: 9px; padding: 0 1px; }
  .name {
    display: block;
    width: 100%;
    padding: 0;
    border: 0;
    background: none;
    color: var(--primary-text-color);
    font: inherit;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.3;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: pointer;
  }
  .name:hover { text-decoration: underline; text-underline-offset: 2px; }
  .battery {
    display: inline-flex;
    align-items: center;
    flex: none;
    margin: 1px 0 0 auto;
    line-height: 16px;
    font-size: 11.5px;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
  }
  .battery ha-icon { --mdc-icon-size: 15px; }
  .battery span:empty { display: none; }
  .battery.low { color: var(--warning-color, #e39700); }
  .battery.critical { color: var(--error-color, #db4437); }
  /* Refresh: beside the battery on every blind, in each room's tray and in the header. A press
     turns its icon once (REFRESH_SPIN_MS in the script is the same second). */
  .refresh {
    position: relative;
    display: grid;
    place-items: center;
    flex: none;
    width: 20px;
    height: 18px;
    margin-right: -3px;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: none;
    color: var(--n-muted);
    cursor: pointer;
  }
  /* A finger gets a wider target than the icon, without the row growing. */
  .refresh::after { content: ""; position: absolute; inset: -6px -4px; }
  .refresh ha-icon { --mdc-icon-size: 15px; }
  .refresh:hover { color: var(--n-accent); }
  .refresh:disabled { opacity: 0.45; cursor: default; }
  .spin ha-icon { color: var(--n-accent); animation: n-spin 1s var(--n-ease); }
  @keyframes n-spin { to { transform: rotate(360deg); } }
  .home-refresh { border-radius: 12px; background: rgba(var(--n-fg-rgb), 0.06); }
  .home-refresh .icon-btn { width: 36px; height: 36px; border-radius: 12px; }
  .meta-bottom { display: flex; align-items: flex-start; gap: 6px; min-height: 18px; }
  .status {
    flex: 1;
    min-width: 0;
    margin-top: 1px;
    font-size: 12.5px;
    line-height: 1.35;
    color: var(--n-muted);
    font-variant-numeric: tabular-nums;
    /* A two-rail blind's "Middle 70% · Bottom 30%" wraps between the rails, never inside one. */
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    overflow: hidden;
  }
  .status.moving { color: var(--n-accent); }

  /* Stop, while a blind is travelling: on the window's corner in the grid, inline in the list. */
  .stop {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
    flex: none;
    padding: 0;
    border: 0;
    color: var(--n-accent);
    font: inherit;
    font-size: 11.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .stop ha-icon { --mdc-icon-size: 16px; }
  .tile > .stop {
    position: absolute;
    top: -6px;
    right: -2px;
    z-index: 8;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background: var(--card-background-color, #fff);
    box-shadow: 0 0 0 1.5px rgba(var(--n-accent-rgb), 0.5), 0 2px 6px rgba(0, 0, 0, 0.25);
    animation: n-pop 0.2s var(--n-ease);
  }
  .tile > .stop span { display: none; }
  .tile > .stop:hover { background: var(--n-accent); color: var(--text-primary-color, #fff); }
  .row .stop {
    height: 22px;
    padding: 0 8px 0 5px;
    border-radius: 11px;
    background: rgba(var(--n-accent-rgb), 0.14);
  }
  .row .stop ha-icon { --mdc-icon-size: 14px; }
  @keyframes n-pop { from { transform: scale(0.4); opacity: 0; } }
  .tile.unavailable .win { filter: grayscale(1); opacity: 0.45; }

  /* ---- the window -------------------------------------------------------------------
     A painted casing and sill around a recessed opening. Everything that moves is placed
     in percent of .opening, so the picture scales with the tile. */
  .win {
    position: relative;
    aspect-ratio: 5 / 6;
    cursor: grab;
    touch-action: pan-y;
    -webkit-user-select: none;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
  }
  .win.dragging { cursor: grabbing; }
  .win.disabled { cursor: default; }
  .frame {
    position: absolute;
    left: 4%;
    right: 4%;
    top: 0;
    bottom: 5%;
    border-radius: 3px;
    background: linear-gradient(to bottom, var(--n-trim-hi), var(--n-trim) 10%, var(--n-trim) 85%, var(--n-trim-lo));
    box-shadow: 0 0 0 1px var(--n-trim-edge), 0 8px 18px -10px rgba(40, 30, 20, 0.45);
  }
  .sill {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 7%;
    border-radius: 2px;
    background: linear-gradient(to bottom, var(--n-trim-hi), var(--n-trim) 35%, var(--n-trim-lo));
    box-shadow: 0 0 0 1px var(--n-trim-edge), 0 5px 8px -5px rgba(40, 30, 20, 0.45);
  }
  .opening {
    position: absolute;
    top: 7%;
    bottom: 5%;
    left: 8.5%;
    right: 8.5%;
  }

  /* The view: sky that follows the sun, a line of hills, the glazing bars and a glint. */
  .view {
    position: absolute;
    inset: 0;
    overflow: hidden;
    background: linear-gradient(to bottom, #6ea6da, #a6cbee 55%, #d9eaf6);
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.2), inset 0 3px 6px rgba(0, 0, 0, 0.25);
  }
  .sun {
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at 76% 30%, rgba(255, 251, 235, 0.95) 0 5%, rgba(255, 244, 214, 0.45) 11%, transparent 32%);
  }
  .hills {
    position: absolute;
    left: -10%;
    right: -10%;
    bottom: 0;
    height: 30%;
    background:
      radial-gradient(70% 100% at 22% 100%, #8fb09a 0 60%, transparent 61%),
      radial-gradient(80% 85% at 82% 100%, #a9c4ae 0 60%, transparent 61%);
  }
  .mullion, .transom {
    position: absolute;
    background: var(--n-trim);
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 0 1px 2px rgba(0, 0, 0, 0.18);
  }
  .mullion { top: 0; bottom: 0; left: 50%; width: 3.2%; transform: translateX(-50%); }
  .transom { left: 0; right: 0; top: 48%; height: 2.8%; }
  .glint {
    position: absolute;
    inset: 0;
    background: linear-gradient(118deg, transparent 0 30%, rgba(255, 255, 255, 0.22) 30% 38%, transparent 38% 44%, rgba(255, 255, 255, 0.12) 44% 47%, transparent 47%);
  }
  ha-card[data-sky="golden"] .view { background: linear-gradient(to bottom, #7f9fd4, #e8b48d 62%, #f6d7ae); }
  ha-card[data-sky="golden"] .sun { background: radial-gradient(circle at 70% 62%, rgba(255, 236, 196, 0.95) 0 6%, rgba(255, 206, 150, 0.45) 14%, transparent 38%); }
  ha-card[data-sky="golden"] .hills { filter: saturate(0.6) brightness(0.8); }
  ha-card[data-sky="dusk"] .view { background: linear-gradient(to bottom, #26325b, #6b5b88 58%, #d38e77); }
  ha-card[data-sky="dusk"] .sun { background: none; }
  ha-card[data-sky="dusk"] .hills { filter: brightness(0.38) saturate(0.5) hue-rotate(40deg); }
  ha-card[data-sky="night"] .view { background: linear-gradient(to bottom, #0b1224, #16223f 60%, #243559); }
  ha-card[data-sky="night"] .sun {
    background:
      radial-gradient(circle at 72% 24%, #f4f1e4 0 3.2%, rgba(244, 241, 228, 0.25) 5%, transparent 12%),
      radial-gradient(circle at 18% 16%, #fff 0 0.5%, transparent 0.9%),
      radial-gradient(circle at 36% 34%, #fff 0 0.4%, transparent 0.8%),
      radial-gradient(circle at 58% 12%, #fff 0 0.35%, transparent 0.7%),
      radial-gradient(circle at 88% 44%, #fff 0 0.4%, transparent 0.8%),
      radial-gradient(circle at 12% 46%, #fff 0 0.3%, transparent 0.7%);
  }
  ha-card[data-sky="night"] .hills { filter: brightness(0.22) saturate(0.4); }
  ha-card[data-sky="night"] .glint { opacity: 0.4; }

  /* Fabric: cellular (honeycomb) pleats. Each cell is a crease, a shadowed lip, a lit
     face and a darker belly, repeated up from the rail so the pleats travel with it. */
  .fabric {
    position: absolute;
    left: 0;
    right: 0;
    top: var(--n-head);
    height: 0;
    z-index: 1;
    transition: top 0.45s var(--n-ease), height 0.45s var(--n-ease);
  }
  /* The pleat, bottom to top: the glued fold, the shadowed underside of the cell, its lit
     face, and a little shade where the cell above overhangs it. */
  .fabric.sheer, .fabric.single, .fabric.blackout {
    background:
      linear-gradient(to right, var(--n-side), transparent 9%, transparent 91%, var(--n-side)),
      repeating-linear-gradient(
        to top,
        var(--n-crease) 0,
        var(--n-crease) 1px,
        var(--n-lo) 1px,
        var(--n-lo) calc(var(--n-pleat) * 0.3),
        var(--n-hi) calc(var(--n-pleat) * 0.68),
        var(--n-mid) calc(var(--n-pleat) * 0.92),
        var(--n-lo) var(--n-pleat)
      );
  }
  .fabric.single, .fabric.blackout {
    --n-side: rgba(90, 70, 40, 0.1);
    --n-crease: var(--n-cloth-crease);
    --n-lo: var(--n-cloth-lo);
    --n-mid: var(--n-cloth);
    --n-hi: var(--n-cloth-hi);
  }
  /* The light-filtering fabric is see-through: the view -- sky, hills, glazing bars --
     shows through it softened, bright by day and dark at night, as it does in the room. */
  .fabric.sheer {
    --n-side: rgba(90, 70, 40, 0.08);
    --n-crease: var(--n-sheer-crease);
    --n-lo: var(--n-sheer-lo);
    --n-mid: var(--n-sheer);
    --n-hi: var(--n-sheer-hi);
    background-color: rgba(252, 249, 243, 0.14);
    -webkit-backdrop-filter: blur(1.2px) brightness(1.06) saturate(0.85);
    backdrop-filter: blur(1.2px) brightness(1.06) saturate(0.85);
  }
  .fabric.single::after, .fabric.blackout::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(90% 70% at 70% 30%, rgba(255, 250, 235, 0.55), transparent 70%);
    mix-blend-mode: soft-light;
  }
  ha-card[data-sky="night"] .fabric.single::after,
  ha-card[data-sky="night"] .fabric.blackout::after,
  ha-card[data-sky="dusk"] .fabric.single::after,
  ha-card[data-sky="dusk"] .fabric.blackout::after { display: none; }
  ha-card[data-theme="dark"] .fabric,
  ha-card[data-theme="dark"] .rail,
  ha-card[data-theme="dark"] .headrail,
  ha-card[data-theme="dark"] .roll,
  ha-card[data-theme="dark"] .hanging { filter: brightness(0.88); }

  /* Rails and the headrail: extruded aluminium, lit from above. */
  .rail, .headrail {
    position: absolute;
    background: linear-gradient(to bottom, var(--n-rail-hi), var(--n-rail-face) 40%, var(--n-rail-lo));
  }
  .rail {
    left: 0;
    right: 0;
    top: var(--n-head);
    height: var(--n-rail);
    min-height: 4px;
    z-index: 3;
    border-radius: 1px;
    box-shadow: 0 0 0 0.5px var(--n-rail-edge), 0 2px 3px -1px rgba(0, 0, 0, 0.4);
    transition: top 0.45s var(--n-ease);
  }
  .rail.middle { z-index: 4; }
  .win.stacked .rail.middle .tab { height: calc(100% + 7px); }
  .headrail {
    left: -3%;
    right: -3%;
    top: 0;
    height: var(--n-head);
    z-index: 5;
    border-radius: 2px 2px 1px 1px;
    background: linear-gradient(to bottom, var(--n-rail-hi), var(--n-rail-face) 30%, var(--n-rail-face) 62%, var(--n-rail-lo));
    box-shadow: 0 0 0 0.5px var(--n-rail-edge), 0 3px 5px -2px rgba(0, 0, 0, 0.45);
  }

  /* The pull tab: what a hand reaches for on a cordless shade, and what the card drags. */
  .tab {
    position: absolute;
    left: 50%;
    top: 100%;
    width: 26%;
    min-width: 20px;
    max-width: 38px;
    height: 7px;
    transform: translateX(-50%);
    border-radius: 0 0 5px 5px;
    background: linear-gradient(to bottom, var(--n-rail-face), var(--n-rail-lo));
    box-shadow: 0 0 0 0.5px var(--n-rail-edge), 0 2px 3px -1px rgba(0, 0, 0, 0.4);
    transition: background-color 0.15s, height 0.15s, box-shadow 0.15s;
  }
  .rail.hot .tab, .rail.held .tab {
    height: 9px;
    background: var(--n-accent);
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.25), 0 2px 8px rgba(var(--n-accent-rgb), 0.55);
  }
  .rail.moving:not(.held) .tab { animation: n-pulse 1.6s ease-in-out infinite; }
  @keyframes n-pulse {
    50% { background: var(--n-accent); box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.25), 0 1px 6px rgba(var(--n-accent-rgb), 0.5); }
  }

  /* Where a rail actually is while it travels to where it was sent. */
  .marker {
    position: absolute;
    left: 0;
    right: 0;
    height: 0;
    z-index: 2;
    border-top: 2px dashed var(--n-accent);
    transform: translateY(-1px);
    opacity: 0;
    transition: opacity 0.25s, top 0.8s linear;
    filter: drop-shadow(0 0 1px rgba(255, 255, 255, 0.9));
    pointer-events: none;
  }
  .marker.on { opacity: 0.95; }

  /* Grab zones: a band around each rail, the only place a touch starts a drag. Everywhere
     else on the picture a finger scrolls the page, so swiping past cannot move a blind. */
  .zone {
    position: absolute;
    left: -8%;
    right: -8%;
    height: 34px;
    z-index: 6;
    border-radius: 8px;
    transform: translateY(-50%);
    touch-action: none;
    outline: none;
    transition: top 0.45s var(--n-ease);
  }
  .zone:focus-visible { box-shadow: 0 0 0 2px var(--n-accent); }
  .win.dragging .fabric, .win.dragging .rail, .win.dragging .zone { transition: none; }
  .win.disabled .zone { touch-action: pan-y; }

  .bubble {
    position: absolute;
    left: 50%;
    z-index: 7;
    padding: 3px 8px;
    border-radius: 11px;
    background: rgba(24, 26, 30, 0.86);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    transform: translate(-50%, calc(-100% - 10px));
    opacity: 0;
    transition: opacity 0.15s;
    pointer-events: none;
  }
  .bubble.on { opacity: 1; }

  /* ---- a roller shade ---------------------------------------------------------------
     Plain woven fabric off a roll at the top: no pleats, and the roll grows as the shade
     winds up onto it. The bottom bar is the shade's weighted hem. */
  .win.roller .roll {
    position: absolute;
    left: -1.5%;
    right: -1.5%;
    top: 0.5%;
    height: 8.5%;
    z-index: 5;
    border-radius: 999px;
    background: linear-gradient(to bottom, var(--n-cloth-lo), var(--n-cloth-hi) 24%, var(--n-cloth) 52%, var(--n-cloth-lo) 80%, var(--n-cloth-crease));
    box-shadow: 0 0 0 0.5px rgba(90, 70, 40, 0.3), 0 2px 3px -1px rgba(0, 0, 0, 0.35);
    transition: height 0.45s var(--n-ease);
  }
  .win.roller .jamb {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    z-index: 4;
    background: linear-gradient(to bottom, var(--n-trim-lo), var(--n-trim));
    transition: height 0.45s var(--n-ease);
  }
  /* The brackets the roll turns in, at each end. */
  .win.roller .bracket {
    position: absolute;
    top: 0;
    height: var(--n-head);
    width: 4%;
    min-width: 3px;
    z-index: 6;
    border-radius: 1px;
    background: linear-gradient(to right, var(--n-rail-lo), var(--n-rail-hi) 45%, var(--n-rail-lo));
    box-shadow: 0 0 0 0.5px var(--n-rail-edge);
  }
  .win.roller .bracket.left { left: -3.5%; }
  .win.roller .bracket.right { right: -3.5%; }
  /* A fine weave in both directions over a soft fall of light, and the roll's shadow at the top. */
  .fabric.roller {
    background:
      linear-gradient(to right, rgba(90, 70, 40, 0.1), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.1)),
      linear-gradient(to bottom, rgba(60, 45, 25, 0.18), transparent 6%),
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.045) 0 0.5px, transparent 0.5px 1.5px),
      repeating-linear-gradient(to right, rgba(140, 120, 90, 0.03) 0 0.5px, transparent 0.5px 2px),
      linear-gradient(to bottom, var(--n-cloth-hi), var(--n-cloth) 55%, var(--n-cloth-lo));
  }
  .fabric.roller::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(90% 70% at 70% 30%, rgba(255, 250, 235, 0.55), transparent 70%);
    mix-blend-mode: soft-light;
  }
  ha-card[data-sky="night"] .fabric.roller::after,
  ha-card[data-sky="dusk"] .fabric.roller::after { display: none; }
  .win.roller .rail { border-radius: 2px; }
  .win.dragging .roll, .win.dragging .jamb { transition: none; }

  /* ---- a Roman shade ----------------------------------------------------------------
     Norman's flat fold with a batten back: a woven panel under a fabric-covered head, with
     a seam at each batten. It folds up from the bottom into soft horizontal folds, each
     lapping over the one below, and the hem -- the bottom bar, sewn in -- is what the card
     drags. The panel is drawn at its full length and clipped, so its seams stay put. */
  .win.roman .headrail {
    left: -1.5%;
    right: -1.5%;
    border-radius: 2px;
    background:
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.05) 0 0.5px, transparent 0.5px 1.5px),
      linear-gradient(to bottom, var(--n-cloth-hi), var(--n-cloth) 40%, var(--n-cloth-lo) 86%, var(--n-cloth-crease));
    box-shadow: 0 0 0 0.5px rgba(90, 70, 40, 0.3), 0 2px 3px -1px rgba(0, 0, 0, 0.3);
  }
  /* The seams repeat every fifth of the panel: ROMAN_SECTIONS in the script. The panel and
     its folds overhang the opening a hair, so no sky shows down their sides. */
  .fabric.roman, .fabric.fold { left: -0.6%; right: -0.6%; }
  .fabric.roman {
    height: calc(100% - var(--n-head) - var(--n-rail));
    background:
      linear-gradient(to right, rgba(90, 70, 40, 0.1), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.1)),
      repeating-linear-gradient(
        to bottom,
        transparent 0 calc(100% / 5 - 1.5px),
        rgba(120, 100, 70, 0.3) calc(100% / 5 - 1.5px) calc(100% / 5 - 0.5px),
        rgba(255, 255, 255, 0.4) calc(100% / 5 - 0.5px) calc(100% / 5)
      ),
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.05) 0 0.5px, transparent 0.5px 1.5px),
      linear-gradient(to bottom, var(--n-cloth-hi), var(--n-cloth) 55%, var(--n-cloth-lo));
    clip-path: inset(0 0 100% 0);
    transition: clip-path 0.45s var(--n-ease);
  }
  /* A fold: a flat face of cloth whose lower edge rounds under -- lit where it turns, dark
     at the crease beneath -- lapping over the fold below and shadowing it. */
  .fabric.fold {
    z-index: 2;
    background:
      linear-gradient(to right, rgba(90, 70, 40, 0.12), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.12)),
      repeating-linear-gradient(to bottom, rgba(140, 120, 90, 0.05) 0 0.5px, transparent 0.5px 1.5px),
      linear-gradient(to bottom, var(--n-cloth) 0, var(--n-cloth-hi) 14%, var(--n-cloth) 66%, var(--n-cloth-hi) 80%, var(--n-cloth-lo) 93%, var(--n-cloth-crease));
    box-shadow: 0 1px 2px rgba(60, 45, 25, 0.32);
  }
  .fabric.roman::after, .fabric.fold::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(90% 70% at 70% 30%, rgba(255, 250, 235, 0.5), transparent 70%);
    mix-blend-mode: soft-light;
  }
  ha-card[data-sky="night"] .fabric.roman::after, ha-card[data-sky="night"] .fabric.fold::after,
  ha-card[data-sky="dusk"] .fabric.roman::after, ha-card[data-sky="dusk"] .fabric.fold::after { display: none; }
  .win.roman .rail {
    border-radius: 0 0 3px 3px;
    background: linear-gradient(to bottom, var(--n-cloth-lo), var(--n-cloth) 28%, var(--n-cloth-hi) 52%, var(--n-cloth-lo) 88%, var(--n-cloth-crease));
    box-shadow: 0 0 0 0.5px rgba(90, 70, 40, 0.28), 0 2px 3px -1px rgba(0, 0, 0, 0.35);
  }

  /* ---- a PerfectSheer ---------------------------------------------------------------
     Soft fabric vanes held between two sheers, under a curved cassette the fabric rolls up
     into. Open, the vanes narrow to bands with the view through the sheer between them;
     closed, they meet in a soft wall of cloth. */
  .win.perfectsheer .headrail {
    border-radius: 3px 3px 4px 4px;
    background: linear-gradient(to bottom, var(--n-rail-lo), var(--n-rail-hi) 12%, var(--n-rail-face) 46%, var(--n-rail-lo) 90%);
  }
  .win.perfectsheer .clip {
    position: absolute;
    left: 0;
    right: 0;
    top: var(--n-head);
    bottom: 0;
    z-index: 1;
    overflow: hidden;
  }
  .win.perfectsheer .cloth {
    position: absolute;
    left: 0;
    right: 0;
    top: 0;
    background-color: rgba(252, 249, 243, 0.2);
    background-image:
      linear-gradient(to right, rgba(90, 70, 40, 0.08), transparent 8%, transparent 92%, rgba(90, 70, 40, 0.08)),
      repeating-linear-gradient(to bottom, rgba(176, 164, 144, 0.2) 0 0.5px, transparent 0.5px 2px);
    -webkit-backdrop-filter: blur(0.8px) brightness(1.06) saturate(0.8);
    backdrop-filter: blur(0.8px) brightness(1.06) saturate(0.8);
    transition: top 0.45s var(--n-ease);
  }
  /* The front sheer, over the vanes as well as between them. */
  .win.perfectsheer .cloth::after {
    content: "";
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(to bottom, rgba(255, 255, 255, 0.14) 0 0.5px, transparent 0.5px 2px);
  }
  .win.perfectsheer .vane {
    position: absolute;
    left: 0;
    right: 0;
    transform-origin: top;
    background: linear-gradient(to bottom, var(--n-cloth-lo), var(--n-cloth-hi) 10%, var(--n-cloth) 58%, var(--n-cloth-lo));
    box-shadow: 0 0.5px 0 rgba(150, 135, 110, 0.35);
    opacity: 0.94;
    transition: transform 0.45s var(--n-ease);
  }
  .win.dragging .cloth { transition: none; }
  ha-card[data-theme="dark"] .win.perfectsheer .vane { filter: brightness(0.88); }

  /* ---- a SmartDrape -------------------------------------------------------------------
     Fabric vanes on a sheer, hung from a track to the sill and drawn sideways. Each vane
     turns about its long axis -- flat and overlapping when closed, nearly edge-on when
     open, the view between them -- and the leading edge is what a hand, and the card, pulls. */
  .win.drape .headrail { height: 4.5%; }
  .win.drape .hanging {
    position: absolute;
    top: 4.5%;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 1;
    perspective: 320px;
  }
  .win.drape .sheer {
    position: absolute;
    top: 0;
    bottom: 0;
    background-color: rgba(252, 249, 243, 0.2);
    background-image: repeating-linear-gradient(to right, rgba(176, 164, 144, 0.2) 0 1px, transparent 1px 3px);
    -webkit-backdrop-filter: blur(1px) brightness(1.05) saturate(0.85);
    backdrop-filter: blur(1px) brightness(1.05) saturate(0.85);
    transition: left 0.45s var(--n-ease), width 0.45s var(--n-ease);
  }
  .win.drape .vane {
    position: absolute;
    top: 0;
    bottom: 0;
    background: linear-gradient(to right, var(--n-cloth-lo), var(--n-cloth-hi) 30%, var(--n-cloth) 62%, var(--n-cloth-lo));
    box-shadow: 0 0 0 0.5px rgba(120, 100, 70, 0.28), 1px 0 2px rgba(60, 45, 25, 0.16);
    transform: rotateY(0deg);
    transition: left 0.45s var(--n-ease), width 0.45s var(--n-ease), transform 0.45s var(--n-ease);
  }
  /* The leading edge: a slim bar down the drape's edge with a pull at its middle, pointing
     the way the drape draws. */
  .win.drape .lead {
    top: 4.5%;
    bottom: 0;
    right: auto;
    height: auto;
    width: 3%;
    min-width: 3px;
    min-height: 0;
    background: linear-gradient(to right, var(--n-rail-lo), var(--n-rail-hi) 40%, var(--n-rail-face) 70%, var(--n-rail-lo));
    transition: left 0.45s var(--n-ease);
  }
  .win.drape .lead.left { transform: translateX(-100%); }
  .win.drape .lead .tab {
    top: 44%;
    left: 100%;
    width: 7px;
    height: 14%;
    min-width: 0;
    max-width: none;
    transform: none;
    border-radius: 0 5px 5px 0;
    background: linear-gradient(to right, var(--n-rail-face), var(--n-rail-lo));
  }
  .win.drape .lead.right .tab {
    left: auto;
    right: 100%;
    border-radius: 5px 0 0 5px;
    background: linear-gradient(to left, var(--n-rail-face), var(--n-rail-lo));
  }
  .win.drape .rail.hot .tab, .win.drape .rail.held .tab { width: 9px; height: 14%; background: var(--n-accent); }
  .win.drape .zone {
    top: 4.5%;
    bottom: 0;
    left: 0;
    right: auto;
    width: 24%;
    height: auto;
    transform: translateX(-50%);
    transition: left 0.45s var(--n-ease);
  }
  .win.drape .marker {
    top: 4.5%;
    bottom: 0;
    right: auto;
    width: 0;
    height: auto;
    border-top: 0;
    border-left: 2px dashed var(--n-accent);
    transform: translateX(-1px);
    transition: opacity 0.25s, left 0.8s linear;
  }
  .win.dragging .vane, .win.dragging .sheer, .win.dragging .lead { transition: none; }

  /* ---- a Shutter ---------------------------------------------------------------------
     Painted louvers in a frame of stiles and rails, set into the window. Each louver turns
     about its long axis -- flat and overlapping when shut, nearly edge-on when open -- and
     the tilt rod down their middle is what a hand, and the card, moves. */
  .win.shutter .panel {
    position: absolute;
    inset: 0;
    z-index: 1;
  }
  .win.shutter .panel::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 2;
    pointer-events: none;
    background:
      linear-gradient(to right, var(--n-trim) 0 7%, transparent 7% 93%, var(--n-trim) 93%),
      linear-gradient(to bottom, var(--n-trim-hi) 0, var(--n-trim) 2%, var(--n-trim) 6%, transparent 6% 94%, var(--n-trim) 94%, var(--n-trim-lo));
    box-shadow: inset 0 0 0 1px var(--n-trim-edge), 0 1px 2px rgba(40, 30, 20, 0.25);
  }
  /* Tucked a little under the frame, so no sky shows where a shut louver meets a stile. */
  .win.shutter .louvers {
    position: absolute;
    top: 5.5%;
    bottom: 5.5%;
    left: 6.5%;
    right: 6.5%;
    z-index: 1;
    display: flex;
    flex-direction: column;
    perspective: 260px;
    box-shadow: inset 0 2px 4px rgba(40, 30, 20, 0.25);
  }
  .win.shutter .louver {
    flex: 1 1 0;
    margin: -0.8% 0;
    border-radius: 1px;
    background: linear-gradient(to bottom, var(--n-trim-hi), var(--n-trim) 42%, var(--n-trim) 70%, var(--n-trim-lo));
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 0 1px 1.5px rgba(60, 45, 25, 0.3);
    transform: rotateX(0deg);
    transition: transform 0.45s var(--n-ease);
  }
  .win.shutter .rod {
    position: absolute;
    left: 50%;
    top: 7%;
    bottom: 7%;
    width: 3.4%;
    min-width: 3px;
    z-index: 3;
    border-radius: 2px;
    background: linear-gradient(to right, var(--n-trim-lo), var(--n-trim-hi) 45%, var(--n-trim) 70%, var(--n-trim-lo));
    box-shadow: 0 0 0 0.5px var(--n-trim-edge), 1px 1px 2px rgba(0, 0, 0, 0.3);
    transform: translate(-50%, 0);
    transition: transform 0.45s var(--n-ease), background-color 0.15s, box-shadow 0.15s;
  }
  .win.shutter .rod.hot, .win.shutter .rod.held {
    background: var(--n-accent);
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.25), 0 0 8px rgba(var(--n-accent-rgb), 0.55);
  }
  .win.shutter .rod.moving:not(.held) { animation: n-pulse 1.6s ease-in-out infinite; }
  .win.shutter .rod-zone { left: 32%; right: 32%; top: 50%; height: 86%; }
  .win.shutter .marker { display: none; }
  .win.dragging .louver, .win.dragging .rod { transition: none; }
  ha-card[data-theme="dark"] .win.shutter .panel { filter: brightness(0.88); }

  /* ---- list layout (hide_picture) --------------------------------------------------- */
  .list { display: flex; flex-direction: column; gap: 12px; }
  /* One line per blind: the name, then its status (while moving), Stop and battery. */
  .row .meta { display: flex; align-items: center; gap: 8px; margin: 0 0 2px; }
  .row .name { flex: 1; width: auto; min-width: 0; }
  .row .meta-bottom { flex: none; align-items: center; min-height: 0; }
  .row .battery { margin-top: 0; }
  .slider {
    display: grid;
    grid-template-columns: 64px 1fr 40px;
    align-items: center;
    gap: 10px;
    min-height: 30px;
  }
  .slider-label { font-size: 12.5px; color: var(--n-muted); }
  .slider-value {
    text-align: right;
    font-size: 13px;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .slider input {
    -webkit-appearance: none;
    appearance: none;
    width: 100%;
    height: 6px;
    margin: 0;
    border-radius: 3px;
    background: linear-gradient(to right, var(--n-accent) var(--n-fill, 0%), rgba(var(--n-fg-rgb), 0.12) var(--n-fill, 0%));
    cursor: pointer;
  }
  .slider input::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.2), 0 1px 4px rgba(0, 0, 0, 0.3);
  }
  .slider input::-moz-range-thumb {
    width: 20px;
    height: 20px;
    border: 0;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.2), 0 1px 4px rgba(0, 0, 0, 0.3);
  }
  .slider input:focus-visible { outline: 2px solid var(--n-accent); outline-offset: 4px; }
  .slider input:disabled { cursor: default; }
  /* The sliders already say where each rail is; the status line only speaks up to say it
     is moving, that its move is not confirmed, or that it is unavailable. */
  .row .status.rest { display: none; }
  .row.unavailable { opacity: 0.5; }

  .empty { padding: 8px 0 4px; color: var(--n-muted); }
`;

class NormanShadesCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("norman-shades-card-editor");
  }

  static getStubConfig() {
    // No title: the card then names the hub itself. Baking in "Shades" here would mean
    // every card added from the picker carried a hardcoded title the user had to clear.
    return { type: "custom:norman-shades-card" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._rendered = false;
    // Positions the user chose, drawn until the hub reports them as its target. Keyed by
    // the entity the write went to; each entry is { value, at }.
    this._pending = new Map();
    // This card's last write to each rail, keyed and shaped like _pending: its `at` is when it
    // went. Sending a blind the target the hub already holds leaves the cover's state as it
    // was, so without this its last_updated would not restart the move window (see
    // _railState). A write that fails is taken back out (see _expect).
    this._sent = new Map();
    // The side each SmartDrape was last seen stacking to, by device: an unavailable cover
    // carries no attributes, and the drape keeps its side meanwhile (see _collectBlinds).
    this._stacks = new Map();
    // Redraws the card when the next move window closes (see _patch).
    this._settleTimer = null;
    // What the card has read from Home Assistant's registries, by name (see _fromRegistry).
    this._registryCache = new Map();
    // When each refresh control last sent, by control, so the hold outlasts a rebuild (see
    // _bindRefresh).
    this._refreshedAt = new Map();
    this._cells = [];
    // The header's text node and summary line (see _render).
    this._headerText = null;
    this._summary = null;
    // Set by the sidebar panel: Home Assistant hides its sidebar on phones (see narrow).
    this._narrow = false;
    this._menuButton = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._rendered = false;
    this._signature = undefined;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
    // A dashboard hands a card a changed config with setConfig alone (hui-card), and hass only
    // with the next state change in the house. A card that already has hass draws itself now.
    if (this._hass) this.hass = this._hass;
  }

  getCardSize() {
    const blinds = this._hass ? this._collectBlinds().length : 3;
    return 2 + Math.ceil(blinds / 3) * 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    // Every word on the card is built in the user's language, so a change of language (from
    // their profile) redraws it rather than patching values into the old words.
    const language = languageOf(hass);
    if (this._rendered && language !== this._language) {
      this._signature = undefined;
      this._rendered = false;
    }
    this._language = language;
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    } else {
      this._update();
    }
  }

  /** A string in the user's language (see STRINGS). */
  _t(key, vars) {
    return translate(languageOf(this._hass), key, vars);
  }

  /** A percentage as the user's language writes it: "84%", or "84 %" in German and French. */
  _pct(value) {
    return this._t("percent", { value: Math.round(value) });
  }

  // The sidebar panel passes Home Assistant's `narrow` on (phones: the sidebar is hidden).
  set narrow(narrow) {
    this._narrow = Boolean(narrow);
    this.toggleAttribute("narrow", this._narrow);
    this._syncMenuButton();
  }

  get narrow() {
    return this._narrow;
  }

  // In the sidebar panel, wherever Home Assistant isn't showing its sidebar (the same test its
  // own menu button uses), the header offers the way back to it. On a dashboard Home
  // Assistant's own toolbar already has that button.
  _wantsMenuButton() {
    if (!this.hasAttribute("panel")) return false;
    return this._narrow || this._hass?.dockedSidebar === "always_hidden";
  }

  _syncMenuButton() {
    if (this._menuButton) this._menuButton.hidden = !this._wantsMenuButton();
  }

  // ---- data ------------------------------------------------------------------------

  /**
   * Whether a device belongs on this card: any Norman device, or with `config_entry_id` only
   * that hub's. The frontend's device registry lists each device's config entries; the
   * entity registry it sends does not carry one.
   */
  _inScope(deviceId) {
    const entryId = this._config.config_entry_id;
    if (!entryId) return true;
    return entriesOf((this._hass?.devices || {})[deviceId]).includes(entryId);
  }

  /**
   * The hub a device is on: its config entry, or null when the device registry does not say.
   * A device another integration has added itself to lists that integration's entry as well
   * (one that tracks a blind's battery, say); its primary entry is the one that created it,
   * which for a Norman device is its hub's.
   */
  _entryOf(deviceId) {
    const device = this._hass?.devices?.[deviceId];
    return device?.config_entry_id ?? device?.primary_config_entry ?? entriesOf(device)[0] ?? null;
  }

  /**
   * `compute()`, kept under `name` until Home Assistant's registries, the language or the
   * card's config change.
   *
   * Home Assistant sets `hass` on every state change in the house, but replaces its entity,
   * device and area registries (`entities`, `devices`, `areas`) only when one of them changes.
   * So what the card reads from those alone is worked out once per change, not by scanning
   * every entity in the house on every update. Nothing read from `hass.states` belongs here:
   * the callers read that afresh each time.
   */
  _fromRegistry(name, compute) {
    const hass = this._hass;
    const key = [hass?.entities, hass?.devices, hass?.areas, languageOf(hass), this._config];
    const kept = this._registryCache.get(name);
    if (kept && kept.key.every((part, index) => part === key[index])) return kept.value;
    const value = compute();
    this._registryCache.set(name, { key, value });
    return value;
  }

  /**
   * Every Norman blind visible to this dashboard, assembled from its entities.
   *
   * A blind is identified by its device id, so the bottom rail, middle rail, sliders, battery
   * sensor and Request status button are grouped even though their entity ids are independent.
   *
   * Everything but a drape's `stack` comes from the registries and is kept between updates
   * (_fromRegistry). The stack is the drape cover's state, so it is read on every call.
   */
  _collectBlinds() {
    if (!this._hass) return [];
    const states = this._hass.states || {};
    // A drape is drawn gathering to the side it stacks to, which its cover reports. The kept
    // blinds are shared between calls, so a drape gets a copy rather than being changed.
    return this._fromRegistry("blinds", () => this._registryBlinds()).map((blind) => {
      if (blind.product !== "drape") return blind;
      const stack = states[blind.bottomCover]?.attributes?.stack;
      // Home Assistant leaves an unavailable entity's attributes out, `stack` with them. The
      // drape keeps the side it was last seen on meanwhile, rather than being redrawn
      // gathering left -- a new side would rebuild the card under the user's hands.
      if (stack !== undefined && stack !== null) {
        this._stacks.set(blind.deviceId, STACK_SIDES[stack] ? stack : "left");
      }
      return { ...blind, stack: this._stacks.get(blind.deviceId) || "left" };
    });
  }

  /** The blinds as the registries have them, with no `stack` yet (see _collectBlinds). */
  _registryBlinds() {
    const hass = this._hass;
    const registry = hass.entities || {};
    const devices = hass.devices || {};
    const areas = hass.areas || {};
    const blinds = new Map();

    const blindFor = (deviceId, fallbackName) => {
      if (!blinds.has(deviceId)) {
        const device = devices[deviceId] || {};
        const area = areas[device.area_id] || {};
        blinds.set(deviceId, {
          deviceId,
          name: device.name_by_user || device.name || fallbackName,
          // The area's name, or null for a blind in none, grouped under `default_room` or
          // "Unassigned" instead.
          area: area.name || null,
          room: area.name || this._config.default_room || this._t("unassigned"),
          product: productOf(device),
          stack: null,
          bottomCover: null,
          middleCover: null,
          louvers: false,
          bottomNumber: null,
          middleNumber: null,
          battery: null,
          // The blind's Request status button, or null when it has none on the card.
          refresh: null,
        });
      }
      return blinds.get(deviceId);
    };

    for (const [entityId, entry] of Object.entries(registry)) {
      if (entry.platform !== DOMAIN || !entry.device_id) continue;
      // The frontend's registry marks a hidden entity `hidden: true` and leaves disabled ones
      // out; `hidden_by` and `disabled_by` are the backend's names for the same.
      if (entry.hidden || entry.hidden_by || entry.disabled_by) continue;
      if (!this._inScope(entry.device_id)) continue;

      const [domain] = entityId.split(".");
      // `translation_key` is the reliable discriminator; fall back to the entity id's
      // suffix for anything that somehow lacks one (a user-renamed entity keeps its key,
      // so this is belt-and-braces rather than a common path).
      const key = entry.translation_key || "";
      const idEndsWith = (suffix) => entityId.endsWith(suffix);
      const blind = blindFor(entry.device_id, entityId);

      if (domain === "cover") {
        if (key === KEY_MIDDLE_RAIL || (!key && idEndsWith("_middle_rail"))) {
          blind.middleCover = entityId;
        } else if (key === KEY_LOUVERS) {
          blind.bottomCover = entityId;
          blind.louvers = true;
        } else if (key === KEY_BOTTOM_RAIL || !key) {
          blind.bottomCover = entityId;
        }
      } else if (domain === "number") {
        if (key === KEY_MIDDLE_POSITION || (!key && idEndsWith("_middle_rail_position"))) {
          blind.middleNumber = entityId;
        } else if (key === KEY_BOTTOM_POSITION || (!key && idEndsWith("_bottom_rail_position"))) {
          blind.bottomNumber = entityId;
        }
      } else if (
        domain === "sensor" &&
        (key === KEY_BATTERY || (!key && idEndsWith("_battery")))
      ) {
        // The `!key` guard matters here as much as on the rails: without it, any Norman
        // sensor whose entity id happens to end in "_battery" is claimed as the battery
        // even when its translation key says otherwise.
        blind.battery = entityId;
      } else if (domain === "button" && key === BUTTON_REQUEST_STATUS) {
        blind.refresh = entityId;
      }
    }

    // A device with no cover is the hub or one of its rooms, not a blind.
    return [...blinds.values()].filter((blind) => blind.bottomCover);
  }

  /**
   * The scenes saved in the Norman app, by room: a map from a room's name, as the blinds are
   * grouped (its area), to its scenes in name order.
   *
   * A room scene sits on its room's device, which the integration places in the area of the
   * same name; an area set on the scene itself wins, as it does everywhere in Home Assistant.
   * Scene groups are left out: they act on several rooms, so none of the rooms is theirs. So
   * is a scene hidden or disabled in Home Assistant, and one whose room has no area.
   *
   * The name is the registry's: the user's own name for the scene, or else the app's, which
   * Home Assistant brings into the registry whenever the entity's name changes.
   */
  _collectScenes() {
    const scenes = new Map();
    const devices = this._hass?.devices || {};
    const areas = this._hass?.areas || {};
    for (const { entityId, entry, name } of this._sceneEntities(KEY_ROOM_SCENE)) {
      const area = areas[entry.area_id || devices[entry.device_id]?.area_id];
      if (!area?.name) continue;
      if (!scenes.has(area.name)) scenes.set(area.name, []);
      scenes.get(area.name).push({ entityId, name });
    }
    return scenes;
  }

  /** The hub's scene groups, in name order: room scenes in several rooms, run together. */
  _collectSceneGroups() {
    return this._sceneEntities(KEY_SCENE_GROUP).map(({ entityId, name }) => ({ entityId, name }));
  }

  /**
   * Norman scene entities with translation key `key` that belong on this card, in name order:
   * not hidden or disabled in Home Assistant, and on this card's hub when it has one.
   *
   * Which scenes they are is kept between updates (_fromRegistry); a scene the registry leaves
   * unnamed is named from its state, so the names are read on every call.
   */
  _sceneEntities(key) {
    const hass = this._hass;
    const entries = this._fromRegistry(`scenes ${key}`, () => {
      const found = [];
      for (const [entityId, entry] of Object.entries(hass?.entities || {})) {
        if (entry.platform !== DOMAIN || entry.translation_key !== key) continue;
        if (!entry.device_id || entry.hidden || entry.hidden_by || entry.disabled_by) continue;
        if (!this._inScope(entry.device_id)) continue;
        found.push({ entityId, entry });
      }
      return found;
    });
    return entries
      .map(({ entityId, entry }) => ({
        entityId,
        entry,
        name: entry.name || hass.states?.[entityId]?.attributes?.friendly_name || entityId,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  /**
   * The heading to show: the configured title, else the hub's name.
   *
   * A configured `title` always wins, whatever it says -- including `""` for a blank
   * heading. With no title the header names the hub, so a house with two hubs gets two
   * cards you can tell apart; "Shades" is the fallback for when no hub device can be found
   * (an install with no Norman devices yet, or before the registry has loaded), and for a
   * card with no hub chosen that shows the blinds of more than one (see _hubName).
   *
   * Cards added from the picker before v0.30 have `title: "Shades"` saved in their config,
   * because `getStubConfig()` used to supply it. Those keep saying "Shades" until the title
   * is removed -- the card cannot tell a saved default from a deliberate choice.
   */
  _headingText() {
    const configured = this._config.title;
    return configured !== undefined ? configured : (this._hubName() ?? this._t("heading_fallback"));
  }

  /**
   * The hub's name, as Home Assistant has it.
   *
   * The hub is the Norman device carrying the hub's own entities (`HUB_KEYS`): its MAC
   * address, Wi-Fi and time-zone sensors, pairing and refresh. Not just any device without a
   * cover -- each of the hub's rooms is one of those too. `name_by_user` wins, matching how
   * Home Assistant shows the device everywhere else. Returns null when there is no hub to
   * name.
   *
   * A card with no `config_entry_id` shows every hub's blinds. Showing one hub's, it names
   * that hub, not another one set up beside it; showing several hubs', it names none of them.
   */
  _hubName() {
    const hass = this._hass;
    if (!hass) return null;

    return this._fromRegistry("hub name", () => {
      const registry = hass.entities || {};
      const devices = hass.devices || {};
      let hubs = null;
      if (!this._config.config_entry_id) {
        const shown = this._roomsOf(this._fromRegistry("blinds", () => this._registryBlinds()));
        hubs = new Set(shown.flatMap(([, list]) => list.map((blind) => this._entryOf(blind.deviceId))).filter(Boolean));
        if (hubs.size > 1) return null;
        if (!hubs.size) hubs = null;
      }

      for (const entry of Object.values(registry)) {
        if (entry.platform !== DOMAIN || !entry.device_id) continue;
        if (!HUB_KEYS.has(entry.translation_key)) continue;
        if (!this._inScope(entry.device_id)) continue;
        if (hubs && !hubs.has(this._entryOf(entry.device_id))) continue;
        const device = devices[entry.device_id];
        const name = device && (device.name_by_user || device.name);
        if (name) return name;
      }
      return null;
    });
  }

  /** Blinds grouped by room: in the configured `rooms` order if one is given, else A-Z. */
  _roomsOf(blinds) {
    const filter =
      Array.isArray(this._config.rooms) && this._config.rooms.length ? this._config.rooms : null;
    const rooms = new Map();
    for (const blind of blinds) {
      if (filter && !filter.includes(blind.room)) continue;
      if (!rooms.has(blind.room)) rooms.set(blind.room, []);
      rooms.get(blind.room).push(blind);
    }
    for (const list of rooms.values()) {
      list.sort((a, b) => a.name.localeCompare(b.name));
    }
    const order = (room) => (filter ? filter.indexOf(room) : 0);
    return [...rooms.entries()].sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0]));
  }

  _numberOf(entityId) {
    const state = this._hass.states[entityId];
    if (!state || state.state === "unknown" || state.state === "unavailable") return null;
    const value = Number(state.state);
    return Number.isNaN(value) ? null : value;
  }

  /**
   * A blind's rails, bottom first: `rails[0]` is the bottom rail and `rails[1]`, when there
   * is one, the middle rail above it.
   */
  _railsOf(blind) {
    if (blind.louvers) {
      // A Shutter has no rails: its one control is the louvers, which the cover exposes as
      // tilt -- how open they are, 0 (shut) to 100 (horizontal).
      return [
        {
          key: "louvers",
          label: this._t("louvers"),
          short: this._t("louvers"),
          coverId: blind.bottomCover,
          numberId: null,
          louvers: true,
        },
      ];
    }
    // `short` is the word the status line has room for: "Middle" for "Middle rail". A label
    // set in the card's config is shortened to its first word, as before.
    const rail = (key, configured) => ({
      key,
      label: configured || this._t(`${key}_rail`),
      short: configured ? configured.split(" ")[0] : this._t(`${key}_short`),
    });
    const rails = [
      { ...rail("bottom", this._config.bottom_label), coverId: blind.bottomCover, numberId: blind.bottomNumber },
    ];
    if (blind.middleCover || blind.middleNumber) {
      rails.push({
        ...rail("middle", this._config.middle_label),
        coverId: blind.middleCover,
        numberId: blind.middleNumber,
      });
    }
    return rails;
  }

  /**
   * Where the hub says a rail is, and where it is sending it (equal when idle). While the two
   * differ, `until` is when the move window closes, and past it `stale` is set.
   *
   * The hub stores a new target whether or not the blind hears the command, and keeps both
   * values until the blind next reports in. So a target the blind has not been heard
   * reaching within MOVE_WINDOW_MS is no longer a move under way, but neither value can be
   * trusted: a blind sat at "100, heading for 0" for two hours on 2026-10-12, and had
   * closed. The rail's cover changes state whenever the hub reports a new position or target
   * for it, so its last_updated is when the move began, unless this card has written the
   * rail since. With neither (a state without timestamps), the move is taken as under way.
   */
  _railState(rail) {
    const cover = this._hass.states[rail.coverId];
    let current;
    let heading;
    if (rail.louvers) {
      const tilt = cover?.attributes?.current_tilt_position;
      current = tilt === undefined || tilt === null ? null : Number(tilt);
      heading = cover?.attributes?.target_tilt;
    } else {
      current = rail.numberId ? this._numberOf(rail.numberId) : null;
      if (current === null) {
        const position = cover?.attributes?.current_position;
        current = position === undefined || position === null ? null : Number(position);
      }
      heading = cover?.attributes?.target_position;
    }
    const target = heading === undefined || heading === null ? current : Number(heading);
    if (current === null || target === null || Math.round(current) === Math.round(target)) {
      return { current, target };
    }
    const updated = Date.parse(cover?.last_updated);
    const since = Math.max(
      Number.isNaN(updated) ? -Infinity : updated,
      this._sent.get(rail.numberId || rail.coverId)?.at ?? -Infinity,
    );
    if (since === -Infinity) return { current, target };
    const until = since + MOVE_WINDOW_MS;
    return Date.now() < until ? { current, target, until } : { current, target, stale: true };
  }

  /**
   * Where a rail is drawn: the position the user just chose while the hub takes it up,
   * else where the hub is sending it. The picture shows where the shade is GOING; the
   * marker and the status line say where it is on the way.
   */
  _railValue(rail) {
    const pending = this._pending.get(rail.numberId || rail.coverId);
    if (pending) return pending.value;
    return this._railState(rail).target;
  }

  _isUnavailable(blind) {
    const state = this._hass.states[blind.bottomCover];
    return !state || state.state === "unavailable";
  }

  // ---- building --------------------------------------------------------------------

  _render() {
    const style = document.createElement("style");
    style.textContent = STYLES;

    const card = document.createElement("ha-card");
    card.appendChild(style);
    this._card = card;

    // With no configured title the header names the HUB rather than saying "Shades": a
    // house with two hubs gets two cards, and "Shades" twice says nothing about which.
    const header = el("div", "header");
    // Shown only in the sidebar panel where Home Assistant hides its sidebar (_wantsMenuButton).
    // It fires the same event as Home Assistant's own menu button, which opens the sidebar.
    this._menuButton = this._iconButton("mdi:menu", this._t("open_sidebar"), () =>
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })),
    );
    this._menuButton.classList.add("menu");
    this._syncMenuButton();
    header.appendChild(this._menuButton);
    const titles = el("div", "titles");
    const text = el("div", "header-text", this._headingText());
    // Kept so the heading can follow a hub rename, or fill in once the device registry has
    // loaded -- _render() runs once, but the hub's name can arrive or change later.
    this._headerText = text;
    this._summary = el("div", "summary");
    titles.append(text, this._summary);
    header.appendChild(titles);
    this._homeScenes = null;
    if (!this._config.hide_home_controls) {
      if (!this._config.hide_refresh) header.appendChild(this._buildHomeRefresh());
      header.appendChild(this._buildHomeControls());
      // Filled with the hub's scene groups on every rebuild (_fillHomeScenes).
      this._homeScenes = el("div", "segmented home-scenes");
      this._homeScenes.hidden = true;
      header.appendChild(this._homeScenes);
    }
    card.appendChild(header);

    this._body = el("div", "body");
    card.appendChild(this._body);
    // A new body has no rooms in it yet, so _update builds them whatever it last built.
    this._signature = undefined;

    this.shadowRoot.innerHTML = "";
    this.shadowRoot.appendChild(card);
    this._update();
  }

  _update() {
    if (!this._body || !this._hass) return;

    const sky = skyOf(this._hass.states["sun.sun"]);
    if (this._card.dataset.sky !== sky) this._card.dataset.sky = sky;
    const theme = this._hass.themes?.darkMode ? "dark" : "light";
    if (this._card.dataset.theme !== theme) this._card.dataset.theme = theme;

    if (this._headerText) {
      const title = this._headingText();
      if (this._headerText.textContent !== title) this._headerText.textContent = title;
      this._headerText.hidden = !title;
    }
    // The user can hide the sidebar from their profile, which arrives as a new hass.
    this._syncMenuButton();

    const rooms = this._roomsOf(this._collectBlinds());
    this._scenes = this._collectScenes();
    this._sceneGroups = this._collectSceneGroups();

    // Rebuild only when the set of blinds, a name, a blind's entities, or a room's scenes
    // change; otherwise patch values in place so a rail being dragged is never replaced under
    // the user's finger. The entity ids are in it because each tile is bound to them: an id
    // changed by "Recreate entity IDs", or an entity disabled or enabled, has to rebind it.
    const blindKey = (b) =>
      [b.deviceId, b.name, b.area, b.product, b.stack, b.louvers, b.bottomCover, b.middleCover,
        b.bottomNumber, b.middleNumber, b.battery, b.refresh].join("/");
    const signature = rooms
      .map(
        ([room, list]) =>
          `${room}:${list.map(blindKey).join(",")}` +
          `:${(this._scenes.get(room) || []).map((scene) => `${scene.entityId}=${scene.name}`).join(",")}`,
      )
      .concat(this._sceneGroups.map((group) => `group ${group.entityId}=${group.name}`))
      .join("|");
    if (signature !== this._signature) {
      this._signature = signature;
      this._build(rooms);
    }

    // Home Assistant sets `hass` on every state change in the house. Redraw only when one of
    // this card's own entities changed -- state objects are replaced, never mutated, so an
    // identity check is enough.
    const seen = this._watched.map((entityId) => this._hass.states[entityId]);
    if (this._seen && seen.every((state, index) => state === this._seen[index])) return;
    this._seen = seen;
    this._patch();
  }

  _build(rooms) {
    this._body.innerHTML = "";
    this._cells = [];
    this._sceneChips = [];
    this._seen = null;
    this._watched = [
      ...rooms.flatMap(([, list]) =>
        list.flatMap((blind) => [
          blind.bottomCover,
          blind.middleCover,
          blind.bottomNumber,
          blind.middleNumber,
          blind.battery,
          // Its refresh button is greyed out while the Request status button is unavailable.
          blind.refresh,
        ]),
      ),
      // A scene's chip is greyed out while the scene is unavailable.
      ...rooms.flatMap(([room]) => (this._scenes?.get(room) || []).map((scene) => scene.entityId)),
      ...(this._sceneGroups || []).map((group) => group.entityId),
    ].filter(Boolean);
    this._fillHomeScenes();

    if (!rooms.length) {
      this._body.appendChild(el("div", "empty", this._t("empty")));
      return;
    }

    // With the headings hidden the rooms run together as one grid.
    const sections = this._config.hide_room_names
      ? [[null, rooms.flatMap(([, list]) => list)]]
      : rooms;

    for (const [roomName, list] of sections) {
      const room = el("section", "room");
      if (roomName !== null) this._buildRoomHead(room, roomName, list);

      const grid = el("div", this._config.hide_picture ? "list" : "grid");
      for (const blind of list) grid.appendChild(this._buildBlind(blind));
      room.appendChild(grid);
      this._body.appendChild(room);
    }
  }

  /**
   * A room's heading: its name and count, open/stop/close for the whole room, and a button
   * that folds out the app's three presets for the room, followed by the room's scenes and
   * its refresh.
   *
   * A preset names its room to the hub, so blinds in no area -- grouped under "Unassigned" or
   * `default_room`, the card's name rather than a room of the hub's -- get no presets. Their
   * open/stop/close go through the covers, so they keep those, and their refresh presses each
   * blind's own button.
   *
   * hide_room_presets takes the presets and scenes out of the tray, and hide_refresh the
   * refresh; the tray and its button are there while anything is left in it.
   */
  _buildRoomHead(room, roomName, blinds) {
    const head = el("div", "room-head");
    head.appendChild(el("div", "room-name", roomName));
    room.appendChild(head);

    if (!this._config.hide_room_controls) {
      head.appendChild(this._buildRoomControls(roomName, blinds));
    }
    const runs = !this._config.hide_room_presets;
    const presets = runs && blinds.some((blind) => blind.area) ? this._buildRoomPresets(roomName, blinds) : null;
    const scenes = runs ? this._buildRoomScenes(roomName) : null;
    const refresh = this._config.hide_refresh ? null : this._buildRoomRefresh(roomName, blinds);
    if (!presets && !scenes && !refresh) return;
    const tray = el("div", "tray");
    tray.hidden = true;
    for (const part of [presets, scenes, refresh]) if (part) tray.appendChild(part);
    const label = presets || scenes ? "room_presets" : "room_more";
    const more = this._iconButton("mdi:dots-horizontal", this._t(label, { room: roomName }), () => {
      tray.hidden = !tray.hidden;
      more.classList.toggle("open", !tray.hidden);
      more.setAttribute("aria-expanded", String(!tray.hidden));
    });
    more.className = "icon-btn more";
    more.setAttribute("aria-expanded", "false");
    head.appendChild(more);
    room.appendChild(tray);
  }

  /**
   * Open / stop / close every blind in one room, both rails of a two-rail blind included.
   *
   * One cover per blind, so one hub command per blind: the integration paces commands about
   * 1.6 s apart, and a second command to the same blind only holds the room's others back.
   * Open and stop go to each blind's bottom rail. Opened, a two-rail blind's bottom rail
   * takes its middle rail up with it, as the integration carries a rail the other would
   * pass; and its two rails share one motor, which one stop stops. Close goes to a two-rail
   * blind's middle rail, which takes the bottom rail down with it.
   *
   * This is NOT the hub's own room verb. Close here ends a two-rail blind at bottom 0 AND
   * middle 0 -- both rails down, which leaves the light-filtering sheer across the window.
   * The app's "Best privacy" is bottom 0 with middle 100: the sheer stacked away and the
   * blackout across the window instead. That one lives in the presets tray
   * (norman.room_command).
   */
  _buildRoomControls(roomName, blinds) {
    const controls = el("div", "icon-group room-buttons");
    for (const [icon, service, label] of ROOM_ACTIONS) {
      controls.appendChild(
        this._iconButton(icon, this._t(label, { room: roomName }), () => {
          // One service call with a list, not one call per entity.
          const entityId = [];
          for (const blind of blinds) {
            // A Shutter's open and close turn its louvers; it has no stop to send.
            if (service === "stop_cover" && blind.louvers) continue;
            const cover = service === "close_cover" ? blind.middleCover || blind.bottomCover : blind.bottomCover;
            if (cover) entityId.push(cover);
          }
          if (entityId.length) this._hass.callService("cover", service, { entity_id: entityId });
        }),
      );
    }
    return controls;
  }

  /**
   * The app's three buttons for the whole house, via the hub's own scope-less verb.
   *
   * Omitting RoomID is what makes the hub treat a command as house-wide, so this is one
   * request per hub however many blinds there are -- the same three the app's "All Rooms"
   * screen sends. They carry the app's names rather than open/close arrows because they are
   * not open and close: "Best privacy" leaves a two-rail blind's middle rail fully OPEN.
   *
   * There is no house-wide Stop button. The hub accepted an unscoped MotorStop and stopped
   * one moving blind in a direct test, but stopping simultaneous motors across rooms has
   * not been verified. A room's Stop here still fans out through its covers.
   */
  _buildHomeControls() {
    const controls = el("div", "segmented home-buttons");
    for (const preset of PRESETS) {
      controls.appendChild(
        this._buildChip(preset.icon, this._t(preset.label), this._t("preset_every_room", { preset: this._t(preset.title) }), () => {
          // No `room`: the action omits RoomID, which the hub reads as every blind. Sent to
          // each hub with a blind on the card.
          this._roomCommand({ command: preset.command }, this._cells.map((cell) => cell.blind));
        }),
      );
    }
    return controls;
  }

  /**
   * The whole house's refresh, beside its presets: norman.room_command's refresh with no room,
   * which asks every blind on the hub to report in with one request -- to each hub with a
   * blind on the card. Nothing moves.
   */
  _buildHomeRefresh() {
    const group = el("div", "icon-group home-refresh");
    const button = this._iconButton(REFRESH_ICON, this._t("home_refresh"));
    this._bindRefresh(button, "home", () => {
      this._roomCommand({ command: "refresh" }, this._cells.map((cell) => cell.blind));
    });
    group.appendChild(button);
    return group;
  }

  /**
   * The hub's scene groups, after the whole-house presets: one chip each, which runs the group
   * -- room scenes in several rooms at once -- with every blind checked afterwards by the
   * integration. Empty and hidden when the hub has none.
   */
  _fillHomeScenes() {
    const box = this._homeScenes;
    if (!box) return;
    box.innerHTML = "";
    for (const group of this._sceneGroups || []) {
      const chip = this._buildChip(SCENE_ICON, group.name, group.name, () => {
        this._hass.callService("scene", "turn_on", { entity_id: group.entityId });
      });
      chip.dataset.entityId = group.entityId;
      (this._sceneChips ||= []).push(chip);
      box.appendChild(chip);
    }
    box.hidden = !box.children.length;
  }

  /**
   * The same three, scoped to one room, via norman.room_command.
   *
   * The action matches on the HUB's room name while the card groups by Home Assistant area.
   * The integration seeds areas from those names, so they agree until an area is renamed --
   * and then the action names the rooms the hub does know. They go to the hub the room's
   * `blinds` are on.
   */
  _buildRoomPresets(roomName, blinds = []) {
    const presets = el("div", "segmented room-presets");
    for (const preset of PRESETS) {
      presets.appendChild(
        this._buildChip(preset.icon, this._t(preset.label), this._t("preset_in_room", { preset: this._t(preset.title), room: roomName }), () => {
          this._roomCommand({ room: roomName, command: preset.command }, blinds);
        }),
      );
    }
    return presets;
  }

  /**
   * The room's scenes, saved in the Norman app: one chip each, which runs the scene. The
   * integration then watches every blind the scene moves. Null when the room has none, so a
   * room without scenes shows only its presets.
   */
  _buildRoomScenes(roomName) {
    const list = this._scenes?.get(roomName);
    if (!list?.length) return null;
    const group = el("div", "segmented room-scenes");
    for (const scene of list) {
      const title = this._t("preset_in_room", { preset: scene.name, room: roomName });
      const chip = this._buildChip(SCENE_ICON, scene.name, title, () => {
        this._hass.callService("scene", "turn_on", { entity_id: scene.entityId });
      });
      chip.dataset.entityId = scene.entityId;
      (this._sceneChips ||= []).push(chip);
      group.appendChild(chip);
    }
    return group;
  }

  /**
   * The room's refresh, after its presets and scenes: each of its blinds asked to report in,
   * and nothing moved. It presses their Request status buttons in one call -- the one status
   * request per blind the hub's own room refresh sends, but for exactly the blinds shown here,
   * so it needs neither a room of the hub's by the area's name nor a hub to route to. Null
   * when none of them has one.
   */
  _buildRoomRefresh(roomName, blinds) {
    if (!blinds.some((blind) => blind.refresh)) return null;
    const box = el("div", "segmented room-refresh");
    const chip = this._buildChip(REFRESH_ICON, this._t("refresh"), this._t("room_refresh", { room: roomName }));
    this._bindRefresh(chip, `room ${roomName}`, () => this._requestStatus(blinds));
    box.appendChild(chip);
    return box;
  }

  /**
   * norman.room_command, sent to this card's hub when it has one (`config_entry_id`). A card
   * with none shows every hub's blinds, and with two hubs the action cannot pick one itself,
   * so the card sends one call to each hub `blinds` are on, read from their devices.
   *
   * An unavailable blind does not count while others do: it may be on a hub that is not set
   * up, which the action refuses. With every one of them unavailable they all count, so the
   * call still names their hubs, and the action says what is wrong with them rather than
   * asking which hub was meant. With no hub to go on the action picks the only one, as it
   * always has.
   */
  _roomCommand(data, blinds = []) {
    const pinned = this._config.config_entry_id;
    const hubsOf = (list) => [...new Set(list.map((blind) => this._entryOf(blind.deviceId)).filter(Boolean))];
    let hubs = pinned ? [pinned] : hubsOf(blinds.filter((blind) => !this._isUnavailable(blind)));
    if (!hubs.length) hubs = hubsOf(blinds);
    if (!hubs.length) {
      this._hass.callService(DOMAIN, "room_command", data);
      return;
    }
    for (const entryId of hubs) {
      this._hass.callService(DOMAIN, "room_command", { ...data, config_entry_id: entryId });
    }
  }

  /** Press the Request status button of each of `blinds` that has one, in one call. */
  _requestStatus(blinds) {
    const buttons = blinds.map((blind) => blind.refresh).filter(Boolean);
    if (!buttons.length) return;
    this._hass.callService("button", "press", { entity_id: buttons.length === 1 ? buttons[0] : buttons });
  }

  /**
   * Make `button` a refresh control: a press runs `send`, and its icon turns once to say the
   * request went. A second press of the same control (`key`) within REFRESH_HOLD_MS is
   * ignored, rebuilt or not, so repeats do not queue more requests at the hub.
   */
  _bindRefresh(button, key, send) {
    button.addEventListener("click", () => {
      const now = Date.now();
      if (now - (this._refreshedAt.get(key) ?? -Infinity) < REFRESH_HOLD_MS) return;
      this._refreshedAt.set(key, now);
      send();
      button.classList.add("spin");
      setTimeout(() => button.classList.remove("spin"), REFRESH_SPIN_MS);
    });
  }

  /**
   * A preset or a scene: an icon and a word, since "blinds-horizontal" alone does not say
   * "privacy". Without `onClick` the chip is left for the caller to bind (a refresh).
   */
  _buildChip(icon, text, title, onClick) {
    const chip = el("button", "chip");
    chip.type = "button";
    chip.append(haIcon(icon), el("span", null, text));
    chip.title = title;
    chip.setAttribute("aria-label", title);
    if (!onClick) return chip;
    chip.addEventListener("click", () => {
      onClick();
      // The blinds take many seconds to answer, so the button acknowledges the press.
      chip.classList.add("sent");
      setTimeout(() => chip.classList.remove("sent"), 1500);
    });
    return chip;
  }

  _iconButton(icon, label, onClick) {
    const button = el("button", "icon-btn");
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
    button.appendChild(haIcon(icon));
    if (onClick) button.addEventListener("click", onClick);
    return button;
  }

  /** One blind: the window (or, with hide_picture, a slider per rail), its name and state. */
  _buildBlind(blind) {
    const rails = this._railsOf(blind);
    const list = Boolean(this._config.hide_picture);
    const tile = el("div", list ? "row" : "tile");

    const shade = list ? null : this._buildShade(blind, rails);
    if (shade) tile.appendChild(shade.element);

    const meta = el("div", "meta");
    const name = el("button", "name", blind.name);
    name.type = "button";
    name.title = this._t("blind_details", { name: blind.name });
    name.addEventListener("click", () => this._showMore(blind.bottomCover));

    const bottom = el("div", "meta-bottom");
    const status = el("span", "status");
    bottom.appendChild(status);

    let batteryEl = null;
    if (blind.battery && !this._config.hide_battery) {
      batteryEl = el("span", "battery");
      batteryEl.append(haIcon("mdi:battery"), el("span"));
      // A bare "84%" next to a blind reads as a position; the icon, title and aria-label
      // say it is the battery.
      batteryEl.setAttribute("role", "img");
      batteryEl.addEventListener("click", () => this._showMore(blind.battery));
      bottom.appendChild(batteryEl);
    }

    // Beside the battery: the blind's Request status, which has it report in without moving.
    let refreshEl = null;
    if (blind.refresh && !this._config.hide_refresh) {
      refreshEl = this._iconButton(REFRESH_ICON, this._t("refresh_blind", { name: blind.name }));
      refreshEl.className = "refresh";
      this._bindRefresh(refreshEl, blind.refresh, () => this._requestStatus([blind]));
      bottom.appendChild(refreshEl);
    }

    const stop = el("button", "stop");
    stop.type = "button";
    stop.hidden = true;
    stop.title = this._t("stop_blind", { name: blind.name });
    stop.setAttribute("aria-label", stop.title);
    stop.append(haIcon("mdi:stop"), el("span", null, this._t("stop")));
    stop.addEventListener("click", () => this._stop(rails));
    // On the window's corner in the grid -- outside the window itself, so a press on it is
    // never taken for the start of a drag.
    (list ? bottom : tile).appendChild(stop);
    meta.append(name, bottom);
    tile.appendChild(meta);

    // In the list layout the rails are sliders, top rail first as on the blind.
    const sliders = list ? [...rails].reverse().map((rail) => this._buildSlider(blind, rails, rail)) : [];
    for (const slider of sliders) tile.appendChild(slider.row);

    this._cells.push({ blind, rails, tile, shade, batteryEl, refreshEl, status, stop, sliders });
    return tile;
  }

  /**
   * The window for one blind: casing, sill, the view, and the shade hanging in it.
   *
   * One fabric band, one rail and one grab zone per rail. On a two-rail blind the band from
   * the headrail to the middle rail is the light-filtering sheer and the band from the
   * middle rail to the bottom rail the blackout. The app's "Best privacy" (bottom 0,
   * middle 100) therefore stacks the sheer away and draws the blackout across the window:
   * "closed for privacy, sheer fabric still open".
   *
   * The two rails' pull tabs sit apart -- the middle rail's left of centre, the bottom
   * rail's right -- so that both can still be taken hold of when the rails are together.
   *
   * A roller shade hangs plain fabric off a roll in place of the headrail, and the roll
   * grows as the shade winds up onto it. A Roman shade's panel folds up into a stack above
   * its hem. A PerfectSheer's vanes, between two sheers, slide up into a cassette.
   */
  _buildShade(blind, rails) {
    if (blind.louvers) return this._buildShutter(blind, rails);
    if (blind.product === "drape") return this._buildDrape(blind, rails);
    const { product } = blind;
    const roller = product === "roller";
    const element = el("div", product ? `win ${product}` : "win");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const view = el("div", "view");
    view.append(el("div", "sun"), el("div", "hills"), el("div", "mullion"), el("div", "transom"), el("div", "glint"));

    const twoRail = rails.length > 1;
    const single = roller || product === "roman" ? product : "single";
    let bands = rails.map((_, index) =>
      el("div", `fabric ${twoRail ? (index === 1 ? "sheer" : "blackout") : single}`),
    );
    // A Roman shade's folds, bottom one first, drawn over the flat panel above them.
    const folds = product === "roman" ? Array.from({ length: ROMAN_SECTIONS }, () => el("div", "fabric fold")) : [];
    // A PerfectSheer's fabric is drawn at its full length and slides up out of sight into
    // the cassette, so it hangs in a clip below the cassette rather than as a band.
    let cloth = null;
    let vanes = [];
    if (product === "perfectsheer") {
      cloth = el("div", "cloth");
      vanes = Array.from({ length: SHEER_VANES }, (_, k) => {
        const vane = el("div", "vane");
        vane.style.top = `${round3((k / SHEER_VANES) * 100)}%`;
        vane.style.height = `${round3(100 / SHEER_VANES)}%`;
        return vane;
      });
      cloth.append(...vanes);
      const clip = el("div", "clip");
      clip.appendChild(cloth);
      bands = [clip];
    }
    const markers = rails.map(() => el("div", "marker"));
    const railEls = rails.map((_, index) => {
      const rail = el("div", `rail ${index === 0 ? "bottom" : "middle"}`);
      const tab = el("div", "tab");
      tab.style.left = `${this._tabX(rails, index)}%`;
      rail.appendChild(tab);
      return rail;
    });
    const zones = rails.map((rail, index) => {
      const zone = el("div", "zone");
      zone.tabIndex = 0;
      zone.dataset.index = String(index);
      zone.setAttribute("role", "slider");
      zone.setAttribute("aria-orientation", "vertical");
      zone.setAttribute("aria-valuemin", "0");
      zone.setAttribute("aria-valuemax", "100");
      zone.setAttribute("aria-label", this._railName(blind, rails, rail));
      return zone;
    });
    const bubble = el("div", "bubble");

    const head = el("div", roller ? "roll" : "headrail");
    // Behind a roll, the top of the window's recess: no sky shows round the roll's ends.
    const jamb = roller ? el("div", "jamb") : null;
    const brackets = roller ? [el("div", "bracket left"), el("div", "bracket right")] : [];
    opening.append(view, ...bands, ...folds, ...markers, ...railEls, ...(jamb ? [jamb] : []), head, ...brackets, ...zones, bubble);
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = {
      element,
      opening,
      bands,
      markers,
      railEls,
      zones,
      bubble,
      rails,
      product,
      roll: roller ? head : null,
      jamb,
      folds,
      cloth,
      vanes,
      dragValues: {},
    };
    this._bindShade(shade);
    return shade;
  }

  /**
   * A Shutter in its window: a painted frame of stiles and rails, a column of louvers, and
   * the tilt rod down their middle -- the rod is what the card drags, as a hand would.
   *
   * The louvers turn about their long axis, so how open they are is drawn as a rotation:
   * flat and overlapping when shut, nearly edge-on with the view between them when open.
   * They lean the other way when the hub reports them turned past horizontal (its
   * Positions 0-2, which a remote or the app can choose).
   */
  _buildShutter(blind, rails) {
    const element = el("div", "win shutter");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const view = el("div", "view");
    view.append(el("div", "sun"), el("div", "hills"), el("div", "mullion"), el("div", "transom"), el("div", "glint"));

    const panel = el("div", "panel");
    const louverBox = el("div", "louvers");
    const louverEls = Array.from({ length: LOUVER_COUNT }, () => el("div", "louver"));
    louverBox.append(...louverEls);
    const rod = el("div", "rod");
    panel.append(louverBox, rod);

    const zone = el("div", "zone rod-zone");
    zone.tabIndex = 0;
    zone.dataset.index = "0";
    zone.setAttribute("role", "slider");
    zone.setAttribute("aria-orientation", "vertical");
    zone.setAttribute("aria-valuemin", "0");
    zone.setAttribute("aria-valuemax", "100");
    zone.setAttribute("aria-label", this._railName(blind, rails, rails[0]));
    const marker = el("div", "marker");
    const bubble = el("div", "bubble");

    opening.append(view, panel, zone, bubble);
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = {
      element,
      opening,
      bands: [],
      markers: [marker],
      railEls: [rod],
      zones: [zone],
      bubble,
      rails,
      louverEls,
      louvers: true,
      dragValues: {},
    };
    this._bindShade(shade);
    return shade;
  }

  /**
   * A SmartDrape in its window: fabric vanes on a sheer, hung from a track to the sill and
   * drawn sideways -- gathered to the side it stacks to when open, spread across the window
   * when closed. A split drape parts in the middle and gathers to both sides.
   *
   * The leading edge is what the card drags, sideways. The vanes turn with the cover's tilt,
   * flat and overlapping when closed and nearly edge-on when open; turning them is the tilt
   * in the blind's more-info dialog, not a drag here.
   */
  _buildDrape(blind, rails) {
    const element = el("div", "win drape");
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", blind.name);

    const frame = el("div", "frame");
    const opening = el("div", "opening");
    const view = el("div", "view");
    view.append(el("div", "sun"), el("div", "hills"), el("div", "mullion"), el("div", "transom"), el("div", "glint"));

    const sides = STACK_SIDES[blind.stack] || STACK_SIDES.left;
    const hanging = el("div", "hanging");
    const parts = sides.map((side) => {
      const sheer = el("div", "sheer");
      const vanes = Array.from({ length: DRAPE_VANES / sides.length }, () => el("div", "vane"));
      hanging.append(sheer, ...vanes);
      const lead = el("div", `rail lead ${side}`);
      lead.dataset.index = "0";
      lead.appendChild(el("div", "tab"));
      const zone = el("div", "zone");
      zone.tabIndex = 0;
      zone.dataset.index = "0";
      zone.dataset.side = side;
      zone.setAttribute("role", "slider");
      zone.setAttribute("aria-orientation", "horizontal");
      zone.setAttribute("aria-valuemin", "0");
      zone.setAttribute("aria-valuemax", "100");
      zone.setAttribute("aria-label", sides.length > 1 ? this._t(`blind_${side}_half`, { name: blind.name }) : blind.name);
      return { side, sheer, vanes, lead, zone, marker: el("div", "marker") };
    });
    const bubble = el("div", "bubble");

    opening.append(
      view,
      hanging,
      ...parts.map((part) => part.marker),
      ...parts.map((part) => part.lead),
      el("div", "headrail"),
      ...parts.map((part) => part.zone),
      bubble,
    );
    frame.appendChild(opening);
    element.append(frame, el("div", "sill"));

    const shade = {
      element,
      opening,
      bands: [],
      markers: parts.map((part) => part.marker),
      railEls: parts.map((part) => part.lead),
      zones: parts.map((part) => part.zone),
      bubble,
      rails,
      drape: true,
      parts,
      dragValues: {},
    };
    this._bindShade(shade);
    return shade;
  }

  /**
   * Dragging and keys.
   *
   * A mouse can press anywhere on the window and the nearest rail follows; a finger has to
   * start on a rail's grab zone, so the rest of the picture still scrolls the page. The
   * drag follows the pointer's movement rather than its position, so a press never makes a
   * rail jump, and nothing is written until release -- a tap writes nothing at all.
   */
  _bindShade(shade) {
    const { element, opening } = shade;
    let press = null;

    // A rail's elements: one, except a split drape's rail, which has a leading edge per half.
    const indexOf = (rail, i) => Number(rail.dataset?.index ?? i);
    const railElsAt = (index) => shade.railEls.filter((rail, i) => indexOf(rail, i) === index);
    const setHot = (index) => {
      shade.railEls.forEach((rail, i) => rail.classList.toggle("hot", indexOf(rail, i) === index));
    };
    // Which rail a press means: the nearest one, or -- where the two rails are together and
    // so equally near -- the one whose tab is on that side.
    const pick = (event) => {
      if (shade.drape) return 0;
      const rect = opening.getBoundingClientRect();
      const y = ((event.clientY - rect.top) / rect.height) * 100;
      const centers = shade.rails.map(
        (_, index) => this._railTop(shade, index, this._shadeValue(shade, index)) + SHADE_RAIL_PCT / 2,
      );
      if (shade.rails.length > 1 && centers[0] - centers[1] < SHADE_RAIL_PCT * 2.5) {
        const nearStack = y > centers[1] - SHADE_RAIL_PCT * 3 && y < centers[0] + SHADE_RAIL_PCT * 3;
        if (nearStack) return event.clientX - rect.left < rect.width / 2 ? 1 : 0;
      }
      let best = 0;
      centers.forEach((center, index) => {
        if (Math.abs(center - y) < Math.abs(centers[best] - y)) best = index;
      });
      return best;
    };

    element.addEventListener("pointerdown", (event) => {
      if (shade.disabled || press) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;
      const onZone = event.target?.classList?.contains("zone");
      if (event.pointerType !== "mouse" && !onZone) return;
      const rect = opening.getBoundingClientRect();
      if (!rect.height) return;
      press = {
        id: event.pointerId,
        index: pick(event),
        x0: event.clientX,
        y0: event.clientY,
        rect,
        side: shade.drape ? this._drapeSideAt(shade, event, rect) : null,
        started: false,
        step: null,
        // A move the arrow keys were gathering on the dragged rail, taken over by the drag.
        keys: null,
      };
      // Arrow keys are ignored until the press ends (_onKey): the drag owns the blind's drawing.
      shade.pressing = true;
      shade.activeSide = press.side;
      element.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    });

    element.addEventListener("pointermove", (event) => {
      if (!press) {
        if (event.pointerType === "mouse" && !shade.disabled) setHot(pick(event));
        return;
      }
      if (event.pointerId !== press.id) return;
      const delta = shade.drape ? event.clientX - press.x0 : event.clientY - press.y0;
      if (!press.started) {
        if (Math.abs(delta) < DRAG_SLOP) return;
        press.started = true;
        // A move the arrow keys are still gathering cannot be left to its timer, which would go
        // off mid-drag. On the dragged rail the drag takes it over: it starts where the keys
        // left the rail, and its release is the one write. On the other rail it is sent now.
        if (shade.keyMove?.index === press.index) {
          press.keys = shade.keyMove;
          clearTimeout(shade.keyTimer);
          shade.keyTimer = null;
          shade.keyMove = null;
        } else {
          this._sendKeys(shade);
        }
        press.start = this._shadeValue(shade, press.index) ?? 0;
        press.travel = shade.drape
          ? (press.rect.width * this._drapeTravelPct(shade)) / 100
          : (press.rect.height * this._travelPct(shade)) / 100;
        element.classList.add("dragging");
        for (const rail of railElsAt(press.index)) rail.classList.add("held");
        setHot(press.index);
      }
      // Up opens a shade; a drape opens towards the side it gathers to.
      const sign = shade.drape && press.side === "right" ? 1 : -1;
      const value = clamp(press.start + sign * (delta / press.travel) * 100);
      this._dragTo(shade, press.index, value);
      const step = clampToStep(value, stepOf(shade.rails[press.index]));
      this._showBubble(shade, press.index, step);
      if (press.step !== null && step !== press.step) navigator.vibrate?.(4);
      press.step = step;
    });

    const finish = (event, commit) => {
      if (!press || event.pointerId !== press.id) return;
      const { index, started, keys } = press;
      press = null;
      shade.pressing = false;
      element.releasePointerCapture?.(event.pointerId);
      element.classList.remove("dragging");
      for (const rail of railElsAt(index)) rail.classList.remove("held");
      if (event.pointerType !== "mouse") setHot(-1);
      this._hideBubble(shade);
      if (!started) return;
      const value = shade.dragValues[index];
      shade.dragValues = {};
      // A rail with no value is never written: clampToStep would make it 0 and close the blind.
      if (commit && value !== undefined) {
        this._move(shade.rails, index, clampToStep(value, stepOf(shade.rails[index])));
      } else if (keys) {
        // The drag was called off, but the keys' move it took over still stands.
        this._move(shade.rails, keys.index, keys.value);
      }
      this._patch();
    };
    element.addEventListener("pointerup", (event) => finish(event, true));
    // A cancelled pointer (the browser took the gesture) puts the rail back where the hub, or
    // the arrow keys before the drag, had it.
    element.addEventListener("pointercancel", (event) => finish(event, false));
    element.addEventListener("pointerleave", (event) => {
      if (!press && event.pointerType === "mouse") setHot(-1);
    });

    shade.zones.forEach((zone, i) => {
      const index = indexOf(zone, i);
      const side = zone.dataset.side;
      zone.addEventListener("focus", () => {
        shade.activeSide = side;
        setHot(index);
      });
      zone.addEventListener("blur", () => setHot(-1));
      zone.addEventListener("keydown", (event) => this._onKey(shade, index, event, side));
    });
  }

  /**
   * Arrow keys move a rail a step; the write goes out once the keys stop. On a drape the
   * left and right arrows move its edge that way, so the one towards its stack opens it.
   *
   * A blind gathers one rail's keys at a time: keys on its other rail first send the move
   * gathered so far, which would otherwise be dropped with the timer and the drawing it shares.
   * While a pointer is pressed on the blind its arrow keys only keep the page from scrolling:
   * the drag draws the blind, and its release sends it. A key held with Alt, Ctrl or Meta is
   * a shortcut of the browser's or the system's (Alt+Left is Back), so it is left to them.
   */
  _onKey(shade, index, event, side) {
    if (shade.disabled || event.altKey || event.ctrlKey || event.metaKey) return;
    const step = stepOf(shade.rails[index]);
    const activeSide = shade.drape ? side || shade.parts[0].side : null;
    const across = shade.drape && activeSide !== "right" ? -1 : 1;
    // How far each key moves the rail; Home and End go all the way, to closed and to open.
    const moves = {
      ArrowUp: step,
      ArrowRight: across * step,
      ArrowDown: -step,
      ArrowLeft: -across * step,
      PageUp: 3 * step,
      PageDown: -3 * step,
      Home: -100,
      End: 100,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    if (shade.pressing) return;
    if (shade.drape) shade.activeSide = activeSide;
    if (shade.keyMove && shade.keyMove.index !== index) this._sendKeys(shade);
    const value = clampToStep((this._shadeValue(shade, index) ?? 0) + moves[event.key], step);
    this._dragTo(shade, index, value);
    this._showBubble(shade, index, value);
    // A screen reader says the new value now, not when the keys' move is sent.
    shade.zones.forEach((zone, i) => {
      if (Number(zone.dataset?.index ?? i) === index) this._sayValue(zone, value);
    });
    clearTimeout(shade.keyTimer);
    shade.keyMove = { index, value };
    shade.keyTimer = setTimeout(() => this._sendKeys(shade), KEY_COMMIT_MS);
  }

  /** Send the move the arrow keys have gathered on a blind, if there is one (see _onKey). */
  _sendKeys(shade) {
    const move = shade.keyMove;
    clearTimeout(shade.keyTimer);
    shade.keyTimer = null;
    shade.keyMove = null;
    if (!move) return;
    shade.dragValues = {};
    this._hideBubble(shade);
    this._move(shade.rails, move.index, move.value);
    this._patch();
  }

  /**
   * Where a two-rail blind's other rail ends up when rail `index` goes to `value`.
   *
   * The middle rail always hangs above the bottom rail, so the other rail stays where it is
   * unless `value` would pass it -- and then it is carried along, as it is on the blind: the
   * middle rail pulled down past the bottom rail takes the bottom rail with it, and the
   * bottom rail pushed up past the middle rail takes the middle rail up. The integration
   * does the same when it sends the move, in the one command. Null on a single-rail blind.
   */
  _carried(rails, index, value) {
    if (rails.length < 2) return null;
    const other = this._railValue(rails[1 - index]);
    if (other === null) return null;
    return index === 0 ? Math.max(other, value) : Math.min(other, value);
  }

  /** Draw rail `index` at `value` mid-drag, with the other rail carried if it is passed. */
  _dragTo(shade, index, value) {
    shade.dragValues = { [index]: value };
    const carried = this._carried(shade.rails, index, value);
    if (carried !== null && carried !== this._railValue(shade.rails[1 - index])) {
      shade.dragValues[1 - index] = carried;
    }
    this._drawShade(shade);
  }

  /**
   * Send rail `index` to `value`. One write: the integration carries the other rail along
   * in the same hub command when it has to, so that rail is only drawn there until the hub
   * reports it -- never written separately, where two commands could cross in flight.
   *
   * A rail already drawn at `value` is not sent there again, unless its move is not confirmed:
   * the blind may never have heard it, and sending it again starts a new move.
   */
  _move(rails, index, value) {
    const rail = rails[index];
    if (value === this._railValue(rail) && !this._railState(rail).stale) return;
    const carried = this._carried(rails, index, value);
    let undoCarried = null;
    if (carried !== null && carried !== this._railValue(rails[1 - index])) {
      undoCarried = this._expect(rails[1 - index], carried);
    }
    this._setRail(rail, value, undoCarried);
  }

  /** Where a two-rail blind's pull tab sits across the rail, in percent: apart, so both can be reached. */
  _tabX(rails, index) {
    if (rails.length < 2) return 50;
    return index === 1 ? 32 : 68;
  }

  /** What a rail is drawn at right now: a drag or key press, else _railValue. */
  _shadeValue(shade, index) {
    const dragged = shade.dragValues?.[index];
    if (dragged !== undefined) return dragged;
    return this._railValue(shade.rails[index]);
  }

  /** How thick a roller shade's roll is at `value`, in percent of the opening's height. */
  _rollSize(value) {
    return ROLL_MIN_PCT + ((ROLL_MAX_PCT - ROLL_MIN_PCT) * clamp(value ?? 0)) / 100;
  }

  /** How much of the window one side of a drape spans: all of it, or half when split. */
  _drapeSpan(shade) {
    return shade.parts.length > 1 ? 50 : 100;
  }

  /** How far a drape's edge travels, in percent of the opening's width: its span, less its stack. */
  _drapeTravelPct(shade) {
    const span = this._drapeSpan(shade);
    return span - (DRAPE_STACK_PCT * span) / 100;
  }

  /** How far a drape reaches from the side it gathers to at `value` (100 open, 0 drawn). */
  _drapeReach(shade, value) {
    const span = this._drapeSpan(shade);
    const gathered = (DRAPE_STACK_PCT * span) / 100;
    return gathered + ((100 - clamp(value ?? 0)) / 100) * this._drapeTravelPct(shade);
  }

  /** Where one side's leading edge is, in percent across the opening. */
  _drapeEdge(part, reach) {
    return part.side === "left" ? reach : 100 - reach;
  }

  /** Which side of a drape a press takes hold of: its own, or on a split drape the nearer. */
  _drapeSideAt(shade, event, rect) {
    const own = event.target?.dataset?.side;
    if (own) return own;
    if (shade.parts.length === 1) return shade.parts[0].side;
    return event.clientX - rect.left < rect.width / 2 ? "left" : "right";
  }

  /** How open a drape's or a PerfectSheer's vanes are drawn, 0 to 1: where the cover's tilt is heading. */
  _vanesOpen(shade) {
    const attributes = this._hass?.states?.[shade.rails[0].coverId]?.attributes || {};
    const tilt = attributes.target_tilt ?? attributes.current_tilt_position;
    return tilt === undefined || tilt === null ? 0 : clamp(Number(tilt) || 0) / 100;
  }

  /** The distance a rail travels, as a percentage of the opening: what the rails leave. */
  _travelPct(shade) {
    if (shade.louvers) return LOUVER_TRAVEL_PCT;
    return 100 - SHADE_HEAD_PCT - this._stackPct(shade) - shade.rails.length * SHADE_RAIL_PCT;
  }

  /** What stays below the headrail with the shade fully up: a Roman shade's folds, else nothing. */
  _stackPct(shade) {
    return shade.product === "roman" ? ROMAN_STACK_PCT : 0;
  }

  /**
   * Where a rail's top edge sits, in percent down the opening. Open (100) is tucked under
   * the headrail -- or under the middle rail, for the bottom rail of a two-rail blind, and
   * under its folds for a Roman shade -- and closed (0) rests on the sill.
   */
  _railTop(shade, index, value) {
    const above = shade.rails.length - 1 - index;
    const position = value === null || value === undefined ? 0 : value;
    return (
      SHADE_HEAD_PCT +
      this._stackPct(shade) +
      above * SHADE_RAIL_PCT +
      ((100 - position) / 100) * this._travelPct(shade)
    );
  }

  /**
   * How a Roman shade's folds hang at `value`: how many sections are folded (a fraction
   * while one is still folding) and how deep each fold is. A fold takes up a section of the
   * panel and, hanging loose, is half a section deep; once every section is folded they
   * pack tighter, to ROMAN_STACK_PCT all told with the shade fully up. The hem rises evenly
   * all the while, so it stays under the pointer.
   */
  _romanFolds(value) {
    const length = 100 - SHADE_HEAD_PCT - SHADE_RAIL_PCT;
    const section = length / ROMAN_SECTIONS;
    const raised = (clamp(value ?? 0) / 100) * (length - ROMAN_STACK_PCT);
    const loose = raised / (section / 2);
    if (loose <= ROMAN_SECTIONS) return { count: loose, depth: section / 2 };
    return { count: ROMAN_SECTIONS, depth: section - raised / ROMAN_SECTIONS };
  }

  /**
   * Hang a Roman shade's folds above its hem at `hem`, bottom fold first, and cut the flat
   * panel off where they begin. The fold still forming is the top one, where the stack
   * takes up the panel above it. The panel keeps its full length, so its seams stay at the
   * battens; it is clipped rather than shortened.
   */
  _drawFolds(shade, hem) {
    const { count, depth } = this._romanFolds(this._shadeValue(shade, 0));
    const length = 100 - SHADE_HEAD_PCT - SHADE_RAIL_PCT;
    const flat = Math.max(0, hem - count * depth - SHADE_HEAD_PCT);
    const shown = Math.min(length, flat + ROMAN_LAP_PCT);
    shade.bands[0].style.clipPath = `inset(0 0 ${round3(100 - (shown / length) * 100)}% 0)`;
    shade.folds.forEach((fold, k) => {
      fold.style.top = `${round3(hem - Math.min(count, k + 1) * depth)}%`;
      fold.style.height = `${round3(clamp(count - k, 0, 1) * depth)}%`;
    });
  }

  /**
   * Hang a PerfectSheer's fabric from the cassette to its bottom rail at `top`. It rolls up
   * into the cassette, so it slides up at its full length rather than shortening. Its vanes
   * open only with the shade fully down; anywhere else they are drawn closed.
   */
  _drawCloth(shade, top) {
    const length = 100 - SHADE_HEAD_PCT - SHADE_RAIL_PCT;
    const clip = 100 - SHADE_HEAD_PCT;
    shade.cloth.style.top = `${round3(((top - SHADE_HEAD_PCT - length) / clip) * 100)}%`;
    shade.cloth.style.height = `${round3((length / clip) * 100)}%`;
    const open = (this._shadeValue(shade, 0) ?? 0) <= 0 ? this._vanesOpen(shade) : 0;
    const band = round3(1 - (1 - SHEER_VANE_OPEN) * open);
    for (const vane of shade.vanes) vane.style.transform = `scaleY(${band})`;
  }

  /**
   * Place every band, rail and grab zone of one picture in a single pass, top rail first:
   * each band hangs from the edge above it (the headrail, or the rail above) to its rail.
   */
  _drawShade(shade) {
    if (shade.louvers) {
      this._drawLouvers(shade);
      return;
    }
    if (shade.drape) {
      this._drawDrape(shade);
      return;
    }
    if (shade.rails.length > 1) {
      const together = this._shadeValue(shade, 1) - this._shadeValue(shade, 0) < 1;
      shade.element.classList.toggle("stacked", together);
    }
    let edge = SHADE_HEAD_PCT;
    if (shade.roll) {
      // The fabric comes off the underside of the roll, which winds up as the shade rises.
      const size = this._rollSize(this._shadeValue(shade, 0));
      shade.roll.style.height = `${round3(size)}%`;
      edge = ROLL_TOP_PCT + size / 2;
      shade.jamb.style.height = `${round3(edge)}%`;
    }
    for (let index = shade.rails.length - 1; index >= 0; index -= 1) {
      const top = this._railTop(shade, index, this._shadeValue(shade, index));
      const band = shade.bands[index];
      if (shade.product === "roman") {
        this._drawFolds(shade, top);
      } else if (shade.product === "perfectsheer") {
        this._drawCloth(shade, top);
      } else {
        band.style.top = `${round3(edge)}%`;
        band.style.height = `${round3(Math.max(0, top - edge))}%`;
      }
      shade.railEls[index].style.top = `${round3(top)}%`;
      shade.zones[index].style.top = `${round3(top + SHADE_RAIL_PCT / 2)}%`;
      edge = top + SHADE_RAIL_PCT;
    }
  }

  /**
   * Turn every louver to how open the Shutter is drawn: 0 flat (shut), 100 nearly edge-on.
   * The tilt rod rides with them, a little lower as they open.
   */
  _drawLouvers(shade) {
    const open = (this._shadeValue(shade, 0) ?? 0) / 100;
    // The side the louvers lean: the hub's own Position says when they are turned past
    // horizontal. While a drag or a sent value is showing, they turn the way the
    // integration sends them.
    const cover = this._hass?.states?.[shade.rails[0].coverId];
    const raw = cover?.attributes?.louver_position;
    const showingHub = shade.dragValues[0] === undefined && !this._pending.has(shade.rails[0].coverId);
    const lean = showingHub && typeof raw === "number" && raw < LOUVER_HORIZONTAL ? -1 : 1;
    const angle = round3(lean * open * LOUVER_OPEN_DEG);
    for (const louver of shade.louverEls) louver.style.transform = `rotateX(${angle}deg)`;
    shade.railEls[0].style.transform = `translate(-50%, ${round3(open * 6)}%)`;
    shade.element.classList.toggle("shut", open <= 0);
  }

  /**
   * Spread a drape's vanes from the side it gathers to out to its edge, evenly, and turn them
   * to how open they are. Gathered, they overlap into a stack; drawn, they close up edge to
   * edge with a little overlap, as the fabric does.
   */
  _drawDrape(shade) {
    const reach = this._drapeReach(shade, this._shadeValue(shade, 0));
    const angle = round3(this._vanesOpen(shade) * VANE_OPEN_DEG);
    for (const part of shade.parts) {
      const count = part.vanes.length;
      const width = (this._drapeSpan(shade) / count) * DRAPE_VANE_OVERLAP;
      part.vanes.forEach((vane, k) => {
        const along = ((k + 0.5) / count) * reach;
        const centre = part.side === "left" ? along : 100 - along;
        vane.style.left = `${round3(centre - width / 2)}%`;
        vane.style.width = `${round3(width)}%`;
        vane.style.transform = `rotateY(${angle}deg)`;
      });
      const edge = this._drapeEdge(part, reach);
      part.sheer.style.left = `${round3(part.side === "left" ? 0 : edge)}%`;
      part.sheer.style.width = `${round3(reach)}%`;
      part.lead.style.left = `${round3(edge)}%`;
      part.zone.style.left = `${round3(edge)}%`;
    }
    shade.element.classList.toggle("drawn", (this._shadeValue(shade, 0) ?? 0) <= 0);
  }

  _showBubble(shade, index, value) {
    const { bubble } = shade;
    if (shade.drape) {
      const part = shade.parts.find((each) => each.side === shade.activeSide) || shade.parts[0];
      bubble.textContent = this._pct(value);
      bubble.style.top = "42%";
      bubble.style.left = `${round3(this._drapeEdge(part, this._drapeReach(shade, this._shadeValue(shade, index))))}%`;
      bubble.classList.add("on");
      return;
    }
    bubble.textContent = this._pct(value);
    bubble.style.top = shade.louvers
      ? "50%"
      : `${round3(this._railTop(shade, index, this._shadeValue(shade, index)))}%`;
    bubble.style.left = `${this._tabX(shade.rails, index)}%`;
    bubble.classList.add("on");
  }

  _hideBubble(shade) {
    shade.bubble.classList.remove("on");
  }

  /**
   * What a rail's control is called for assistive technology, the same on the picture and in
   * the list: the blind's name, with the rail's on a two-rail blind and "louvers" on a
   * Shutter, so each control on the card is told apart from the others.
   */
  _railName(blind, rails, rail) {
    if (rail.louvers) return this._t("blind_louvers", { name: blind.name });
    return rails.length > 1 ? this._t("blind_rail", { name: blind.name, rail: rail.label }) : blind.name;
  }

  /** The list layout's control for one rail of `blind`: a plain range input, in 10% steps. */
  _buildSlider(blind, rails, rail) {
    const row = el("label", "slider");
    const label = el("span", "slider-label", rail.louvers || rails.length > 1 ? rail.short : this._t("position"));
    const input = el("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = String(stepOf(rail));
    input.setAttribute("aria-label", this._railName(blind, rails, rail));
    const value = el("span", "slider-value");
    // `holding` while a pointer is down on it and `keyTimer` while arrow keys are gathering a
    // move: _patchSlider leaves the slider alone for both. `keys` when a key moved it last, and
    // `keyMove` the position the keys have gathered until it is sent. `moved` once the held
    // pointer has moved it.
    const slider = { rail, row, input, value, holding: false, moved: false, keys: false, keyTimer: null, keyMove: null };
    // A blind that has gone unavailable takes no write, and its slider goes back to the hub's value.
    const send = (position) => {
      clearTimeout(slider.keyTimer);
      slider.keyTimer = null;
      slider.keyMove = null;
      if (!this._isUnavailable(blind)) this._move(rails, rails.indexOf(rail), position);
      this._patch();
    };
    input.addEventListener("pointerdown", () => {
      slider.holding = true;
      slider.moved = false;
      slider.keys = false;
      slider.pressedAt = input.value;
      // A move the keys are still gathering waits on the press, which sends it or its own.
      clearTimeout(slider.keyTimer);
      slider.keyTimer = null;
    });
    // A press can end without a `change`: a tap on the thumb, a drag back to where it began,
    // or a touch the browser takes for a scroll (pointercancel). So the hold ends however the
    // press does. A press that moved the slider has a `change` coming, which sends it in place
    // of any move the keys gathered. Any other press -- and any on a blind gone unavailable,
    // whose `change` sends nothing -- sends the keys' move if there is one, or else catches the
    // slider up with the hub at once. A drag back to where it began sends that position on a
    // rail whose move is not confirmed, as a drag of the picture does: it is the one way to
    // send the blind the position it is drawn at again (see _move).
    const release = (cancelled) => {
      if (!slider.holding) return;
      slider.holding = false;
      const unavailable = this._isUnavailable(blind);
      if (!cancelled && !unavailable && input.value !== slider.pressedAt) return;
      const resend = !cancelled && !unavailable && slider.moved && this._railState(rail).stale;
      if (slider.keyMove !== null) send(slider.keyMove);
      else if (resend) send(clampToStep(input.value, stepOf(rail)));
      else this._patchSlider(slider, unavailable);
    };
    input.addEventListener("pointerup", () => release(false));
    input.addEventListener("pointercancel", () => release(true));
    input.addEventListener("lostpointercapture", () => release(false));
    input.addEventListener("blur", () => release(false));
    // A range input fires `change` on every arrow key, so keyed changes are gathered into one
    // write as on the picture (KEY_COMMIT_MS); a pointer's is sent on release.
    input.addEventListener("keydown", () => {
      slider.keys = true;
    });
    input.addEventListener("input", () => {
      if (slider.holding) slider.moved = true;
      value.textContent = this._pct(clampToStep(input.value, stepOf(rail)));
      input.style.setProperty?.("--n-fill", `${input.value}%`);
    });
    input.addEventListener("change", () => {
      const position = clampToStep(input.value, stepOf(rail));
      slider.holding = false;
      if (!slider.keys) {
        send(position);
        return;
      }
      clearTimeout(slider.keyTimer);
      slider.keyMove = position;
      slider.keyTimer = setTimeout(() => send(position), KEY_COMMIT_MS);
    });
    row.append(label, input, value);
    return slider;
  }

  // ---- writing ---------------------------------------------------------------------

  /**
   * Draw a rail at `position` until the hub reports it as the rail's target. Past
   * PENDING_MS the hub's own value is shown again, so a move that never happened shows.
   *
   * Returns a function that takes the expectation back, for a call that failed: the rail is
   * drawn where the hub has it again, and its move window is the one it had before (see
   * _railState), so a write that never left Home Assistant does not read as a move.
   */
  _expect(rail, position) {
    const key = rail.numberId || rail.coverId;
    const entry = { value: position, at: Date.now() };
    const before = this._sent.get(key);
    this._pending.set(key, entry);
    this._sent.set(key, entry);
    setTimeout(() => {
      if (this._pending.get(key) !== entry) return;
      this._pending.delete(key);
      this._patch();
    }, PENDING_MS);
    return () => {
      if (this._pending.get(key) === entry) this._pending.delete(key);
      // Unless a later write to the rail has taken its place.
      if (this._sent.get(key) !== entry) return;
      if (before === undefined) this._sent.delete(key);
      else this._sent.set(key, before);
    };
  }

  /**
   * Write a rail position, preferring the number entity so the 10% step is enforced.
   * `undoCarried` takes back the other rail's expectation when this write carries it along.
   */
  _setRail(rail, position, undoCarried = null) {
    const undo = this._expect(rail, position);
    let call;
    if (rail.louvers) {
      call = this._hass.callService("cover", "set_cover_tilt_position", {
        entity_id: rail.coverId,
        tilt_position: position,
      });
    } else if (rail.numberId) {
      call = this._hass.callService("number", "set_value", { entity_id: rail.numberId, value: position });
    } else {
      call = this._hass.callService("cover", "set_cover_position", { entity_id: rail.coverId, position });
    }
    // A failed call is reported by Home Assistant. The picture goes back to the hub's values,
    // the carried rail's included, and the status to what it said before the write.
    Promise.resolve(call).catch(() => {
      undo();
      undoCarried?.();
      this._patch();
    });
  }

  /** Call a cover service on the rail's own entity -- never the blind's bottom rail. */
  _coverService(rail, service) {
    if (rail.coverId) this._hass.callService("cover", service, { entity_id: rail.coverId });
  }

  /**
   * Stop this blind. Its rails share one motor, so one call on a moving rail stops them all;
   * a second would only queue behind it at the hub's pace.
   */
  _stop(rails) {
    const moving = rails.find((rail) => {
      const { current, target, stale } = this._railState(rail);
      return !stale && current !== null && target !== null && Math.round(current) !== Math.round(target);
    });
    for (const rail of rails) this._pending.delete(rail.numberId || rail.coverId);
    this._coverService(moving || rails[0], "stop_cover");
    this._patch();
  }

  // ---- patching --------------------------------------------------------------------

  _patch() {
    if (!this._cells || !this._hass) return;
    const isOff = (entityId) => {
      const state = this._hass.states[entityId];
      return !state || state.state === "unavailable";
    };
    for (const chip of this._sceneChips || []) {
      const off = isOff(chip.dataset.entityId);
      if (chip.disabled !== off) chip.disabled = off;
    }
    let open = 0;
    let moving = 0;
    let lowBattery = 0;
    let settles = Infinity;

    for (const cell of this._cells) {
      const { blind, rails, shade } = cell;
      const unavailable = this._isUnavailable(blind);
      cell.tile.classList.toggle("unavailable", unavailable);

      const states = rails.map((rail) => {
        const state = this._railState(rail);
        if (state.until) settles = Math.min(settles, state.until);
        const key = rail.numberId || rail.coverId;
        const pending = this._pending.get(key);
        // The hub has taken the choice up once it reports it as the target.
        if (pending && state.target !== null && Math.round(state.target) === pending.value) {
          this._pending.delete(key);
        }
        const shown = this._railValue(rail);
        return {
          ...state,
          shown,
          moving:
            !unavailable &&
            !state.stale &&
            state.current !== null &&
            shown !== null &&
            Math.round(shown) !== Math.round(state.current),
          unconfirmed: !unavailable && Boolean(state.stale),
        };
      });

      if (shade) this._patchShade(shade, states, unavailable);
      for (const slider of cell.sliders) this._patchSlider(slider, unavailable);

      setText(cell.status, this._statusOf(rails, states, unavailable));
      const isMoving = states.some((state) => state.moving);
      const unconfirmed = states.some((state) => state.unconfirmed);
      cell.status.classList.toggle("moving", isMoving);
      cell.status.classList.toggle("rest", !isMoving && !unconfirmed && !unavailable);
      // A Shutter's louvers turn in a moment and take no stop.
      const noStop = !isMoving || Boolean(blind.louvers);
      if (cell.stop.hidden !== noStop) cell.stop.hidden = noStop;

      if (cell.batteryEl) {
        const battery = cell.batteryEl;
        const level = this._numberOf(blind.battery);
        const kind = batteryClass(level);
        if (battery.className !== `battery ${kind}`) battery.className = `battery ${kind}`;
        setAttr(battery.firstChild, "icon", batteryIcon(level));
        const shown = level === null ? "—" : this._pct(level);
        setText(battery.lastChild, shown);
        const title = level === null ? this._t("battery_unknown") : this._t("battery", { value: shown });
        if (battery.title !== title) battery.title = title;
        setAttr(battery, "aria-label", title);
        if (kind === "low" || kind === "critical") lowBattery += 1;
      }
      if (cell.refreshEl) {
        // Greyed out while the blind's Request status button is unavailable, as it is with the blind.
        const off = isOff(blind.refresh);
        if (cell.refreshEl.disabled !== off) cell.refreshEl.disabled = off;
      }

      if ((states[0].shown ?? 0) > 0) open += 1;
      if (isMoving) moving += 1;
    }

    this._patchSummary(this._cells.length, open, moving, lowBattery);

    // Redraw when the next move window closes, even if no state changes by then: a blind that
    // missed its move should stop reading "Closing" on time, not at the next update.
    clearTimeout(this._settleTimer);
    this._settleTimer = Number.isFinite(settles)
      ? setTimeout(() => this._patch(), Math.max(0, settles - Date.now()) + 100)
      : null;
  }

  _patchShade(shade, states, unavailable) {
    shade.disabled = unavailable;
    shade.element.classList.toggle("disabled", unavailable);
    this._drawShade(shade);
    if (shade.drape) {
      // One rail, drawn at a leading edge per side: each side gets the marker and the state.
      const [state] = states;
      const showMarker = (state.moving || state.unconfirmed) && shade.dragValues[0] === undefined;
      const reach = showMarker ? this._drapeReach(shade, state.current) : 0;
      const value = Math.round(this._shadeValue(shade, 0) ?? 0);
      for (const part of shade.parts) {
        part.marker.classList.toggle("on", showMarker);
        if (showMarker) part.marker.style.left = `${round3(this._drapeEdge(part, reach))}%`;
        part.lead.classList.toggle("moving", state.moving);
        this._sayValue(part.zone, value);
        setAttr(part.zone, "aria-disabled", String(unavailable));
      }
      return;
    }
    states.forEach((state, index) => {
      const held = shade.dragValues[index] !== undefined;
      const marker = shade.markers[index];
      const showMarker = (state.moving || state.unconfirmed) && !held && !shade.louvers;
      marker.classList.toggle("on", showMarker);
      if (showMarker) {
        marker.style.top = `${round3(this._railTop(shade, index, state.current) + SHADE_RAIL_PCT / 2)}%`;
      }
      shade.railEls[index].classList.toggle("moving", state.moving);
      const zone = shade.zones[index];
      this._sayValue(zone, Math.round(this._shadeValue(shade, index) ?? 0));
      setAttr(zone, "aria-disabled", String(unavailable));
    });
  }

  /** Where a rail's grab zone says the rail is, to assistive technology. */
  _sayValue(zone, value) {
    setAttr(zone, "aria-valuenow", String(value));
    setAttr(zone, "aria-valuetext", this._t("percent_open", { value }));
  }

  _patchSlider(slider, unavailable) {
    const { rail, input, value } = slider;
    // Nothing changes under a pointer that holds the slider -- not even `disabled`, as Chromium
    // fires `change` on a held range input it disables, which would send the half-dragged value.
    // The press's end patches it (_buildSlider).
    if (slider.holding) return;
    if (input.disabled !== unavailable) input.disabled = unavailable;
    if (slider.keyTimer) return;
    const shown = this._railValue(rail);
    const position = String(clampToStep(shown ?? 0, stepOf(rail)));
    if (input.value !== position) input.value = position;
    const fill = `${shown ?? 0}%`;
    if (input.style.getPropertyValue?.("--n-fill") !== fill) input.style.setProperty?.("--n-fill", fill);
    setText(value, shown === null ? "—" : this._pct(shown));
  }

  /**
   * A blind's state in a few words. At rest: "Open", "Closed", "60% open" -- or, on a
   * two-rail blind, "Privacy" for the app's preset and both rails otherwise. On the move:
   * which way, and where it has got to.
   */
  _statusOf(rails, states, unavailable) {
    if (unavailable) return this._t("unavailable");
    const travelling = states.findIndex((state) => state.moving);
    if (travelling >= 0) {
      const { current, shown } = states[travelling];
      const verb = shown > current ? "opening" : "closing";
      const value = Math.round(current);
      return rails.length > 1
        ? this._t(`${verb}_rail`, { rail: rails[travelling].short, value })
        : this._t(verb, { value });
    }
    // Drawn where it was sent, with the marker where the hub last heard it.
    if (states.some((state) => state.unconfirmed)) return this._t("unconfirmed");
    const [bottom, middle] = states.map((state) => (state.shown === null ? null : Math.round(state.shown)));
    if (bottom === null) return this._t("position_unknown");
    if (rails.length < 2 || middle === null) {
      if (bottom >= 100) return this._t("open");
      if (bottom <= 0) return this._t("closed");
      return this._t("percent_open", { value: bottom });
    }
    if (bottom >= 100 && middle >= 100) return this._t("open");
    if (bottom <= 0 && middle <= 0) return this._t("closed");
    if (bottom <= 0 && middle >= 100) return this._t("privacy");
    return this._t("two_rails", { middle_rail: rails[1].short, middle, bottom_rail: rails[0].short, bottom });
  }

  _patchSummary(total, open, moving, lowBattery) {
    const summary = this._summary;
    if (!summary) return;
    const parts = [[this._t("shades", { count: total }), ""]];
    if (total) {
      if (open === 0) parts.push([this._t("all_closed"), ""]);
      else if (open === total) parts.push([this._t(total === 1 ? "one_open" : "all_open"), ""]);
      else parts.push([this._t("some_open", { count: open }), ""]);
    }
    if (moving) parts.push([this._t("moving", { count: moving }), "live"]);
    if (lowBattery) parts.push([this._t("low_battery", { count: lowBattery }), "warn"]);

    const key = parts.map((part) => part.join(":")).join("|");
    if (summary.dataset.key === key) return;
    summary.dataset.key = key;
    summary.innerHTML = "";
    parts.forEach(([text, kind], index) => {
      if (index) summary.appendChild(el("span", "sep", " · "));
      summary.appendChild(el("span", kind || null, text));
    });
  }

  _showMore(entityId) {
    if (!entityId) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId };
    this.dispatchEvent(event);
  }
}

/**
 * The visual editor. Home Assistant's own form when it is available, so the options look
 * like every other card's; plain inputs otherwise.
 */
const EDITOR_FIELDS = [
  { key: "title", label: "editor_title", type: "text" },
  { key: "config_entry_id", label: "editor_hub", type: "entry" },
  { key: "hide_picture", label: "editor_hide_picture", type: "boolean" },
  { key: "hide_battery", label: "editor_hide_battery", type: "boolean" },
  { key: "hide_room_names", label: "editor_hide_room_names", type: "boolean" },
  { key: "hide_room_controls", label: "editor_hide_room_controls", type: "boolean" },
  { key: "hide_room_presets", label: "editor_hide_room_presets", type: "boolean" },
  { key: "hide_home_controls", label: "editor_hide_home_controls", type: "boolean" },
  { key: "hide_refresh", label: "editor_hide_refresh", type: "boolean" },
];

class NormanShadesCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    // Home Assistant hands the editor its config back after every change it reports, and the
    // title field reports one per keystroke. Rebuilding the form would take the focus out of
    // the field being typed in, so a form already drawn is only given the new values.
    if (this._form) this._form.data = this._config;
    else this._render();
  }

  set hass(hass) {
    const language = languageOf(hass);
    const changed = this._config !== undefined && language !== languageOf(this._hass);
    this._hass = hass;
    // The labels are in the user's language, which is only known once hass arrives.
    if (changed) this._render();
    else if (this._form) this._form.hass = hass;
  }

  _label(field) {
    return translate(languageOf(this._hass), field.label);
  }

  /**
   * Report a changed config, without the options left empty or turned off: the card's
   * defaults. A blank title is kept unless it is the title field that was just emptied --
   * `title: ""` set in YAML is a heading left blank on purpose, which a change to another
   * option must not turn back into the hub's name.
   */
  _changed(config) {
    const next = { ...config };
    for (const { key } of EDITOR_FIELDS) {
      if (key === "title" && next.title === "" && this._config?.title === "") continue;
      if (next[key] === "" || next[key] === false) delete next[key];
    }
    this._config = next;
    this.dispatchEvent(
      new CustomEvent("config-changed", { detail: { config: next }, bubbles: true, composed: true }),
    );
  }

  _render() {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = "";

    if (customElements.get("ha-form")) {
      const form = document.createElement("ha-form");
      form.hass = this._hass;
      form.data = this._config;
      const selectors = {
        boolean: { boolean: {} },
        entry: { config_entry: { integration: DOMAIN } },
        text: { text: {} },
      };
      form.schema = EDITOR_FIELDS.map(({ key, type }) => ({ name: key, selector: selectors[type] }));
      const labels = Object.fromEntries(EDITOR_FIELDS.map((field) => [field.key, this._label(field)]));
      form.computeLabel = (field) => labels[field.name] || field.name;
      form.addEventListener("value-changed", (event) => this._changed(event.detail.value));
      this._form = form;
      this.shadowRoot.appendChild(form);
      return;
    }

    // ha-form is loaded lazily by the dashboard editor; redraw with it once it arrives.
    customElements.whenDefined?.("ha-form").then(() => this._render());
    const wrap = document.createElement("div");
    wrap.style.padding = "8px 0";
    for (const field of EDITOR_FIELDS) {
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:8px;padding:6px 0;";
      const text = document.createElement("span");
      text.textContent = this._label(field);
      text.style.flex = "1";
      const input = document.createElement("input");
      input.type = field.type === "boolean" ? "checkbox" : "text";
      if (field.type === "boolean") input.checked = Boolean(this._config[field.key]);
      else input.value = this._config[field.key] ?? "";
      input.addEventListener("change", () => {
        const value = field.type === "boolean" ? input.checked : input.value;
        this._changed({ ...this._config, [field.key]: value });
      });
      row.append(text, input);
      wrap.appendChild(row);
    }
    this.shadowRoot.appendChild(wrap);
  }
}

if (!customElements.get("norman-shades-card")) {
  customElements.define("norman-shades-card", NormanShadesCard);
}
if (!customElements.get("norman-shades-card-editor")) {
  customElements.define("norman-shades-card-editor", NormanShadesCardEditor);
}

// Register in the dashboard's "Add card" picker. There is no hass yet, so the page's language
// (Home Assistant sets it to the user's) picks the words.
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "norman-shades-card")) {
  const language = languageOf(null);
  window.customCards.push({
    type: "norman-shades-card",
    name: translate(language, "card_name"),
    description: translate(language, "card_description"),
    preview: true,
    documentationURL: "https://github.com/kedube/ha-norman/blob/main/docs/dashboard.md",
  });
}

// The loaded build, in the browser console. This is the only place a version mismatch is
// visible from the browser side: if this does not match the integration version on the
// Norman device page, the browser is running a cached copy of an older card.
console.info(
  `%c NORMAN-SHADES-CARD %c v${CARD_VERSION} `,
  "color: #fff; background: #4a6572; font-weight: 700;",
  "color: #4a6572; background: #fff; font-weight: 700;"
);
