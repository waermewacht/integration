/*
 * Wärmewacht cards: the figures of one heat pump in small cards per topic,
 * without extra cards from HACS. Served and registered by the integration
 * itself (no Lovelace resource to add). A card finds its entities by device
 * and translation key, so the language of Home Assistant and renamed entity
 * ids do not matter; states are formatted by Home Assistant (locale, unit,
 * translated states).
 *
 *   type: custom:waermewacht-ratios-card   (… -now-, -health-, -cycling-,
 *         -dhw-, -costs-, -hybrid-, -analysis-, -months-card)
 *   device_id: <optional: the only Wärmewacht device otherwise>
 *   title: <optional; a single space hides the heading>
 *
 *   type: custom:waermewacht-boiler-card  (a gas or oil boiler entry)
 *
 *   type: custom:waermewacht-card        (all topics in one card)
 *   sections: [now, ratios, health, cycling, dhw, costs, hybrid, analysis, months]
 *
 * Two kinds of devices: heat pumps (all topics but "boiler") and gas or oil
 * boilers before the switch (only "boiler"). A card shows the kind its
 * topics are for; the card with all topics follows the chosen device.
 */

// The integration loads the file with "?v=<version>" (cards.py).
const CARD_VERSION = new URL(import.meta.url).searchParams.get("v") || "dev";
const DOMAIN = "waermewacht";
const TOPICS = ["now", "ratios", "health", "cycling", "dhw", "costs", "hybrid", "analysis", "months", "boiler"];
const WIDE = new Set(["ratios", "analysis", "months", "boiler"]);
// Thresholds of the energy signature (heat_load.py), for "2 of 8 weeks".
const SIGNATURE_NEEDS = { weeks: 8, spread: 10, frost_days: 5 };

const TEXT = {
  de: {
    noDevice: "Kein Wärmewacht-Gerät gefunden.",
    onlyBoiler: "Diese Karte zeigt Wärmepumpen. Für eine Gas- oder Ölheizung gibt es die Karte „Wärmewacht Gas- und Ölheizung“.",
    onlyPump: "Diese Karte zeigt eine Gas- oder Ölheizung. Für Wärmepumpen gibt es die übrigen Wärmewacht-Karten.",
    nothing: "Keine Daten für diese Karte.",
    topics: {
      now: "Jetzt",
      ratios: "Arbeitszahlen",
      health: "Gesundheit",
      cycling: "Takte",
      dhw: "Warmwasser",
      costs: "Kosten",
      hybrid: "Hybridanlage",
      analysis: "Kennlinie und Heizlast",
      months: "Wärme und Strom je Monat",
      boiler: "Gas- und Ölheizung",
    },
    describe: {
      now: "Betriebsart, Kompressor und Temperaturen der Wärmepumpe.",
      ratios: "Arbeitszahlen heute, Monat, Saison und gesamt als Tabelle.",
      health: "Befunde des Gesundheits-Checks mit Kennzahl.",
      cycling: "Starts, Laufzeiten, Abtauungen und Spreizung.",
      dhw: "Letzte Warmwasserladung und die Ladungen der letzten 30 Tage.",
      costs: "Stromkosten, Wärmekosten und Ersparnis gegenüber Gas.",
      hybrid: "Anteil der Wärmepumpe und Wärme des Kessels (Hybridanlage).",
      analysis: "AZ-Kennlinie, Energiesignatur und Heizlast.",
      months: "Wärme und Strom je Monat mit Arbeitszahl, aus der Langzeitstatistik.",
      boiler: "Heizlast, Heizgrenze, Energiesignatur und Kosten einer Gas- oder Ölheizung vor dem Umstieg.",
      all: "Alle Themen in einer Karte.",
    },
    periods: { today: "Heute", month: "Monat", season: "Saison", total: "Gesamt" },
    scopes: { heating: "Heizen", dhw: "Warmwasser", combined: "beides", cooling: "Kühlen" },
    checks: {
      efficiency_drop: "Effizienz",
      aux_mild_weather: "Heizstab bei milder Witterung",
      aux_dhw_charges: "Heizstab bei Warmwasser",
      dhw_efficiency_drop: "Warmwasser gegen Vorjahr",
      cycling_problem: "Takten",
    },
    tiles: {
      activity: "Betriebsart",
      compressor: "Kompressor",
      outdoor_temp: "Außen",
      flow_temp: "Vorlauf",
      return_temp: "Rücklauf",
      dhw_temp: "Speicher",
      heat_power: "Wärme",
      electric_power: "Strom",
      starts_today: "Starts heute",
      runtime_today: "Laufzeit heute",
      run_minutes_today: "Laufzeit je Start",
      shortest_pause_today: "Kürzeste Pause",
      short_runs_today: "Kurzläufe",
      defrosts_today: "Abtauungen heute",
      spread_7d: "Spreizung 7 Tage",
      starts_season: "Starts Saison",
      run_minutes_week: "Lauf/Start 7 Tage",
      standby_power_7d: "Stillstand 7 Tage",
      ratio_dhw_last_charge: "Letzte Ladung",
      ratio_dhw_charges_30d: "Ladungen 30 Tage",
      cost_month: "Strom Monat",
      cost_season: "Strom Saison",
      heat_cost_season: "Je kWh Wärme",
      gas_savings_season: "Ersparnis Gas",
      heat_pump_share_month: "Anteil WP Monat",
      heat_pump_share_season: "Anteil WP Saison",
      boiler_heat_heating: "Kessel Heizen",
      boiler_heat_dhw: "Kessel Warmwasser",
      heat_load_per_kelvin: "Heizlast je Kelvin",
      heat_load_design: "Heizlast Norm",
      heating_limit: "Heizgrenze",
      heat_per_degree_day_season: "Wärme je Gradtag",
      flow_at_zero: "Vorlauf bei 0 °C",
      oversize_factor: "Leistung/Heizlast",
      gas_heat_load_per_kelvin: "Heizlast je Kelvin",
      gas_heat_load_design: "Heizlast Norm",
      gas_heating_limit: "Heizgrenze",
      gas_heat_per_degree_day: "Wärme je Gradtag",
      gas_flow_at_zero: "Vorlauf bei 0 °C",
      gas_flow_at_design: "Vorlauf Normaußentemp.",
      gas_dhw_share: "Warmwasseranteil",
      gas_consumption_year: "Gas 365 Tage",
      oil_consumption_year: "Heizöl 365 Tage",
      gas_cost_year: "Gaskosten",
      oil_cost_year: "Ölkosten",
    },
    progress: {
      weeks: (have, need) => `${have} von ${need} Wochen`,
      spread: (have, need) => `Spanne ${have} von ${need} K`,
      frost_days: (have, need) => `${have} von ${need} Frosttagen`,
    },
    preliminaryLine: "Gerade (vorläufig)",
    preliminaryValue: (v) => `vorläufig ${v}`,
    litres: (v) => `${v} Liter`,
    days: (n) => `erst ${n} Tage`,
    since: (v) => `seit ${v}`,
    perDay: (v) => `${v} je Tag`,
    times: (n, m) => `${n}-mal · Ø ${m} min`,
    charges: (n, m) => `${n}× · Ø ${m} min`,
    withDhw: (v) => `mit Warmwasser ${v} %`,
    previous: "Vorsaison",
    curve: "AZ-Kennlinie Heizen",
    signature: "Energiesignatur",
    current: "Laufende Saison",
    previousSeason: "Vorsaison",
    weeks: "Wochen",
    line: "Gerade",
    heat: "Wärme",
    electricity: "Strom",
    standby: "Stillstand",
    ratio: "AZ",
    noStatistics: "Noch keine Langzeitstatistik.",
    detail: {
      efficiency_drop: (a, n) => `AZ Heizen ${n(a.ratio_current, 2)} statt ${n(a.ratio_previous_same_weather, 2)}`,
      aux_mild_weather: (a, n) => `${n(a.aux_kwh_7d, 1)} kWh in 7 Tagen${a.aux_kwh_defrost_7d > 0 ? ` · beim Abtauen ${n(a.aux_kwh_defrost_7d, 1)} kWh` : ""}`,
      aux_dhw_charges: (a, n) => `${n(a.aux_share, 1)} % · ${n(a.aux_kwh, 2)} kWh in 30 Tagen${a.aux_kwh_defrost > 0 ? ` · beim Abtauen ${n(a.aux_kwh_defrost, 2)} kWh` : ""}`,
      dhw_efficiency_drop: (a, n) => `AZ ${n(a.ratio, 2)} statt ${n(a.previous_ratio, 2)}`,
      cycling_problem: (a, n) => `max. ${n(a.max_starts_per_hour, 0)} Starts/h · ${n(a.short_runs_24h, 0)} Kurzläufe`,
    },
    fine: "In Ordnung",
    problem: "Auffällig",
    unknown: "Unbekannt",
    reasons: {
      not_analysed_yet: "Noch nicht ausgewertet",
      no_previous_season: "Noch keine Vorsaison",
      no_previous_year: "Noch kein Vorjahr",
      too_few_classes: "Zu wenig vergleichbares Wetter",
      too_few_days: "Zu wenige Tage",
      too_little_electricity: "Zu wenig Strom",
      too_few_charges: "Zu wenige Ladungen",
      comparison_restarted: "Vergleich neu gestartet",
      no_aux_counter: "Kein Heizstab-Zähler",
      no_outdoor_temp: "Keine Außentemperatur",
      too_few_weeks: "Zu wenige kalte Wochen",
      spread_too_small: "Zu wenig Temperaturspanne",
      too_few_frost_days: "Zu wenige Frosttage",
      slope_not_negative: "Kein Zusammenhang mit draußen",
      no_summer_days: "Noch keine Sommertage",
      heating_only: "Zähler nur Heizen",
      flow_needs_dhw_counter: "Braucht Warmwasser-Zähler",
      no_recorder: "Recorder fehlt",
      gas_unit: "Einheit des Zählers",
      no_calorific_value: "Brennwert fehlt",
      too_few_periods: "Zu wenige Ablesungen",
    },
    editor: {
      device_id: "Wärmepumpe (Wärmewacht-Gerät)",
      device_boiler: "Heizung (Wärmewacht-Gerät)",
      device_any: "Wärmewacht-Gerät",
      title: "Überschrift (leer: Thema, nur ein Leerzeichen: keine)",
      sections: "Themen (leer: alle)",
      heat_power: "Wärmeleistung (optional)",
      electric_power: "Elektrische Leistung (optional)",
    },
  },
  en: {
    noDevice: "No Wärmewacht device found.",
    onlyBoiler: "This card shows heat pumps. For a gas or oil boiler there is the card “Wärmewacht gas and oil boiler”.",
    onlyPump: "This card shows a gas or oil boiler. For heat pumps there are the other Wärmewacht cards.",
    nothing: "No data for this card.",
    topics: {
      now: "Now",
      ratios: "Performance factors",
      health: "Health",
      cycling: "Cycling",
      dhw: "Hot water",
      costs: "Costs",
      hybrid: "Hybrid system",
      analysis: "Performance curve and heat load",
      months: "Heat and electricity per month",
      boiler: "Gas and oil boiler",
    },
    describe: {
      now: "Activity, compressor and temperatures of the heat pump.",
      ratios: "Performance factors today, month, season and total as a table.",
      health: "Findings of the health check with their figure.",
      cycling: "Starts, run times, defrosts and spread.",
      dhw: "Last hot water charge and the charges of the last 30 days.",
      costs: "Electricity cost, heat cost and savings against gas.",
      hybrid: "Heat pump share and boiler heat (hybrid system).",
      analysis: "Performance curve, energy signature and heat load.",
      months: "Heat and electricity per month with performance factor, from the long-term statistics.",
      boiler: "Heat load, heating limit, energy signature and costs of a gas or oil boiler before the switch.",
      all: "All topics in one card.",
    },
    periods: { today: "Today", month: "Month", season: "Season", total: "Total" },
    scopes: { heating: "Heating", dhw: "Hot water", combined: "both", cooling: "Cooling" },
    checks: {
      efficiency_drop: "Efficiency",
      aux_mild_weather: "Backup heater on mild days",
      aux_dhw_charges: "Backup heater for hot water",
      dhw_efficiency_drop: "Hot water against last year",
      cycling_problem: "Cycling",
    },
    tiles: {
      activity: "Activity",
      compressor: "Compressor",
      outdoor_temp: "Outdoor",
      flow_temp: "Flow",
      return_temp: "Return",
      dhw_temp: "Storage",
      heat_power: "Heat",
      electric_power: "Electricity",
      starts_today: "Starts today",
      runtime_today: "Run time today",
      run_minutes_today: "Run time per start",
      shortest_pause_today: "Shortest pause",
      short_runs_today: "Short runs",
      defrosts_today: "Defrosts today",
      spread_7d: "Spread 7 days",
      starts_season: "Starts season",
      run_minutes_week: "Run/start 7 days",
      standby_power_7d: "Standby 7 days",
      ratio_dhw_last_charge: "Last charge",
      ratio_dhw_charges_30d: "Charges 30 days",
      cost_month: "Electricity month",
      cost_season: "Electricity season",
      heat_cost_season: "Per kWh of heat",
      gas_savings_season: "Savings vs. gas",
      heat_pump_share_month: "Heat pump share month",
      heat_pump_share_season: "Heat pump share season",
      boiler_heat_heating: "Boiler heating",
      boiler_heat_dhw: "Boiler hot water",
      heat_load_per_kelvin: "Heat load per kelvin",
      heat_load_design: "Design heat load",
      heating_limit: "Heating limit",
      heat_per_degree_day_season: "Heat per degree day",
      flow_at_zero: "Flow at 0 °C",
      oversize_factor: "Power/heat load",
      gas_heat_load_per_kelvin: "Heat load per kelvin",
      gas_heat_load_design: "Design heat load",
      gas_heating_limit: "Heating limit",
      gas_heat_per_degree_day: "Heat per degree day",
      gas_flow_at_zero: "Flow at 0 °C",
      gas_flow_at_design: "Flow at design temp.",
      gas_dhw_share: "Hot water share",
      gas_consumption_year: "Gas 365 days",
      oil_consumption_year: "Heating oil 365 days",
      gas_cost_year: "Gas cost",
      oil_cost_year: "Oil cost",
    },
    progress: {
      weeks: (have, need) => `${have} of ${need} weeks`,
      spread: (have, need) => `spread ${have} of ${need} K`,
      frost_days: (have, need) => `${have} of ${need} frost days`,
    },
    preliminaryLine: "Line (preliminary)",
    preliminaryValue: (v) => `preliminary ${v}`,
    litres: (v) => `${v} litres`,
    days: (n) => `only ${n} days`,
    since: (v) => `since ${v}`,
    perDay: (v) => `${v} per day`,
    times: (n, m) => `${n} times · mean ${m} min`,
    charges: (n, m) => `${n}× · mean ${m} min`,
    withDhw: (v) => `with hot water ${v} %`,
    previous: "previous season",
    curve: "Performance curve heating",
    signature: "Energy signature",
    current: "Current season",
    previousSeason: "Previous season",
    weeks: "Weeks",
    line: "Line",
    heat: "Heat",
    electricity: "Electricity",
    standby: "Standby",
    ratio: "COP",
    noStatistics: "No long-term statistics yet.",
    detail: {
      efficiency_drop: (a, n) => `COP heating ${n(a.ratio_current, 2)} instead of ${n(a.ratio_previous_same_weather, 2)}`,
      aux_mild_weather: (a, n) => `${n(a.aux_kwh_7d, 1)} kWh in 7 days${a.aux_kwh_defrost_7d > 0 ? ` · in defrosts ${n(a.aux_kwh_defrost_7d, 1)} kWh` : ""}`,
      aux_dhw_charges: (a, n) => `${n(a.aux_share, 1)} % · ${n(a.aux_kwh, 2)} kWh in 30 days${a.aux_kwh_defrost > 0 ? ` · in defrosts ${n(a.aux_kwh_defrost, 2)} kWh` : ""}`,
      dhw_efficiency_drop: (a, n) => `COP ${n(a.ratio, 2)} instead of ${n(a.previous_ratio, 2)}`,
      cycling_problem: (a, n) => `max. ${n(a.max_starts_per_hour, 0)} starts/h · ${n(a.short_runs_24h, 0)} short runs`,
    },
    fine: "Fine",
    problem: "Conspicuous",
    unknown: "Unknown",
    reasons: {
      not_analysed_yet: "Not analysed yet",
      no_previous_season: "No previous season yet",
      no_previous_year: "No previous year yet",
      too_few_classes: "Too little comparable weather",
      too_few_days: "Too few days",
      too_little_electricity: "Too little electricity",
      too_few_charges: "Too few charges",
      comparison_restarted: "Comparison restarted",
      no_aux_counter: "No backup heater meter",
      no_outdoor_temp: "No outdoor temperature",
      too_few_weeks: "Too few cold weeks",
      spread_too_small: "Too little temperature spread",
      too_few_frost_days: "Too few frost days",
      slope_not_negative: "No link to the outdoor temperature",
      no_summer_days: "No summer days yet",
      heating_only: "Heating-only meter",
      flow_needs_dhw_counter: "Needs a hot water meter",
      no_recorder: "No recorder",
      gas_unit: "Unit of the meter",
      no_calorific_value: "Calorific value missing",
      too_few_periods: "Too few readings",
    },
    editor: {
      device_id: "Heat pump (Wärmewacht device)",
      device_boiler: "Boiler (Wärmewacht device)",
      device_any: "Wärmewacht device",
      title: "Heading (empty: topic, a single space: none)",
      sections: "Topics (empty: all)",
      heat_power: "Heat power (optional)",
      electric_power: "Electric power (optional)",
    },
  },
};

const CHECKS = ["efficiency_drop", "aux_mild_weather", "aux_dhw_charges", "dhw_efficiency_drop", "cycling_problem"];
const RATIO_SCOPES = ["heating", "dhw", "combined", "cooling"];
const RATIO_PERIODS = ["today", "month", "season", "total"];
const ICONS = {
  now: "mdi:heat-pump",
  ratios: "mdi:speedometer",
  health: "mdi:stethoscope",
  cycling: "mdi:sync",
  dhw: "mdi:water-boiler",
  costs: "mdi:currency-eur",
  hybrid: "mdi:fire",
  analysis: "mdi:chart-bell-curve-cumulative",
  months: "mdi:chart-bar",
  boiler: "mdi:radiator",
};
const COLORS = {
  current: "#DE5E32",
  previous: "#2F6FB0",
  heat: "#DE5E32",
  heatDhw: "#F2A383",
  elec: "#2F6FB0",
  elecDhw: "#8DB3DD",
  standby: "#9AA0A6",
};
// Own energy sensors for the months (translation keys).
const MONTH_KEYS = ["heat_heating", "heat_dhw", "electricity_heating", "electricity_dhw", "standby"];

const STYLE = `
  :host { display: block; }
  ha-card { padding: 16px; height: 100%; box-sizing: border-box; }
  .head { display: flex; align-items: center; gap: 8px; margin: 0 0 12px; font-size: 16px; font-weight: 500;
    color: var(--primary-text-color); }
  .head ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .head .device { margin-left: auto; font-size: 12px; font-weight: 400; color: var(--secondary-text-color); }
  section + section { margin-top: 16px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
  .tile { border: 1px solid var(--divider-color); border-radius: 12px; padding: 8px 12px; cursor: pointer; min-width: 0; }
  .tile:hover, .row:hover, td.link:hover, .chart:hover { background: var(--secondary-background-color); }
  .tile .label { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
  .tile .value { font-size: 16px; font-weight: 500; color: var(--primary-text-color); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .tile .extra { font-size: 12px; color: var(--secondary-text-color); }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { padding: 6px 4px; text-align: right; border-bottom: 1px solid var(--divider-color); color: var(--primary-text-color); }
  th { font-weight: 500; color: var(--secondary-text-color); }
  th:first-child, td:first-child { text-align: left; }
  td.link { cursor: pointer; }
  .wrap { overflow-x: auto; }
  .row { display: flex; align-items: center; gap: 12px; padding: 6px 4px; border-radius: 8px; cursor: pointer; }
  .dot { flex: none; width: 12px; height: 12px; border-radius: 50%; background: var(--disabled-color, #bdbdbd); }
  .dot.ok { background: var(--success-color, #43a047); }
  .dot.problem { background: var(--error-color, #db4437); }
  .row .name { font-weight: 500; color: var(--primary-text-color); }
  .row .text { font-size: 13px; color: var(--secondary-text-color); }
  .chart { border-radius: 8px; cursor: pointer; min-width: 0; }
  .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
  .charts + .grid { margin-top: 16px; }
  .chart svg { max-width: 560px; margin: 0 auto; }
  .chart.months svg { max-width: 900px; }
  .chart .caption { font-size: 13px; font-weight: 500; color: var(--primary-text-color); margin-bottom: 4px; }
  svg { width: 100%; height: auto; display: block; overflow: visible; }
  svg text { font-size: 10px; fill: var(--secondary-text-color); }
  svg .axis { stroke: var(--divider-color); stroke-width: 1; }
  svg .hit { fill: transparent; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
  .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    margin-right: 4px; vertical-align: -1px; background: var(--c); }
  .empty { color: var(--secondary-text-color); font-size: 14px; }
`;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** A round axis step (1, 2 or 5 times a power of ten) of at least `raw`. */
function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw - 1e-9);
}

/** Decimals that show an axis step exactly. */
function stepDigits(step) {
  return Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
}

// {pump: {device id: {translation key: entity id}}, boiler: {…}}: Wärmewacht's
// heat pumps and its gas or oil boiler entries, computed once per registry
// object.
const INDEX = new WeakMap();
const HEAT_PUMP_KEY = /^(ratio_|starts_|heat_heating$|electricity_heating$)/;
const BOILER_KEY = /^(gas|oil)_consumption_year$/;
function index(hass) {
  const entities = hass.entities || {};
  let found = INDEX.get(entities);
  if (!found) {
    const byDevice = {};
    for (const entry of Object.values(entities)) {
      if (entry.platform === DOMAIN && entry.device_id && entry.translation_key) {
        (byDevice[entry.device_id] ||= {})[entry.translation_key] = entry.entity_id;
      }
    }
    found = { pump: {}, boiler: {} };
    for (const [deviceId, keys] of Object.entries(byDevice)) {
      const names = Object.keys(keys);
      if (names.some((k) => HEAT_PUMP_KEY.test(k))) found.pump[deviceId] = keys;
      else if (names.some((k) => BOILER_KEY.test(k))) found.boiler[deviceId] = keys;
    }
    INDEX.set(entities, found);
  }
  return found;
}

/** Entities of one Wärmewacht device: {translation key: entity id}. */
function deviceEntities(hass, deviceId) {
  const found = index(hass);
  return found.pump[deviceId] || found.boiler[deviceId] || {};
}

/** "pump", "boiler" or undefined (no Wärmewacht device, or still starting). */
function deviceKind(hass, deviceId) {
  const found = index(hass);
  return found.pump[deviceId] ? "pump" : found.boiler[deviceId] ? "boiler" : undefined;
}

function wwDevices(hass, kind = "pump") {
  return Object.keys(index(hass)[kind]);
}

/** The kind of device a topic is for. */
function topicKind(topic) {
  return topic === "boiler" ? "boiler" : "pump";
}

// Cards on the page: re-rendered when data they wait for arrive.
const CARDS = new Set();
function renderAll() {
  for (const card of CARDS) {
    card._states = null;
    card._render();
  }
}

// Source entities per device (activity, temperatures). Asked again after
// RETRY_MS on an error (entry still starting) and when the registry changes.
const SOURCES = new Map();
const RETRY_MS = 30000;
function sources(hass, deviceId) {
  const known = SOURCES.get(deviceId);
  const fresh = known && known.entities === hass.entities && (known.value || Date.now() - known.at < RETRY_MS);
  if (!fresh && !known?.loading) {
    SOURCES.set(deviceId, { loading: true, value: known?.value, entities: hass.entities, at: Date.now() });
    hass.callWS({ type: "waermewacht/sources", device_id: deviceId })
      .then((result) => SOURCES.set(deviceId, { value: result.entities || {}, entities: hass.entities, at: Date.now() }))
      .catch(() => SOURCES.set(deviceId, { value: null, entities: hass.entities, at: Date.now() }))
      .finally(renderAll);
  }
  return SOURCES.get(deviceId)?.value;
}

class WaermewachtCard extends HTMLElement {
  connectedCallback() {
    CARDS.add(this);
  }

  disconnectedCallback() {
    CARDS.delete(this);
  }

  /** The one topic of a topic card (subclass); null for the card with all. */
  _fixedTopic() {
    return null;
  }

  /** The kind of device this card shows: a topic card its topic's, the card
   * with all topics the chosen device's (else heat pumps, if there are). */
  _kind() {
    const topic = this._fixedTopic();
    if (topic) return topicKind(topic);
    if (!this._hass) return "pump";
    const chosen = this._config?.device_id && deviceKind(this._hass, this._config.device_id);
    if (chosen) return chosen;
    return wwDevices(this._hass, "pump").length || !wwDevices(this._hass, "boiler").length ? "pump" : "boiler";
  }

  /** The topics of this card: a topic card its one, the card with all the
   * chosen ones (or all) for its kind of device. */
  _topics() {
    const topic = this._fixedTopic();
    if (topic) return [topic];
    const wanted = this._config?.sections;
    const chosen = Array.isArray(wanted) && wanted.length ? wanted.filter((s) => TOPICS.includes(s)) : TOPICS;
    const kind = this._kind();
    return chosen.filter((s) => topicKind(s) === kind);
  }

  setConfig(config) {
    if (config.sections !== undefined && !Array.isArray(config.sections)) {
      throw new Error("sections must be a list");
    }
    this._config = { ...config };
    this._states = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Render only when one of the card's entities (state objects are
    // replaced on every change) or the language changed.
    const ids = this._watched();
    const states = ids.map((id) => hass.states[id]);
    if (this._states && states.length === this._states.length && states.every((s, i) => s === this._states[i])
      && this._lang === hass.locale?.language) {
      return;
    }
    this._states = states;
    this._lang = hass.locale?.language;
    this._render();
  }

  getCardSize() {
    return 4 * Math.max(1, this._topics().length);
  }

  getGridOptions() {
    // Sections view: 12 columns are the section's full width (a section is
    // one column of the view; analysis and months like more room).
    return { columns: "full", min_columns: 6 };
  }

  static getConfigElement() {
    return document.createElement("waermewacht-card-editor");
  }

  static getStubConfig(hass) {
    const devices = [...wwDevices(hass, "pump"), ...wwDevices(hass, "boiler")];
    return devices.length > 1 ? { device_id: devices[0] } : {};
  }

  _deviceId() {
    return this._config?.device_id || wwDevices(this._hass, this._kind())[0];
  }

  _watched() {
    if (!this._hass || !this._config) return [];
    const deviceId = this._deviceId();
    if (!deviceId) return [];
    const ids = Object.values(deviceEntities(this._hass, deviceId));
    if (this._topics().includes("now")) {
      ids.push(...Object.values(SOURCES.get(deviceId)?.value || {}));
      for (const key of ["heat_power", "electric_power"]) if (this._config[key]) ids.push(this._config[key]);
    }
    return ids;
  }

  _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return TEXT[lang] || TEXT.en;
  }

  /** Locale for numbers as the user's number format says (HA's mapping). */
  _numberLocale() {
    const locale = this._hass?.locale || {};
    return {
      comma_decimal: ["en-US", "en"],
      decimal_comma: ["de", "es", "it"],
      space_comma: ["fr", "sv", "cs"],
      system: undefined,
    }[locale.number_format] ?? locale.language ?? "en";
  }

  _num(value, digits) {
    if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "–";
    return new Intl.NumberFormat(this._numberLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value));
  }

  /** "14:05", or with the day when it was not today. */
  _when(iso) {
    const date = new Date(iso);
    const locale = this._hass.locale || {};
    const options = { hour: "2-digit", minute: "2-digit", timeZone: this._timeZone() };
    if (locale.time_format === "12") options.hour12 = true;
    if (locale.time_format === "24") options.hour12 = false;
    const day = (d) => d.toLocaleDateString("en-CA", { timeZone: this._timeZone() });
    if (day(date) !== day(new Date())) Object.assign(options, { day: "numeric", month: "short" });
    return date.toLocaleString(locale.language || "en", options);
  }

  /** Time zone for dates: the server's unless the user chose the local one. */
  _timeZone() {
    return this._hass?.locale?.time_zone === "local" ? undefined : this._hass?.config?.time_zone;
  }

  _stateOf(entityId) {
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _state(key) {
    return this._stateOf(this._entities[key]);
  }

  _format(state) {
    if (!state || state.state === "unavailable" || state.state === "unknown") return "–";
    return this._hass.formatEntityState ? this._hass.formatEntityState(state)
      : `${state.state} ${state.attributes.unit_of_measurement || ""}`.trim();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (event) => {
        const target = event.composedPath().find((el) => el.dataset && el.dataset.entity);
        if (target) {
          this.dispatchEvent(new CustomEvent("hass-more-info", {
            detail: { entityId: target.dataset.entity }, bubbles: true, composed: true,
          }));
        }
      });
    }
    const t = this._t();
    const deviceId = this._deviceId();
    const kind = this._kind();
    const actual = deviceId ? deviceKind(this._hass, deviceId) : undefined;
    this._entities = actual === kind ? deviceEntities(this._hass, deviceId) : {};
    const topics = this._topics();
    let body;
    if (!Object.keys(this._entities).length) {
      // The other kind of device chosen, or only that kind there: say which
      // card fits instead of "no device".
      const other = kind === "pump" ? "boiler" : "pump";
      const hint = actual === other || (!actual && !this._config.device_id && wwDevices(this._hass, other).length);
      const text = !hint ? t.noDevice : kind === "pump" ? t.onlyBoiler : t.onlyPump;
      body = `<div class="empty">${escapeHtml(text)}</div>`;
    } else {
      const single = topics.length === 1;
      body = topics
        .map((topic) => {
          const inner = this[`_${topic}`](t, deviceId);
          if (!inner) return "";
          return single ? inner : `<section>${this._heading(t, topic, false)}${inner}</section>`;
        })
        .filter(Boolean)
        .join("") || `<div class="empty">${escapeHtml(t.nothing)}</div>`;
      if (single) body = this._heading(t, topics[0], true) + body;
    }
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${body}</ha-card>`;
  }

  _heading(t, topic, card) {
    const title = this._config.title === undefined ? undefined : String(this._config.title);
    if (card && title !== undefined && title.trim() === "" && title !== "") return "";
    const text = card && title ? title : t.topics[topic];
    let device = "";
    // The device only where it is not clear: several heat pumps and none
    // chosen, or asked for (show_device).
    if (card && (this._config.show_device || (!this._config.device_id && wwDevices(this._hass, this._kind()).length > 1))) {
      const entry = this._hass.devices?.[this._deviceId()];
      device = `<span class="device">${escapeHtml(entry?.name_by_user || entry?.name || "")}</span>`;
    }
    return `<div class="head"><ha-icon icon="${ICONS[topic]}"></ha-icon>${escapeHtml(text)}${device}</div>`;
  }

  _tile(entityId, label, extra = "", value = undefined) {
    const state = this._stateOf(entityId);
    if (!state) return "";
    return `<div class="tile" data-entity="${escapeHtml(entityId)}"><div class="label">${escapeHtml(label)}</div>`
      + `<div class="value">${escapeHtml(value ?? this._format(state))}</div>`
      + `${extra ? `<div class="extra">${escapeHtml(extra)}</div>` : ""}</div>`;
  }

  _own(key, label, extra = "") {
    return this._tile(this._entities[key], label, extra);
  }

  _grid(tiles) {
    const shown = tiles.filter(Boolean);
    return shown.length ? `<div class="grid">${shown.join("")}</div>` : "";
  }

  // ---- Topics -------------------------------------------------------------

  _now(t, deviceId) {
    const src = sources(this._hass, deviceId);
    if (!src) return `<div class="empty">…</div>`;
    const activity = this._stateOf(src.activity);
    const since = activity?.last_changed ? t.since(this._when(activity.last_changed)) : "";
    return this._grid([
      this._tile(src.activity, t.tiles.activity, since),
      this._tile(src.compressor, t.tiles.compressor),
      this._tile(this._config.heat_power, t.tiles.heat_power),
      this._tile(this._config.electric_power, t.tiles.electric_power),
      this._tile(src.outdoor_temp, t.tiles.outdoor_temp),
      this._tile(src.flow_temp, t.tiles.flow_temp),
      this._tile(src.return_temp, t.tiles.return_temp),
      this._tile(src.dhw_temp, t.tiles.dhw_temp),
    ]);
  }

  _ratios(t) {
    const rows = RATIO_SCOPES.filter((scope) => RATIO_PERIODS.some((p) => this._state(`ratio_${scope}_${p}`)))
      .map((scope) => {
        const cells = RATIO_PERIODS.map((p) => {
          const id = this._entities[`ratio_${scope}_${p}`];
          const state = this._stateOf(id);
          if (!state) return "<td>–</td>";
          return `<td class="link" data-entity="${escapeHtml(id)}">${escapeHtml(this._format(state))}</td>`;
        }).join("");
        const label = scope === "combined" ? `<b>${escapeHtml(t.scopes[scope])}</b>` : escapeHtml(t.scopes[scope]);
        return `<tr><td>${label}</td>${cells}</tr>`;
      });
    if (!rows.length) return "";
    const head = `<tr><th></th>${RATIO_PERIODS.map((p) => `<th>${escapeHtml(t.periods[p])}</th>`).join("")}</tr>`;
    return `<div class="wrap"><table>${head}${rows.join("")}</table></div>`;
  }

  _health(t) {
    const rows = CHECKS.map((check) => {
      const problemId = this._entities[check];
      const statusId = this._entities[`${check}_status`];
      const binary = this._stateOf(problemId);
      const status = this._stateOf(statusId);
      if (!binary && !status) return "";
      const attrs = binary?.attributes || {};
      const reason = attrs.reason;
      let cls = "";
      let text;
      if (status && !["unknown", "unavailable"].includes(status.state)) {
        cls = status.state === "ok" ? "ok" : status.state === "problem" ? "problem" : "";
        text = this._format(status);
      } else if (binary && !reason && ["on", "off"].includes(binary.state)) {
        cls = binary.state === "on" ? "problem" : "ok";
        text = binary.state === "on" ? t.problem : t.fine;
      } else {
        text = (reason && (t.reasons[reason] || reason)) || t.unknown;
      }
      let detail = "";
      if (cls && binary && !reason) {
        try {
          detail = t.detail[check](attrs, (v, d) => this._num(v, d));
        } catch (e) {
          detail = "";
        }
      }
      return `<div class="row" data-entity="${escapeHtml(problemId || statusId)}"><div class="dot ${cls}"></div><div>`
        + `<div class="name">${escapeHtml(t.checks[check])}</div>`
        + `<div class="text">${escapeHtml(text)}${detail ? ` · ${escapeHtml(detail)}` : ""}</div></div></div>`;
    }).filter(Boolean);
    return rows.join("");
  }

  _cycling(t) {
    const d = this._state("defrosts_today")?.attributes || {};
    const season = this._state("starts_season")?.attributes || {};
    return this._grid([
      this._own("starts_today", t.tiles.starts_today),
      this._own("runtime_today", t.tiles.runtime_today),
      this._own("run_minutes_today", t.tiles.run_minutes_today),
      this._own("shortest_pause_today", t.tiles.shortest_pause_today),
      this._own("short_runs_today", t.tiles.short_runs_today),
      this._own("defrosts_today", t.tiles.defrosts_today,
        d.defrosts_7d !== undefined ? t.times(d.defrosts_7d, this._num(d.mean_minutes_7d, 1)) : ""),
      this._own("run_minutes_week", t.tiles.run_minutes_week),
      this._own("spread_7d", t.tiles.spread_7d),
      this._own("starts_season", t.tiles.starts_season,
        season.per_day !== undefined ? t.perDay(this._num(season.per_day, 1)) : ""),
      this._own("standby_power_7d", t.tiles.standby_power_7d),
    ]);
  }

  _dhw(t) {
    const last = this._state("ratio_dhw_last_charge")?.attributes || {};
    const charges = this._state("ratio_dhw_charges_30d")?.attributes || {};
    return this._grid([
      this._own("ratio_dhw_last_charge", t.tiles.ratio_dhw_last_charge, last.minutes !== undefined
        ? `${last.minutes} min · ${this._num(last.start_temp, 1)} → ${this._num(last.max_temp, 1)} °C` : ""),
      this._own("ratio_dhw_charges_30d", t.tiles.ratio_dhw_charges_30d, charges.charges !== undefined
        ? t.charges(charges.charges, this._num(charges.mean_minutes, 0)) : ""),
    ]);
  }

  _costs(t) {
    return this._grid(["cost_month", "cost_season", "heat_cost_season", "gas_savings_season"]
      .map((key) => this._own(key, t.tiles[key])));
  }

  _hybrid(t) {
    const share = (key) => {
      const a = this._state(key)?.attributes || {};
      return this._own(key, t.tiles[key], a.with_dhw !== undefined && a.with_dhw !== null ? t.withDhw(this._num(a.with_dhw, 0)) : "");
    };
    return this._grid([
      share("heat_pump_share_month"),
      share("heat_pump_share_season"),
      this._own("boiler_heat_heating", t.tiles.boiler_heat_heating),
      this._own("boiler_heat_dhw", t.tiles.boiler_heat_dhw),
    ]);
  }

  _analysis(t) {
    const charts = [];
    const curve = this._state("performance_curve_heating");
    if (curve) {
      const series = [
        ["previous", t.previousSeason, curve.attributes.previous],
        ["current", t.current, curve.attributes.current],
      ].map(([key, label, rows]) => ({
        color: COLORS[key],
        label,
        line: true,
        points: (rows || []).filter((r) => r.ratio !== null && r.ratio !== undefined)
          .map((r) => [(r.lower + r.upper) / 2, r.ratio]),
      })).filter((s) => s.points.length);
      if (series.length) {
        charts.push(this._xyChart(t.curve, "", series, this._entities.performance_curve_heating, undefined, 2));
      }
    }
    const signature = this._signature(t, "heat_load_per_kelvin");
    if (signature) charts.push(signature);
    const flow = this._state("flow_at_zero")?.attributes || {};
    const perDegree = this._state("heat_per_degree_day_season")?.attributes || {};
    const previous = (v, digits, unit = "") => (v !== undefined && v !== null ? `${t.previous} ${this._num(v, digits)}${unit}` : "");
    const tiles = this._grid([
      this._own("heat_load_per_kelvin", t.tiles.heat_load_per_kelvin),
      this._own("heat_load_design", t.tiles.heat_load_design),
      this._own("heating_limit", t.tiles.heating_limit),
      this._own("heat_per_degree_day_season", t.tiles.heat_per_degree_day_season, previous(perDegree.previous_season, 2)),
      this._own("flow_at_zero", t.tiles.flow_at_zero, previous(flow.previous_season, 1, " °C")),
      this._own("oversize_factor", t.tiles.oversize_factor),
    ]);
    return (charts.length ? `<div class="charts">${charts.join("")}</div>` : "") + tiles;
  }

  /** Energy signature of a heat load sensor (attributes of heat_load.py):
   * the weeks and the line, also a preliminary one. */
  _signature(t, key) {
    const load = this._state(key);
    if (!load) return "";
    const a = load.attributes;
    const weeks = (a.weeks || []).map((w) => [w.mean_outdoor, w.power_kw]).sort((x, y) => x[0] - y[0]);
    const series = [];
    if (weeks.length) series.push({ color: COLORS.previous, label: t.weeks, line: false, points: weeks });
    if (a.intercept_kw !== null && a.intercept_kw !== undefined && a.slope_kw_per_k !== null && a.slope_kw_per_k !== undefined) {
      const lo = a.design_temp ?? Math.min(-12, ...weeks.map((w) => w[0]));
      const hi = a.heating_limit ?? 15;
      series.push({
        color: COLORS.current,
        label: a.sufficient === false ? t.preliminaryLine : t.line,
        line: true,
        points: [[lo, a.intercept_kw + a.slope_kw_per_k * lo], [hi, Math.max(0, a.intercept_kw + a.slope_kw_per_k * hi)]],
      });
    }
    return series.length ? this._xyChart(t.signature, "kW", series, this._entities[key], 0, 2) : "";
  }

  /** A tile of the boiler: an unknown value says why. */
  _boilerTile(t, key, extra = "") {
    const state = this._state(key);
    if (!state) return "";
    const reason = state.attributes.reason;
    const unknown = ["unknown", "unavailable"].includes(state.state);
    const why = unknown && reason ? t.reasons[reason] || reason : "";
    return this._own(key, t.tiles[key], extra || why);
  }

  _boiler(t) {
    const load = this._state("gas_heat_load_per_kelvin")?.attributes || {};
    const n = (v, d) => this._num(v, d);
    // Heat load still unknown: what the data still lack (weeks, spread, frost).
    const progress = this._state("gas_heat_load_per_kelvin")?.state === "unknown" && load.week_count !== undefined
      ? [
        ["weeks", load.week_count, SIGNATURE_NEEDS.weeks, 0],
        ["spread", load.spread ?? 0, SIGNATURE_NEEDS.spread, 1],
        ["frost_days", load.frost_days ?? 0, SIGNATURE_NEEDS.frost_days, 0],
      ].filter(([, have, need]) => have < need).map(([key, have, need, digits]) => t.progress[key](n(have, digits), need)).join(" · ")
      : "";
    const limit = this._state("gas_heating_limit");
    const preliminaryLimit = limit?.state === "unknown" && load.preliminary && load.heating_limit !== null && load.heating_limit !== undefined
      ? t.preliminaryValue(`${n(load.heating_limit, 1)} °C`) : "";
    const fuel = this._entities.oil_consumption_year ? "oil" : "gas";
    const used = this._state(`${fuel}_consumption_year`)?.attributes || {};
    const usedExtra = [
      used.litres !== undefined && used.litres !== null ? t.litres(n(used.litres, 0)) : "",
      used.complete === false && used.days !== undefined ? t.days(used.days) : "",
    ].filter(Boolean).join(" · ");
    const signature = this._signature(t, "gas_heat_load_per_kelvin");
    const tiles = this._grid([
      this._boilerTile(t, "gas_heat_load_per_kelvin", progress),
      this._boilerTile(t, "gas_heat_load_design"),
      this._boilerTile(t, "gas_heating_limit", preliminaryLimit),
      this._boilerTile(t, "gas_heat_per_degree_day"),
      this._boilerTile(t, "gas_flow_at_zero"),
      this._boilerTile(t, "gas_flow_at_design"),
      this._boilerTile(t, "gas_dhw_share"),
      this._boilerTile(t, `${fuel}_consumption_year`, usedExtra),
      this._boilerTile(t, `${fuel}_cost_year`),
    ]);
    return (signature ? `<div class="charts">${signature}</div>` : "") + tiles;
  }

  _months(t, deviceId) {
    const ids = MONTH_KEYS.map((k) => this._entities[k]).filter(Boolean);
    if (!ids.length) return "";
    const cache = this._monthCache;
    const stale = !cache || cache.deviceId !== deviceId || Date.now() - cache.at > 3600 * 1000;
    if (stale && !this._monthLoading) {
      this._monthLoading = true;
      // 13 months back; the recorder cuts months in the server's time zone,
      // the last twelve are shown.
      const start = new Date(Date.now() - 400 * 86400000);
      this._hass.callWS({
        type: "recorder/statistics_during_period",
        start_time: start.toISOString(),
        statistic_ids: ids,
        period: "month",
        types: ["change"],
        units: { energy: "kWh" },
      }).then((rows) => {
        this._monthCache = { deviceId, at: Date.now(), rows };
      }).catch(() => {
        this._monthCache = { deviceId, at: Date.now(), rows: {} };
      }).finally(() => {
        this._monthLoading = false;
        this._states = null;
        this._render();
      });
    }
    if (!this._monthCache) return `<div class="empty">…</div>`;
    const rows = this._monthCache.rows || {};
    const months = new Map();
    for (const key of MONTH_KEYS) {
      for (const row of rows[this._entities[key]] || []) {
        const m = months.get(row.start) || {};
        m[key] = (m[key] || 0) + (row.change || 0);
        months.set(row.start, m);
      }
    }
    if (!months.size) return `<div class="empty">${escapeHtml(t.noStatistics)}</div>`;
    return this._monthChart(t, [...months.entries()].sort((a, b) => a[0] - b[0]).slice(-12));
  }

  // ---- Charts -------------------------------------------------------------

  /** Points and lines over the outdoor temperature (°C on x). */
  _xyChart(caption, unit, series, entityId, yMin, digits) {
    const W = 320;
    const H = 160;
    const L = 30;
    const B = 22;
    const all = series.flatMap((s) => s.points);
    const x0 = Math.floor(Math.min(...all.map((p) => p[0])) / 5) * 5;
    let x1 = Math.ceil(Math.max(...all.map((p) => p[0])) / 5) * 5;
    if (x1 - x0 < 10) x1 = x0 + 10;
    const low = yMin ?? Math.min(...all.map((p) => p[1]));
    const high = Math.max(...all.map((p) => p[1]));
    const step = niceStep(Math.max(high - low, 0.1) / 4);
    const y0 = Math.floor(low / step) * step;
    let y1 = Math.ceil(high / step) * step;
    if (y1 <= y0) y1 = y0 + step;
    const x = (v) => L + ((v - x0) / (x1 - x0)) * (W - L - 6);
    const y = (v) => 6 + (1 - (v - y0) / (y1 - y0)) * (H - B - 6);
    let grid = "";
    for (let v = y0; v <= y1 + step / 2; v += step) {
      grid += `<line class="axis" x1="${L}" x2="${W - 6}" y1="${y(v)}" y2="${y(v)}" stroke-dasharray="2 3"/>`
        + `<text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${this._num(v, stepDigits(step))}</text>`;
    }
    for (let v = x0; v <= x1; v += 5) grid += `<text x="${x(v)}" y="${H - 6}" text-anchor="middle">${v} °C</text>`;
    const marks = series.map((s) => {
      const pts = s.points.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`);
      const line = s.line && pts.length > 1 ? `<polyline points="${pts.join(" ")}" fill="none" stroke="${s.color}" stroke-width="2"/>` : "";
      const dots = s.points.map((p) => `<circle cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="${s.line ? 2.5 : 3.5}" fill="${s.color}">`
        + `<title>${escapeHtml(s.label)}: ${this._num(p[0], 1)} °C · ${this._num(p[1], digits)}${unit ? ` ${unit}` : ""}</title></circle>`).join("");
      return line + dots;
    }).join("");
    const legend = series.map((s) => `<span style="--c:${s.color}">${escapeHtml(s.label)}</span>`).join("");
    return `<div class="chart" data-entity="${escapeHtml(entityId)}"><div class="caption">${escapeHtml(caption)}${unit ? ` (${escapeHtml(unit)})` : ""}</div>`
      + `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(caption)}">${grid}${marks}</svg>`
      + `<div class="legend">${legend}</div></div>`;
  }

  /** Two stacked bars per month: heat (heating, hot water) and electricity
   * (heating, hot water, standby), the performance factor above. */
  _monthChart(t, months) {
    const W = 560;
    const H = 200;
    const L = 34;
    const B = 22;
    const T = 14;
    const sum = (m, keys) => keys.reduce((s, k) => s + Math.max(0, m[k] || 0), 0);
    const heatKeys = ["heat_heating", "heat_dhw"];
    const elecKeys = ["electricity_heating", "electricity_dhw", "standby"];
    const high = Math.max(1, ...months.map(([, m]) => Math.max(sum(m, heatKeys), sum(m, elecKeys))));
    const step = niceStep(high / 4);
    const y1 = Math.ceil(high / step) * step;
    const y = (v) => T + (1 - v / y1) * (H - B - T);
    const slot = (W - L - 6) / months.length;
    const bar = Math.max(3, slot * 0.34);
    const lang = this._hass.locale?.language || "en";
    let grid = "";
    for (let v = 0; v <= y1 + step / 2; v += step) {
      grid += `<line class="axis" x1="${L}" x2="${W - 6}" y1="${y(v)}" y2="${y(v)}" stroke-dasharray="2 3"/>`
        + `<text x="${L - 4}" y="${y(v) + 3}" text-anchor="end">${this._num(v, stepDigits(step))}</text>`;
    }
    const colors = {
      heat_heating: COLORS.heat, heat_dhw: COLORS.heatDhw,
      electricity_heating: COLORS.elec, electricity_dhw: COLORS.elecDhw, standby: COLORS.standby,
    };
    const names = {
      heat_heating: `${t.heat} ${t.scopes.heating}`, heat_dhw: `${t.heat} ${t.scopes.dhw}`,
      electricity_heating: `${t.electricity} ${t.scopes.heating}`, electricity_dhw: `${t.electricity} ${t.scopes.dhw}`,
      standby: t.standby,
    };
    let bars = "";
    months.forEach(([start, m], i) => {
      const date = new Date(start);
      const label = date.toLocaleDateString(lang, { month: "short", timeZone: this._timeZone() });
      const x0 = L + i * slot + slot / 2 - bar - 1;
      for (const [keys, left] of [[heatKeys, x0], [elecKeys, x0 + bar + 2]]) {
        let base = 0;
        for (const key of keys) {
          const v = Math.max(0, m[key] || 0);
          if (!v) continue;
          bars += `<rect x="${left.toFixed(1)}" y="${y(base + v).toFixed(1)}" width="${bar.toFixed(1)}" height="${(y(base) - y(base + v)).toFixed(1)}" fill="${colors[key]}">`
            + `<title>${escapeHtml(label)} · ${escapeHtml(names[key])}: ${this._num(v, 0)} kWh</title></rect>`;
          base += v;
        }
      }
      const heat = sum(m, heatKeys);
      const elec = sum(m, elecKeys);
      if (heat > 0 && elec > 0) {
        bars += `<text x="${(L + i * slot + slot / 2).toFixed(1)}" y="${(y(Math.max(heat, elec)) - 3).toFixed(1)}" text-anchor="middle">${this._num(heat / elec, 1)}</text>`;
      }
      bars += `<text x="${(L + i * slot + slot / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${escapeHtml(label)}</text>`;
    });
    const legend = Object.keys(colors).map((k) => `<span style="--c:${colors[k]}">${escapeHtml(names[k])}</span>`).join("");
    const target = this._entities.heat_heating || this._entities.electricity_heating;
    return `<div class="chart months" data-entity="${escapeHtml(target)}"><div class="caption">kWh · ${escapeHtml(t.ratio)}</div>`
      + `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t.topics.months)}">${grid}${bars}</svg>`
      + `<div class="legend">${legend}</div></div>`;
  }
}

class WaermewachtCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const lang = (this._hass.locale?.language || "en").slice(0, 2);
    const t = TEXT[lang] || TEXT.en;
    const type = String(this._config.type || "");
    const topic = TOPICS.find((x) => type === `custom:waermewacht-${x}-card`);
    // Only devices the card can show: heat pumps, boilers, or (the card with
    // all topics) both.
    const kinds = topic ? [topicKind(topic)] : ["pump", "boiler"];
    const deviceLabel = topic ? t.editor[topicKind(topic) === "boiler" ? "device_boiler" : "device_id"] : t.editor.device_any;
    const devices = kinds.flatMap((kind) => wwDevices(this._hass, kind)).map((id) => {
      const entry = this._hass.devices?.[id];
      return { value: id, label: entry?.name_by_user || entry?.name || id };
    });
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (event) => {
        const value = { ...event.detail.value };
        for (const key of Object.keys(value)) {
          if (value[key] === "" || value[key] === null || (Array.isArray(value[key]) && !value[key].length)) delete value[key];
        }
        this._config = { type: this._config.type, ...value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.computeLabel = (schema) => (schema.name === "device_id" ? deviceLabel : t.editor[schema.name] || schema.name);
    const schema = [
      { name: "device_id", selector: { select: { mode: "dropdown", options: devices } } },
      { name: "title", selector: { text: {} } },
    ];
    if (!topic) {
      // Topics for the chosen device's kind (all when none is chosen).
      const chosen = this._config.device_id && deviceKind(this._hass, this._config.device_id);
      schema.push({
        name: "sections",
        selector: {
          select: {
            multiple: true,
            options: TOPICS.filter((s) => !chosen || topicKind(s) === chosen).map((s) => ({ value: s, label: t.topics[s] })),
          },
        },
      });
    }
    if (!topic || topic === "now") {
      schema.push(
        { name: "heat_power", selector: { entity: { filter: { domain: "sensor", device_class: "power" } } } },
        { name: "electric_power", selector: { entity: { filter: { domain: "sensor", device_class: "power" } } } },
      );
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = schema;
  }
}

/** One topic per card type: waermewacht-<topic>-card. */
function topicCard(topic) {
  return class extends WaermewachtCard {
    _fixedTopic() {
      return topic;
    }

    static getStubConfig(hass) {
      const devices = wwDevices(hass, topicKind(topic));
      return devices.length > 1 ? { device_id: devices[0] } : {};
    }
  };
}

if (!customElements.get("waermewacht-card")) {
  customElements.define("waermewacht-card-editor", WaermewachtCardEditor);
  customElements.define("waermewacht-card", WaermewachtCard);
  window.customCards = window.customCards || [];
  const lang = (navigator.language || "en").slice(0, 2);
  const t = TEXT[lang] || TEXT.en;
  for (const topic of TOPICS) {
    customElements.define(`waermewacht-${topic}-card`, topicCard(topic));
    window.customCards.push({
      type: `waermewacht-${topic}-card`,
      name: `Wärmewacht ${t.topics[topic]}`,
      description: t.describe[topic],
      preview: true,
      documentationURL: "https://github.com/waermewacht/integration#karten",
    });
  }
  window.customCards.push({
    type: "waermewacht-card",
    name: "Wärmewacht",
    description: t.describe.all,
    preview: false,
    documentationURL: "https://github.com/waermewacht/integration#karten",
  });
  console.info(`%c WÄRMEWACHT %c ${CARD_VERSION} `, "color:#fff;background:#DE5E32", "color:#DE5E32");
}
