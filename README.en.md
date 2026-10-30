<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Wärmewacht – Every kilowatt-hour. Every cycle." src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/waermewacht/integration?color=DE5E32)](https://github.com/waermewacht/integration/releases)
[![CI](https://github.com/waermewacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/waermewacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

[Deutsch](https://github.com/waermewacht/integration/blob/main/README.md) · **English**

> **New.** The templates for EMS-ESP and Bosch HomeCom run on a real installation; all others are beta (see [Requirements](#requirements)). Feedback is welcome, see [Reporting issues](#reporting-issues).

**How efficient is your heat pump really?** Wärmewacht ("heat watch") calculates performance factors per operating mode and period in Home Assistant, counts starts, short runs and defrosts and shows a few diagnostic values. It works from the entities your heat pump already provides. Wärmewacht only reads and never controls anything. No cloud, no network requests.

**Still on gas?** Wärmewacht also computes your house's heat load from the gas consumption, as a basis for sizing a heat pump: [Gas boiler before switching](#gas-boiler-before-switching).

> **A guide, not an expert diagnosis.** The figures depend on what your heat pump's meters measure. See [System boundary and limits](#system-boundary-and-limits).

The user interface is available in German and English and follows the language of your Home Assistant.

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/arbeitszahlen.png" alt="Dashboard with performance factors per mode for today, month and season, costs and cycling" width="720">

<sub>Real figures of a Bosch Compress 5800i AW (EMS-ESP) in October, German UI. "Heizen+WW" (heating + hot water) is the factor including standby electricity and is therefore below both single values.</sub>

## Contents

- [Features](#features) · [What Wärmewacht does differently](#what-wärmewacht-does-differently-from-template-sensors)
- **Getting started:** [Requirements](#requirements) · [Installation](#installation) · [Setup](#setup) · [Settings](#settings) · [Gas boiler before switching](#gas-boiler-before-switching)
- **[Entities](#entities):** [Performance factors](#performance-factors) · [Energy](#energy) · [Cycling](#cycling) · [Hot water charges](#hot-water-charges) · [Health check](#health-check) · [Costs and gas comparison](#costs-and-gas-comparison) · [Performance curve and heat load](#performance-curve-and-heat-load)
- **[Actions](#actions):** [Report](#report) · [Performance curve](#performance-curve) · [Heat load](#heat-load)
- **More:** [Dashboard examples](#dashboard-examples) · [System boundary](#system-boundary-and-limits) · [Troubleshooting](#troubleshooting) · [Privacy](#privacy) · [Removal](#removal) · [Reporting issues](#reporting-issues) · [Related projects](#related-projects)

## Features

- **Performance factors** for heating, hot water and heating + hot water, plus the **energy efficiency ratio for cooling (EER)**, each for today, yesterday, month, season and total.
- **Heat and electricity sensors per mode** and a sensor for **standby**, with long-term statistics for statistics cards.
- **Cycling:** starts, run time, run time per start, short runs, shortest pause, defrosts and a binary sensor **Conspicuous cycling**.
- **Diagnostics:** backup heater share, flow-return spread and mean flow temperature while heating (with an activity).
- **Hot water per charge:** performance factor of the last charge and of the charges of the last 30 days, last thermal disinfection.
- **Health check:** reports a dropped efficiency at the same weather, a dropped hot water efficiency against last year and the backup heater on mild days or in hot water charges. Repair issues when a meter stands still, a source fails, the outdoor temperature is stuck or flow rate, flow and return do not add up.
- **Costs and gas comparison** (optional, with fixed prices): electricity cost, heat cost per kWh and the savings against a gas boiler.
- **Performance curve and heat load:** heating performance factor over the outdoor temperature and heat load from the energy signature. As sensors and via actions for any period. Plus figures such as degree days, flow temperature at 0 °C (the heating curve), spread on cold days and power per heat load.
- **Gas boiler before switching:** heat load, heating limit and hot water share from the gas consumption of the last 365 days, as an entry of its own ([more](#gas-boiler-before-switching)).
- **Report for any period** via an action, broken down by month. Also **before the setup**, as far back as the long-term statistics of your meters go.
- **Templates for EMS-ESP and Bosch HomeCom:** find Bosch/Buderus heat pumps on their own and fill in the entities. As beta also Luxtronik (alpha innotec, Novelan), Stiebel Eltron/Tecalor (ISG), Panasonic Aquarea (HeishaMon), Lambda, iDM, Viessmann (ViCare), Mitsubishi Ecodan (MELCloud, F1p bridge or ESPHome), Vaillant (myVAILLANT), Waterkotte, Buderus via the MX300/MX400 gateway (integration `buderus`) and Daikin Altherma (P1P2MQTT). Other heat pumps are mapped by hand.
- **Easy on SD cards:** writes only when something changed, and then at most every 10 minutes. In addition at the end of a run, at midnight and on shutdown. Sensors update once a minute and on events.

## What Wärmewacht does differently from template sensors

- **Performance factor of a period = Σ heat / Σ electricity**, never the mean of daily values.
- **Unknown instead of 0:** Without heat or below the minimum electricity (default 0.5 kWh) a performance factor is unknown. Zeros would drag means and statistics down.
- **Standby kept separate:** Electricity while the compressor stands still does not count in the factor per mode, but it does in heating + hot water. Fraunhofer ISE calculates the same way in its field tests.
- **Cooling never enters the seasonal factor.** It has its own EER.
- **Cycling from real compressor runs:** A Home Assistant restart in the middle of a run is not a new start. If the heat pump switches from heating to hot water without stopping, it stays one run. A run that was already going when first seen does not count as a start.
- **Meter resets and steps back:** Steps back keep the highest reading; only heat above it is booked (net). This covers noise and defrosts, during which the heat pump subtracts the heat it took. Only a drop of more than 10 % and more than 1 kWh counts as a reset with a new baseline, implausible jumps are not booked. `unknown` and `unavailable` never count as 0.
- **Look back from the long-term statistics:** Today, yesterday, month, season and total already include the time before the setup.

## Requirements

A gas boiler before switching needs only a gas counter and the outdoor temperature, see [Gas boiler before switching](#gas-boiler-before-switching). For a heat pump:

- Home Assistant 2026.4 or newer.
- The recorder (on by default in Home Assistant) for the look back, the report, the performance curve and the heat load. Which entities it must record: [Keeping the recorder lean](#keeping-the-recorder-lean).
- At least one mode with a **heat meter** and a **compressor electricity meter**: cumulative energy sensors in Wh, kWh or MWh. Without heat meters the compressor state is enough; then there is cycling and electricity, but no performance factors.

| Source | Status |
| --- | --- |
| [EMS-ESP](https://github.com/emsesp/EMS-ESP32) (MQTT) with Bosch/Buderus heat pumps, e.g. CS5800i/CS6800i, WLW176i/WLW186i | template, tested on a CS5800i/CS6800i |
| [Bosch HomeCom](https://github.com/serbanb11/bosch-homecom-hass) (`bosch_homecom`, local and cloud) | template, new, compared with EMS-ESP on the same CS5800i/CS6800i |
| [Luxtronik](https://github.com/BenPru/luxtronik) (`luxtronik2`; alpha innotec, Novelan) | beta, from the source code; electricity per mode only with newer firmware |
| [Stiebel Eltron / Tecalor ISG](https://github.com/pail23/stiebel_eltron_isg_component) (`stiebel_eltron_isg`) | beta, from the source code; meters in whole kWh; no cooling electricity, so no EER |
| [Panasonic Aquarea via HeishaMon](https://github.com/kamaradclimber/heishamon-homeassistant) (`aquarea`) | beta, from the source code; energy summed up from the power values, no backup heater |
| [Lambda](https://github.com/GuidoJeuken-6512/lambda_heat_pumps) (`lambda_heat_pumps`) | beta, from the source code; own meters for defrost and standby |
| [iDM Navigator 2.0](https://github.com/Xerolux/idm-heatpump-hass) (`idm_heatpump`, with web interface) | beta, from the source code |
| [Viessmann ViCare](https://www.home-assistant.io/integrations/vicare/) (core `vicare`) | beta, from the source code; **cycling and electricity only, no performance factor** |
| [Mitsubishi Ecodan via MELCloud](https://www.home-assistant.io/integrations/melcloud/) (core `melcloud`, HA 2026.5+) | beta, from the source code; performance factors without cycling |
| [Vaillant myVAILLANT](https://github.com/signalkraft/mypyllant-component) (`mypyllant`) | beta, from the source code; performance factors without cycling |
| [Mitsubishi Ecodan via F1p bridge](https://github.com/F1p/Home-Assistant-Mitsubishi-CN105-to-MQTT) (MQTT, CN105) | beta, from the source code; performance factors, cycling and defrosts |
| [Mitsubishi Ecodan with ESPHome](https://github.com/gekkekoe/esphome-ecodan-hp) (`esphome`, esphome-ecodan-hp) | beta, from the source code; performance factors, cycling and defrosts |
| [Waterkotte EcoTouch](https://github.com/marq24/ha-waterkotte) (`waterkotte_heatpump`) | beta, from the source code; compressor electricity as a total only |
| [Buderus/Bosch via MX300, MX400, K30](https://github.com/BassXT/buderus) (`buderus_ha`) | beta, from the source code; performance factors, cycling and defrosts |
| [Daikin Altherma via P1P2MQTT](https://github.com/Arnold-n/P1P2Serial) (MQTT) | beta, from the source code; performance factors, cycling and defrosts, meters in whole kWh |
| any heat and electricity meters | manual mapping |

The EMS-ESP template recognizes the heat pump by the `boiler` device. It needs the compressor state (`hpcompon`) and the heating meters. It finds the entities through the entity registry, not by entity ID, so renaming and all of EMS-ESP's naming formats are fine. It understands the activity (`hpactivity`) in all EMS-ESP languages and in the index format.

The HomeCom template needs the energy per mode ("Wärme erzeugt Heizung", "Strom Kompressor Heizung" etc.; English: heat produced and compressor energy per heating, hot water and cooling). `bosch_homecom` creates these entities disabled: enable them first. The setup shows which ones are still disabled. "Compressor running" is the compressor speed above 0. Compared with EMS-ESP, HomeCom has limits:

- **Day values from the cloud:** the energy arrives as the day's sum, up to two hours late. Wärmewacht books it when it arrives, so "today" lags behind. The cloud never delivers the last one or two hours of a day (observed up to 0.5 kWh per day).
- **Standby:** electricity of a fetch that brought no heat of the same mode.
- **Activity only with the compressor status:** Until `bosch_homecom` provides the sensor "Compressor status" ([PR #217](https://github.com/serbanb11/bosch-homecom-hass/pull/217)), there are no defrosts, no flow-return spread and no mean flow temperature. Once it exists, Wärmewacht takes it over at the next start by itself.
- **No flow rate:** `bosch_homecom` reports "L/min" but delivers l/h.

If you run EMS-ESP, use EMS-ESP: meters in 0.01 kWh every minute, and the activity.

**Beta templates** are derived from the source code of each integration, not confirmed on a real installation. The setup shows them with "(beta)". If you have such a heat pump, feedback with the [diagnostics file](#reporting-issues) helps a lot. The main limits:

- **Viessmann ViCare:** Home Assistant provides no heat (the library PyViCare does not read it yet). Wärmewacht therefore shows cycling, run times, electricity per mode and costs, but no performance factor. E3 controllers (Vitocal 150-A to 252-A) report no activity; older Vitotronic controllers report defrosts but no energy. Wärmewacht counts the cloud's day values in UTC days: if the cloud starts at local midnight after all, a day's first value only arrives an hour or two later.
- **Mitsubishi Ecodan (MELCloud):** `melcloud` creates the heat per mode disabled: enable it first. Without a usable compressor signal (only every 30 minutes) there is no cycling and no defrost count. MELCloud reports the totals of the **previous day**: they jump once just after midnight and then stay the same all day. Wärmewacht therefore books them into the previous day, so month and season are right at month boundaries too. "Today" stays empty for this source, "yesterday" is the earliest figure. If the cloud misses an update, that day is missing.
- **Mitsubishi Ecodan (F1p bridge):** Local via the CN105 port, with compressor and activity, so with cycling and defrosts. The energy comes as the previous day's total, as with MELCloud. The bridge sometimes sends its own estimate before the real value; if it is higher, Wärmewacht counts a little too much. As the bridge sets no `state_class`, there is no look back before the setup.
- **Mitsubishi Ecodan (ESPHome):** Like the F1p bridge, the esphome-ecodan-hp firmware provides compressor, activity, defrost and the energy as the previous day's total. The template recognises the entities by the firmware's names; if you renamed them in the YAML, map them by hand. The FTC clock must be right, also after a DST change. Defrost includes standby and restart and therefore tends to be too long.
- **Buderus/Bosch via MX300/MX400 (`buderus`):** Reads the Bosch cloud like Bosch HomeCom, but with lifetime meters per mode (0.01 kWh, fetched every 10 minutes) and with the activity including defrost. "Compressor running" is the modulation above 0. No flow rate.
- **Daikin Altherma (P1P2MQTT):** The heat pump's own meters (heat and electricity per mode, backup heater) in whole kWh. They only arrive with the counter request of the bridge switched on ("Counter_Request_Function"). Activity from the flags defrost, hot water, cooling and heating. The hot water entities exist only with the matching field settings of the controller.
- **Waterkotte:** The meters are yearly sums, heat per mode, but compressor electricity as a total only. Wärmewacht assigns the electricity to the running mode, in the look back by the share of heat. A run without a hot water or cooling flag counts as heating (the heating release `status_heating` is no heating state). Enable "Cooling" (`state_cooling`), otherwise cooling counts as heating. There is no starts counter (Wärmewacht counts itself) and no defrost signal.
- **Vaillant (myVAILLANT):** Wärmewacht books hour by hour from the statistics mypyllant writes itself. Set mypyllant's option "Seconds between energy data updates" to 3600 to 7200 seconds, otherwise it fetches the energy only at start. The figures therefore lag one to three hours behind. There is no compressor signal and no defrost, so no cycling. Standby is an hour without environmental yield.

### Keeping the recorder lean

If you exclude entities in the `recorder` configuration (`exclude`) or record only selected ones (`include`): an entity that is not recorded gets **no long-term statistics** either. Wärmewacht reads almost nothing but these statistics, one row per hour.

- **Must be recorded:**
  - Wärmewacht's energy sensors (heat and electricity per mode, standby electricity) for the report, performance curve, heat load, degree days and health check;
  - the outdoor temperature for the same analyses and the sensor check;
  - the flow temperature for "Flow temperature at 0 °C".
- **Should be recorded:**
  - the heat pump's energy meters. Wärmewacht needs them for the time before the setup: look back, "Recalculate look-back" and report. Without them a newly created entry has no look back;
  - the starts counter. Without statistics, "Starts season" counts only from the first value Wärmewacht sees.
- **May be left out:**
  - all other Wärmewacht sensors (performance factors, cycling, costs, health, diagnostics) and the binary sensors. Wärmewacht stores its state itself. Their history in your own charts is missing then, though;
  - compressor state and activity. Wärmewacht reads their history only once at the setup, to add the cycles of the last 10 days.

Example for `include` (check the entity IDs on the device page; the trailing `*` also covers suffixes like `_2`):

```yaml
recorder:
  include:
    entity_globs:
      - sensor.*_heat_heating*
      - sensor.*_heat_hot_water*
      - sensor.*_electricity_heating*
      - sensor.*_electricity_hot_water*
      - sensor.*_standby_electricity*
    entities:
      - sensor.outdoor_temperature   # your outdoor temperature
      - sensor.flow_temperature      # your flow temperature
      - sensor.heat_meter_heating    # your meters, per mode
```

If it is only about the size of the database, a short retention is often enough (`purge_keep_days`, default 10 days). The long-term statistics are not affected by it.

## Installation

Wärmewacht is installed through HACS as a custom repository. Every version is a regular GitHub release.

1. HACS → ⋮ → *Custom repositories* → `https://github.com/waermewacht/integration`, type *Integration*.
2. Search for Wärmewacht and download it. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Wärmewacht*.

## Setup

1. **Name and source:** The name (default "Wärmepumpe") becomes the device name and the prefix of the entity IDs. As source you choose one of the heat pumps found (EMS-ESP, with the MQTT prefix if there are several; Bosch HomeCom with the gateway number) or *Manual*.
2. **Entities:** With a template the form is filled in; every field can be changed. With *Manual* you pick them yourself.

<table>
  <tr>
    <td valign="top"><img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/einrichtung_1.png" alt="Step 1: name and source, the templates found two heat pumps" width="360"></td>
    <td valign="top"><img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/einrichtung_2.png" alt="Step 2: meters for heating, hot water and cooling filled in by the EMS-ESP template" width="360"></td>
  </tr>
</table>

| Section | Field | EMS-ESP (standard format) |
| --- | --- | --- |
| Heating | Heat produced heating (meter) | `sensor.boiler_nrgheat` |
| | Compressor electricity heating | `sensor.boiler_meterheat` |
| | Backup heater heating | `sensor.boiler_auxelecheatnrgconsheating` |
| Hot water | Heat produced hot water (meter) | `sensor.boiler_dhw_nrg` |
| | Compressor electricity hot water | `sensor.boiler_dhw_meter` |
| | Backup heater hot water | `sensor.boiler_dhw_auxelecheatnrgcons` |
| | Hot water temperature (actual, tank) | `sensor.boiler_dhw_curtemp` |
| Cooling | Heat removed cooling (meter) | `sensor.boiler_nrgcool` |
| | Compressor electricity cooling | `sensor.boiler_metercool` |
| Operation | Compressor running (on/off or speed) | `binary_sensor.boiler_hpcompon` |
| | Activity | `sensor.boiler_hpactivity` |
| | Compressor starts total | `sensor.boiler_totalcompstarts` |
| | Compressor electricity total (only without per mode) | – |
| | Backup heater total (only without per mode) | – |
| | Electricity defrost | – |
| | Electricity standby | – |
| Activity from several entities | Defrost running (on/off) | – |
| | Hot water running (on/off) | – |
| | Cooling running (on/off) | – |
| | Heating running (on/off) | – |
| | Set operating mode (cooling?) | – |
| Measurements | Outdoor temperature | `sensor.boiler_outdoortemp` |
| | Flow temperature | `sensor.boiler_hptc1` |
| | Return temperature | `sensor.boiler_hptc0` |
| | Flow rate | `sensor.boiler_pc0flow` |

- The electricity meters per mode are those of the **compressor without backup heater**. Enter the backup heater separately: either per mode or as "Backup heater total", not both. The total is assigned to the mode that is running or ran last. Without an activity it counts as heating.
- If the compressor electricity comes as one meter for all modes (Waterkotte), enter it as "Compressor electricity total" instead of per mode. Wärmewacht assigns it to the running mode like the backup heater; electricity without a compressor run is standby.
- **Electricity defrost** and **Electricity standby** are for sources that keep this electricity in meters of their own (Lambda and iDM templates). Electricity defrost counts towards the mode that is running or ran last (without an activity: heating), electricity standby as standby. EMS-ESP has no such meters.
- The template takes meters in 0.01 kWh where available, otherwise the whole-kWh ones (e.g. `sensor.boiler_nrgsuppheating`). EMS-ESP provides the backup heater per mode in whole kWh only.
- Without "Compressor running" there is no cycling. Without "Activity" no defrosts, no flow-return spread and no mean flow temperature. "Compressor running" may be a binary sensor or a speed or modulation (running above 0). With a manual mapping, Wärmewacht understands the values of EMS-ESP: `0`–`7` or texts such as `heating`, `hot water`, `defrost` (or the German "Heizen", "Warmwasser", "Abtauen").
- The outdoor temperature is used by the [performance curve and heat load](#performance-curve-and-heat-load). Wärmewacht reads its hourly means from the long-term statistics, so the sensor needs statistics (`state_class: measurement`). Wärmewacht only checks the flow rate for plausibility (see [troubleshooting](#troubleshooting)). That needs the activity, and flow and return for the comparison with heat and spread.

- **Activity from several entities** (collapsed section): If the heat pump has no single activity entity but flags (on/off) for defrost, hot water, cooling and heating, enter those. An "on" flag wins in this order: defrost, hot water, cooling, heating. If the compressor runs and no flag is on, the run counts as heating. The *set operating mode* (e.g. "Cool") turns heating into cooling when the activity entity only tells heating from hot water (three-way valve). The templates for Stiebel and HeishaMon fill this in, the one for ViCare the hot water flag.

Several heat pumps: add one entry each.

### Settings

*Wärmewacht → entry → cogwheel (Configure)*. Every change reloads the entry. The fields in the order of the form:

| Setting | Default | Meaning |
| --- | --- | --- |
| Minimum electricity for a ratio | 0.5 kWh | Below it the performance factor is unknown instead of a random value. |
| Short run below | 10 min | Fraunhofer ISE reports cycles under about 10 minutes separately. |
| Critical run below | 6 min | Minimum run time of about 6 minutes according to the Dimplex planning manual. |
| Conspicuous above starts per hour | 3 | More starts within one hour count as conspicuous. Compressor manufacturers give 6 to 12 starts per hour as the upper limit. |
| Backup heater: mild weather from | 5 °C | Health check: daily mean outdoor temperature from which the heat pump should heat alone (own assumption). |
| Efficiency dropped from | 15 % | Health check: drop of the heating performance factor against the previous season at the same outdoor temperature; off again only 5 points lower (own assumption). |
| Thermal disinfection from | 60 °C | Hot water temperature from which a charge counts as thermal disinfection. DVGW W 551 requires 60 °C at the outlet; the storage sensor often reads a little lower. |
| Season starts in | July | Start of the season (heating period July to June). |
| ***Costs and gas comparison (optional)*** | | |
| Electricity price | – | ct/kWh gross. Without it there are no cost sensors. |
| Electricity base price | – | €/year gross, only for a separate heat pump meter (heat pump tariff). On the household meter leave it empty: that base price is paid anyway. |
| Gas working price | – | ct/kWh gross on the gross calorific value (as on the gas bill). For the savings against a gas boiler. |
| Gas base price | – | €/year gross, spread per day. Without it only the working prices are compared. |
| ***Heat load (optional)*** | | |
| Design outdoor temperature | – | °C per DIN/TS 12831-1 for your postcode (e.g. the BWP climate map). For the heat load at the design temperature. |
| Rated heating power at A-7/W35 | – | kW from the data sheet. Gives the sensor "Power per heat load". |
| Smallest heating power | – | kW from the data sheet. Shows whether cycling is to be expected in mild weather. |

Every optional field may stay empty. Sources of the defaults in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md) (German). If you change the season start, Wärmewacht recomputes the current season from the long-term statistics (standby before the setup estimated per hour).

### Reconfigure

*Wärmewacht → ⋮ → Reconfigure* shows the entity form again with the current mapping. The figures booked so far are kept. A newly added meter counts from that moment; the button **Recalculate look-back** adds the time before the setup.

**Recalculate look-back** (button, configuration) computes the energy before the setup anew from the long-term statistics, with today's entities and rules: after adding a meter or when an update improved the rules of the look-back. What Wärmewacht booked since the setup stays. The time between the setup and adding a meter is still missing, and the imported statistics of the own energy sensors before the setup stay as they were. Not for sources with previous-day values (MELCloud, F1p bridge): their statistics do not suit a look-back.

If a template learns a new signal in an update (e.g. the hot water temperature), Wärmewacht adds it at start when it belongs to the same heat pump and the entry has none. What you deliberately remove under *Reconfigure* stays removed.

If you rename a source (entity ID in the entity settings, *Recreate entity IDs* on the device), Wärmewacht follows the new ID itself and reloads the entry shortly after. No need to *Reconfigure*; history and statistics stay, because Home Assistant renames them as well.

## Gas boiler before switching

If you still heat with gas and think about a heat pump, the key figure is the **heat load**: how much power does the house need on the coldest day? Wärmewacht computes it from the gas consumption, with the same [energy signature](#performance-curve-and-heat-load) as for a heat pump. Heating limit, heat per degree day and the hot water share come with it.

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/gasheizung.png" alt="Energy signature from the consumption with weekly points and the line, below heat load per kelvin, heat load at −12 °C, heating limit, heat per degree day, hot water share and consumption of the last 365 days" width="720">

<sub>Cross-check on a real installation, German UI: the heat meters of a Bosch Compress 5800i AW (EMS-ESP) are entered as "gas" here, with efficiency 1. The gas boiler calculation arrives at 112 W/K, the heat pump itself at 107 W/K (last 365 days against the last complete season). With a real gas boiler the last tile shows the gas consumption.</sub>

**Setup:** *Add integration → Wärmewacht*, source **Gas boiler (before switching)**. Then:

| Field | Meaning |
| --- | --- |
| Gas total | One counter for heating and hot water: gas meter (pulse, AI-on-the-edge) or the boiler's counter, in kWh or m³ |
| Gas heating only | instead of "Gas total" if the boiler counts heating and hot water apart (e.g. Viessmann ViCare) |
| Gas hot water | optional, if hot water is counted apart |
| Outdoor temperature | required, with long-term statistics; a nearby weather station is fine |
| Calorific value, Z-number | only for counters in m³, from the gas bill (kWh = m³ × calorific value × Z-number) |

The counters need long-term statistics (state class `total` or `total_increasing`). Wärmewacht reads only those, for the **last 365 days**: if your gas meter's statistics already reach back that far (for example from the energy dashboard), the results appear 2 minutes after the setup. After that Wärmewacht recomputes daily at 3:00. It listens to no states and stores nothing.

**Heat from gas:** gas in kWh on the gross calorific value (as on the bill) times **efficiency 0.87**, the field value of condensing boilers (Jagnow/Wolff, DBU 2004). Older boilers are lower; change it in the settings. The heat load changes in proportion.

**Hot water** does not count towards the heat load. Wärmewacht separates it:

- with a hot water counter of its own: from that one (subtracted from "Gas total");
- with "Gas total" and no hot water counter from the **summer base**: the median daily gas on days with a mean of at least 15 °C (heating limit of VDI 3807) counts as hot water and is taken off every day. This needs at least 14 such days in the 365. Without them (a meter recorded only since autumn) nothing is subtracted and the hot water share stays unknown (`no_summer_days`). The standard heat load is still right, because it comes from the slope alone; the heating limit is then too high.

| Entity | Unit | Meaning |
| --- | --- | --- |
| Heat load per kelvin | W/K | Slope of the energy signature. Attributes as for the heat pump, plus `boiler_efficiency` and `dhw_method` |
| Heat load at design temperature | kW | standard, only with the design outdoor temperature set |
| Heating limit | °C | where the line reaches 0 |
| Heat per degree day | kWh/K·d | heating heat per degree day G20/15, over heating days |
| Hot water share | % | share of the gas for hot water. Attributes `method` (`counter`, `summer_base`, `no_summer_days`, `heating_only`), `summer_days`, `summer_base_kwh_per_day` |
| Gas 365 days | kWh | gas of the last 365 days. Attributes `days` (days with data), `complete`, `heat_kwh` (heat after efficiency) |
| Gas cost 365 days | € | only with a gas price in the settings; with base price |

If a value is unknown, the attribute `reason` says why (`not_analysed_yet`, `no_recorder`, `gas_unit`, `no_calorific_value` or the reasons of the energy signature). The action [Heat load](#heat-load) works for a gas boiler too; it then defaults to the last 365 days. The chart above is the card from the [dashboard examples](#performance-curve-and-energy-signature), with the sensor "Heat load per kelvin" of the gas entry.

**Limits:**

- Boilers mostly estimate their gas from burner time and power instead of measuring it. A real gas meter is more accurate.
- A gas cooker on the same meter counts as hot water (summer base) or as heating; it cannot be separated.
- A fireplace, tiled stove or solar thermal lowers the gas on cold or sunny days. The heat load then comes out too low.

## Entities

All entities belong to a separate device per heat pump. Which ones are created depends on the mapped signals and the settings.

### Performance factors

| Entity | Needs |
| --- | --- |
| COP heating *period* | heat and electricity heating |
| COP hot water *period* | heat and electricity hot water |
| COP heating+DHW *period* | heating or hot water complete |
| EER cooling *period* | heat and electricity cooling |

*Period* is **today**, **yesterday**, **month**, **season** or **total**: up to 20 sensors without a unit. Today and yesterday swing a lot and are therefore disabled by default. The season of cooling is the calendar year: cooling runs from spring to autumn, and a heating season starting in July would split it. "Total" goes as far back as the long-term statistics of your meters at the time of setup.

- Factor per mode = heat / electricity (compressor plus backup heater), **without** standby.
- Heating + hot water = heat of both / (electricity of both + standby). This corresponds to a seasonal performance factor.

The sensors have long-term statistics (`state_class: measurement`). They are a time mean of the quotient, not a balance. For monthly or yearly values use the [energy sensors](#energy) or the [report](#report).

Attributes:

| Attribute | Meaning |
| --- | --- |
| `heat_kwh` | heat in the period |
| `electricity_kwh` | electricity in the period (compressor plus backup heater, without standby) |
| `standby_kwh` | standby in the period (heating + hot water only) |
| `period_start` | start of the period (empty for "total") |
| `counter_step_kwh` | resolution of the coarsest meter involved: 0.01 or 1 kWh |
| `reliable` | `true` if meter rounding accounts for at most 5 % of the electricity |

### Energy

| Entity | Unit | Meaning |
| --- | --- | --- |
| Heat heating / hot water, Heat removed cooling | kWh | heat since the setup (cooling: heat removed) |
| Electricity heating / hot water / cooling | kWh | electricity while the compressor runs, with backup heater and "Electricity defrost", without standby |
| Standby electricity | kWh | electricity while the compressor stands still, all modes, plus the source's "Electricity standby". Attributes from the diary (with the daily analysis, so only with an outdoor temperature): mean power of the last 7 days (`mean_power_w_7d`) against the median of the 30 days before (`reference_w`), smallest and largest day (`min_day_w`, `max_day_w`); `rising` is on from +50 % **and** +10 W (own assumption) |

All with long-term statistics (`total_increasing`). Each sensor is only created if the matching meter is mapped. "Standby electricity" is created when standby can be told apart: with heat and electricity meters of the same mode, or with an electricity meter and "Compressor running" (not with day values from a cloud). Please do not disable them or exclude them from the [recorder](#keeping-the-recorder-lean): the report, the performance curve and the heat load read their statistics for the time after the setup.

**Statistics before the setup:** Once after the setup (for older entries on the update), Wärmewacht writes the hours before it into the statistics of these sensors. They are computed from the statistics of your meters, with standby estimated per hour. Statistics cards then show the months before the setup as well. Wärmewacht only writes hours before the first row Home Assistant recorded itself. About 15 minutes after the start, Wärmewacht shifts the sums once, from the first imported hour on. So they start at 0, and the first bar of a statistics card is not negative. The change per hour stays the same. The hour of the setup is missing up to the moment of the setup.

**Standby:** Electricity of a mode counts as standby if, since the previous meter reading, that mode delivered no heat and the compressor did not run in it. Without a compressor state, only the heat decides. With neither a compressor state nor a heat meter of that mode, its electricity counts as running.

### Cycling

Most cycling sensors need "Compressor running". Defrosts only need the activity. "Starts total" also exists when only the heat pump's starts counter is mapped.

| Entity | Unit | Meaning |
| --- | --- | --- |
| Starts today, Starts yesterday | – | observed compressor starts |
| Starts season | – | Starts since the start of the season from the heat pump's counter and its long-term statistics. If the statistics do not reach back that far, it counts from their first value. Attributes `since` and `per_day`. For comparison: 90 % of the air/water heat pumps in the Fraunhofer field test stay below 5,500 starts a year, about 15 a day. Needs the start counter and the outdoor temperature (set with the daily analysis). |
| Starts total | – | the heat pump's counter if mapped (attribute `source: heat_pump`), otherwise starts observed since the setup (`since_setup`) |
| Run time today | min | compressor run time, in steps of 5 minutes |
| Run time per start today, 7 days, month | min | mean duration of the runs that ended in the period |
| Short runs today | – | runs below the short-run limit; attributes `threshold_minutes`, `critical_runs`, `critical_threshold_minutes` |
| Shortest pause today | min | shortest time between the end of a run and the next start |
| Defrosts today | – | count; attributes `minutes` (duration today), `yesterday` (count yesterday). With the daily analysis (only with an outdoor temperature) for the last 7 days the count (`defrosts_7d`), warm defrosts (`warm_defrosts_7d`, hourly mean of 10 °C or more), mean and longest duration (`mean_minutes_7d`, `longest_minutes_7d`), plus `classes`: defrosts per run hour per 2 K class against the previous season (`factor` = current ÷ previous) |

If the compressor state was missing for more than 5 minutes (Home Assistant or the source down), the affected run counts as uncertain. It is then left out of run time per start, short runs and pauses.

### Conspicuous cycling

Binary sensor (problem), only with "Compressor running". It is on if within the last 24 hours

- there were more starts within one hour than set (default: more than 3) **or**
- at least 3 runs were shorter than the critical run (default: 6 minutes).

Attributes: `max_starts_per_hour`, `critical_runs_24h`, `short_runs_24h`, `starts_per_hour_limit`.

### Hot water charges

A charge is one continuous period of the activity hot water. A defrost in between does not end it. Heat and electricity of the charge come from the hot water meters, without standby. What the meters report up to 5 minutes after the end still counts; with meters in whole kWh (Daikin) up to 2 hours, at most until the next charge. The figure of the last charge then appears that much later. Wärmewacht keeps charges for 40 days.

| Entity | Meaning | Needs |
| --- | --- | --- |
| COP hot water last charge | Heat over electricity (compressor and backup heater) of the last finished charge. Attributes: `start`, `minutes`, `heat_kwh`, `electricity_kwh`, `aux_kwh`, `start_temp`, `max_temp`, `disinfection`, `uncertain` | hot water complete and activity, running meters (not with day or hourly values from a cloud, so not with Bosch HomeCom, ViCare, MELCloud, the F1p bridge and myVAILLANT: the values arrive too late) |
| COP hot water charges 30 days | the same over the normal charges of the last 30 days, without thermal disinfection. Attributes: `charges`, `uncertain`, `mean_minutes`, `mean_heat_kwh`, `mean_lift` (temperature lift in K), `aux_share`, `disinfections` | the same |
| Last thermal disinfection | When the storage last reached the set temperature (default 60 °C after DVGW W 551). A new one counts only after it was 5 K below in between. | hot water temperature |

`uncertain`: the activity was unknown during the charge, or Home Assistant was not running. Such charges count in the ratio, but not in duration, heat and lift per charge.

### Health check

Once a day (around 3 am) Wärmewacht checks for anomalies that cost money or hint at a fault. It says **what** stands out and **how** that shows, not **why**. If the data are not enough, a sensor is *unknown* and gives the reason in the attribute `reason`, never "off" for lack of data. Derived and referenced in [docs/GESUNDHEITSCHECK.md](docs/GESUNDHEITSCHECK.md) (German).

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/gesundheit.png" alt="Problem sensors of the health check: efficiency dropped, backup heater in mild weather, backup heater in hot water charges, conspicuous cycling" width="400">

| Binary sensor (problem) | On if | Needs |
| --- | --- | --- |
| Efficiency dropped | The heating performance factor of the current season is at least 15 % (adjustable) below the previous season at the same outdoor temperature. Off again only 5 points lower. | heating complete and outdoor temperature |
| Hot water efficiency below last year | The performance factor of normal [hot water charges](#hot-water-charges) in the last 30 days is at least 15 % below the same 30 days of the previous year (without thermal disinfection, at least 10 charges on each side). Same time of year, because the cold water is colder in winter. Causes: higher storage temperature, scaled heat exchanger. At the earliest one year after the setup, re-evaluated once a day. | charges and hot water temperature |
| Backup heater in hot water charges | In the last 30 days the backup heater used more than 10 % of the electricity of normal [hot water charges](#hot-water-charges) (without thermal disinfection, at least 10 charges). Re-evaluated after every charge and at midnight. | charges, hot water temperature and a backup heater meter |
| Backup heater on mild days | In the last 7 days, on days with a daily mean of 5 °C or more (adjustable), the backup heater used at least 2 kWh for heating in total. Unknown with fewer than 3 mild days with heating heat in the window. | in addition a backup heater meter |

- **Same weather:** The comparison is per 2 K class of the [performance curve](#performance-curve-and-heat-load), weighted by the heat of the current season. If one season merged classes (common early in a season with few days), Wärmewacht sums the classes of the other over the same range. It needs a common range of at least 4 K with 14 days and 10 kWh of electricity together.
- **Attributes:** Efficiency: `ratio_current`, `ratio_previous_same_weather`, `drop_percent`, `threshold_percent` and `classes` (days and performance factor of both seasons per class). Backup heater: `aux_kwh_7d`, `mild_days_7d`, `min_outdoor_temp`, `threshold_kwh` and `days` (per mild day). Hot water last year: `ratio`, `charges`, `from`, `to`, the same with `previous_` for last year, `change_percent`, `threshold_percent`. The lists are not recorded.
- **Reasons for *unknown*:** `not_analysed_yet` (after start), `no_previous_season`, `too_few_classes`, `too_few_days`, `too_little_electricity`, `comparison_restarted`, `too_few_charges`, `no_previous_year` (fewer than 10 charges last year, e.g. in the first year).
- **Restart efficiency comparison** (button, configuration): after a deliberate change such as a new heating curve. The next 28 days become the new reference; until then "Efficiency dropped" is unknown.
- **Data faults** (meter stands still, source unreachable, outdoor temperature unusable, flow rate implausible or 0, flow and return swapped) are reported as a [repair issue](#troubleshooting), not as a sensor.
- **Diary:** At midnight Wärmewacht adds an entry for the previous day (outdoor temperature, starts, run time per mode, short runs, defrosts, spread, flow temperature, flow rate, energy, hot water charges), for up to 3 years. It is kept in the history file and written once a day. "Flow-return spread 7 days", the rise of standby and the defrosts per class come from it.

### Diagnostics

| Entity | Unit | Meaning | Needs |
| --- | --- | --- | --- |
| Backup heater share month, season | % | backup heater share of the electricity for heating and hot water (with standby) | backup heater meter |
| Flow-return spread today | K | flow minus return, time-weighted over the time the compressor was heating | flow, return and activity |
| Flow temperature today | °C | mean flow temperature, weighted the same way | flow and activity |

### Costs and gas comparison

With an electricity price in the [settings](#settings).

| Entity | Unit | Meaning | Needs |
| --- | --- | --- | --- |
| Electricity cost month, season | € | all electricity of the heat pump (all modes, standby, backup heater) × electricity price, plus the prorated electricity base price; in steps of 10 cents | electricity price and an electricity meter |
| Heat cost per kWh season | €/kWh | cost of heating and hot water (electricity with standby, prorated electricity base price) per kWh of heat; unknown below 0.5 kWh of heat | electricity price, heating or hot water complete |
| Savings vs. gas boiler season | € | gas cost (working price plus prorated gas base price) for the same heat minus the heat pump's cost of heating and hot water (electricity with standby, prorated electricity base price); in whole euros | electricity price, gas working price, heating or hot water complete |

- **Season** means the heating period from the set month (default: 1 July to 30 June). The attribute `period_start` gives its start.
- **Prices** are fixed, as entered in the settings. Wärmewacht does not support dynamic tariffs.
- **Base prices** are spread per day (annual price ÷ 365 or 366). The electricity base price only counts for a separate heat pump meter and belongs to heating and hot water.
- **Gas boiler:** For the same heat (heating and hot water, no cooling) it would need heat ÷ 0.87 of gas on the gross calorific value. 0.87 is the efficiency that field measurements of condensing boilers found (Jagnow/Wolff, DBU 2004). Gas is billed on the gross calorific value, so the figure refers to it.
- **No CO₂ comparison:** it would depend too much on assumptions (average or hourly mix, upstream chains, own PV use, battery, green tariffs).

Attributes of "Savings vs. gas boiler season":

| Attribute | Meaning |
| --- | --- |
| `period_start` | start of the season |
| `heat_kwh` | heat of heating and hot water in the season |
| `heat_pump_cost_eur` | the heat pump's cost of this heat (electricity with standby, prorated electricity base price) |
| `electricity_base_cost_eur` | prorated electricity base price included in it (0 without the setting) |
| `gas_kwh` | gas for the same heat, on the gross calorific value |
| `gas_cost_eur` | gas cost with the prorated base price |
| `gas_base_cost_eur` | prorated gas base price included in it (0 without the setting) |
| `boiler_efficiency` | boiler efficiency on the gross calorific value (0.87) |

### Performance curve and heat load

All sensors in this section need the outdoor temperature plus heat and electricity heating, and the recorder. Wärmewacht computes them 2 minutes after the start and then daily from 3 am, from the long-term statistics (before the setup from the statistics of your meters, like the [report](#report)). The results are kept in memory only. After a restart the sensors are therefore empty for about 2 minutes.

| Entity | Unit | Meaning |
| --- | --- | --- |
| Performance curve heating | timestamp | When it was last computed. The curve is in the attributes. |
| Heat load per kelvin | W/K | Slope of the energy signature of the last complete season. |
| Heat load at design temperature | kW | Standard heat load (line through 0 at 20 °C). Only with the setting design outdoor temperature. |
| Flow-return spread 7 days | K | Spread while heating on cold days (below 5 °C) of the last 7 days, from 10 hours of heating. Also needs flow, return and activity. Attributes `all_days` (every day), `field_reference` and `field_range` (field test WPsmart: 6.8 K, 3.2–9.8 K). No alarm: hydraulics and sensor positions shape the value. |
| Power per heat load | – | Rated heating power from the data sheet divided by the standard heat load. Only with the setting rated heating power. Attributes `measured_factor` (against the measured heat load), `load_at_7c_kw` and, with the smallest heating power, `cycling_expected`. Field mean 1.5 (Fraunhofer WP-QS). |
| Flow temperature at 0 °C | °C | The heating curve as a figure: least-squares line of the flow over the outdoor temperature, read off at 0 °C. Also needs the flow temperature. Per day only hours with heating heat (at least 0.3 kWh) and no hot water count, at least 2 per day; it needs 14 days spanning 6 K. Attributes `slope` (K flow per K outdoor), `r_squared`, `days`, `spread`, `reasons`, `previous_season` and `previous_slope` (the same for the previous season). Shows whether a changed heating curve works. A little below the set value, because pauses within the hour count. |
| Degree days season | K·d | Degree days G20/15 after VDI 3807 from the start of the season to yesterday: per day 20 °C minus the daily mean, only on days below 15 °C. As a meter: a statistics card shows the degree days per month. Attributes `base` (`G20/15`), `days_counted`, `days_missing` (fewer than 20 hourly values), `days_without_heating`. |
| Heat per degree day season | kWh/K·d | Heating heat divided by the degree days, over heating days only (at least 1 kWh of heating heat per day), from 10 K·d. Cool days without heating in summer and autumn would otherwise push it down a lot. Without heating heat it is unknown. Attribute `degree_days_heating` of the degree days sensor: the degree days of these heating days. Attribute `previous_season`: the same value of the whole previous season. A measure of the heat demand of the house, corrected for the weather. It scatters by about 18 % from month to month, so it is a season value only. |

**Performance curve:** heating performance factor per 2-K class of the daily mean outdoor temperature, without standby. The current and the previous season stay apart: a changed heating curve would blur both.

- A day counts with at least 20 hourly outdoor values and only if it delivered heat for heating. Hours without an outdoor value are dropped together with their energy. Values outside −35 to 45 °C are discarded.
- A class needs at least 7 days. Sparse edge classes are merged into their neighbour. Sparse classes in between stay, but have `sparse: true` and `ratio: null`.

Attributes of "Performance curve heating":

| Attribute | Meaning |
| --- | --- |
| `current_start`, `previous_start` | start of the current and the previous season |
| `current`, `previous` | classes of the current and the previous season, coldest first |

Each class has `lower` and `upper` (°C, lower bound included), `days`, `mean_outdoor` (mean of the daily means), `heat_kwh`, `electricity_kwh`, `ratio` (`null` below the minimum electricity or for a sparse class) and `sparse`.

**Heat load (energy signature):** weekly mean heating power over the weekly mean outdoor temperature. Only heat for heating counts, not hot water. Wärmewacht fits a straight line through the weeks.

- A week starts on Monday 00:00. It counts with at least 6 full days and a mean below 12 °C.
- A full day has at least 20 hourly outdoor values, no cooling and at least 1 kWh of heating heat. Days with the heating off (summer mode held by hand, a gas boiler not switched on yet in autumn) do not count: they say nothing about the house and would make the line too steep. Values outside −35 to 45 °C are discarded. A frost day has a daily mean below 0 °C.
- There is a result only with at least 8 weeks, a spread of 10 K between the coldest and the warmest week, 5 frost days and a falling line. Otherwise the value stays empty and `reasons` gives the reason.
- "Measured" (`measured_kw`) is the line at the design outdoor temperature, with internal and solar gains. "Standard" (`standard_kw`) is the line moved in parallel through 0 at 20 °C, without these gains. The sensor "Heat load at design temperature" shows the standard value.

Attributes of "Heat load per kelvin":

| Attribute | Meaning |
| --- | --- |
| `start`, `end` | period evaluated (the last complete season) |
| `sufficient` | `true` if the data suffice for a result |
| `reasons` | reasons if not: `too_few_weeks`, `spread_too_small`, `too_few_frost_days`, `slope_not_negative` |
| `week_count` | valid weeks |
| `spread` | spread of the weekly means in K |
| `frost_days` | frost days in the valid weeks |
| `intercept_kw`, `slope_kw_per_k` | line P = a + b · T (a in kW, b in kW/K, negative) |
| `r_squared` | coefficient of determination of the line |
| `heating_limit` | heating limit in °C, where the line reaches 0 |
| `design_temp` | design outdoor temperature from the settings |
| `measured_kw`, `standard_kw` | heat load at the design outdoor temperature, measured and standard |
| `weeks` | valid weeks with `start`, `days`, `hours`, `mean_outdoor`, `power_kw` |

Without sufficient data the values of the line are `null`. For other periods and for heating with hot water, use the [actions](#actions). Charts are in the [dashboard examples](#dashboard-examples).

## Actions

*Settings → Tools → Actions* (formerly *Developer tools → Actions*) → choose the action, the heat pump and the period, "Show response". The response can also be used in scripts and automations (`response_variable`). Times without a time zone are local time of your Home Assistant. All actions need the recorder.

### Report

**Wärmewacht: Report** returns heat, electricity and performance factors of a period, broken down by month.

```yaml
action: waermewacht.report
data:
  config_entry: <choose entry>
  start: "2026-09-01 00:00:00"
```

Without start: start of the current season. Without end: now. Example response (made-up values):

```yaml
start: "2026-09-01T00:00:00+02:00"
end: "2026-10-27T10:15:00+01:00"
data_until: "2026-10-27T10:00:00+01:00"
estimated_until: "2026-10-20T15:00:00+02:00"
heating:
  heat_kwh: 440.7
  electricity_kwh: 110.8
  ratio: 3.98
dhw:
  heat_kwh: 240.6
  electricity_kwh: 87.6
  ratio: 2.75
heating_dhw:
  heat_kwh: 681.3
  electricity_kwh: 198.4
  standby_kwh: 32
  ratio: 2.96
cooling:
  heat_kwh: 21.5
  electricity_kwh: 6.2
  ratio: 3.47
months:
  - month: 2026-09
    heating:
      heat_kwh: 38.4
      electricity_kwh: 9.6
      ratio: 4
    dhw:
      heat_kwh: 121.7
      electricity_kwh: 44.1
      ratio: 2.76
    heating_dhw:
      heat_kwh: 160.1
      electricity_kwh: 53.7
      standby_kwh: 17.9
      ratio: 2.24
    cooling:
      heat_kwh: 21.5
      electricity_kwh: 6.2
      ratio: 3.47
  - month: 2026-10
    heating:
      heat_kwh: 402.3
      electricity_kwh: 101.2
      ratio: 3.98
    dhw:
      heat_kwh: 118.9
      electricity_kwh: 43.5
      ratio: 2.73
    heating_dhw:
      heat_kwh: 521.2
      electricity_kwh: 144.7
      standby_kwh: 14.1
      ratio: 3.28
    cooling:
      heat_kwh: 0
      electricity_kwh: 0
      ratio: null
```

- `heating`, `dhw`, `heating_dhw` and `cooling` only appear for modes that are set up. For `cooling`, `ratio` is the EER; `null` means unknown (no heat or below the minimum electricity).
- `electricity_kwh` is without standby; for `heating_dhw`, `standby_kwh` enters the factor.
- `degree_days` (total and per month, only with an outdoor temperature): degree days G20/15, heating heat per degree day (`kwh_per_degree_day`, heating days of at least 1 kWh only, from 10 K·d) and the days counted. Only whole days with at least 20 hourly values count.
- `data_until`: until when hourly values were available. `estimated_until`: until when the figures come from the heat pump's own meters (see below); `null` if the period starts after the setup.
- **Before the setup**, Wärmewacht calculates from the long-term statistics of your meters. They hold no compressor state. So the electricity of a mode in an hour without heat of that mode counts as standby. Hours with a run keep their minutes of standby as running; the factor per mode comes out slightly lower there.
- **From the first full hour after the setup** the report uses the statistics of Wärmewacht's own [energy sensors](#energy).

### Performance curve

**Wärmewacht: Performance curve** (`waermewacht.performance_curve`) computes the [curve](#performance-curve-and-heat-load) for any period.

```yaml
action: waermewacht.performance_curve
data:
  config_entry: <choose entry>
  start: "2025-07-01 00:00:00"
  end: "2026-07-01 00:00:00"
  scope: heating_dhw
```

| Field | Default | Meaning |
| --- | --- | --- |
| `start` | start of the current season | Do not mix seasons with different heating curves. |
| `end` | now | |
| `scope` | `heating` | `heating`, or `heating_dhw` (heating and hot water; both without standby) |

The response contains `start`, `end`, `scope` and `classes`: the classes as in the sensor's attribute `current`.

### Heat load

**Wärmewacht: Heat load** (`waermewacht.heat_load`) computes the [energy signature](#performance-curve-and-heat-load) for any period.

```yaml
action: waermewacht.heat_load
data:
  config_entry: <choose entry>
  design_outdoor_temp: -12
```

| Field | Default | Meaning |
| --- | --- | --- |
| `start` | start of the last complete season (gas boiler: 365 days ago) | |
| `end` | end of the last complete season; with `start`: now | |
| `design_outdoor_temp` | design outdoor temperature from the settings | °C, for `measured_kw` and `standard_kw` |

The response contains the same values as the attributes of "Heat load per kelvin".

Performance curve and heat load report an error when no outdoor temperature is mapped or the recorder is missing.

## Dashboard examples

The entity IDs depend on the name of the entry (here the default "Wärmepumpe") and on the language of Home Assistant at setup; the examples use the IDs of an English setup. Add a card with *Edit dashboard → Add card → Manual*.

### Statistics card: heat and electricity per month

The [report](#report) gives a performance factor per month. A statistics card shows heat and electricity per month, standby as a bar of its own. The months before the setup come from the long-term statistics of the meters:

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/monatsdiagramm.png" alt="Bar chart of heat and electricity per month for heating and hot water, plus standby (German UI)" width="480">

```yaml
type: statistics-graph
title: Heat and electricity per month
chart_type: bar
period: month
stat_types:
  - change
days_to_show: 365
entities:
  - entity: sensor.warmepumpe_heat_heating
    name: Heat heating
  - entity: sensor.warmepumpe_heat_hot_water
    name: Heat hot water
  - entity: sensor.warmepumpe_electricity_heating
    name: Electricity heating
  - entity: sensor.warmepumpe_electricity_hot_water
    name: Electricity hot water
  - entity: sensor.warmepumpe_standby_electricity
    name: Standby
```

### Performance curve and energy signature

<img src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/screenshots/analyse.png" alt="Heating performance curve over the outdoor temperature, energy signature with the heat load line and figures such as heat load, heating limit and degree days" width="720">

Both charts need the HACS card [apexcharts-card](https://github.com/RomRider/apexcharts-card). It only has a time axis. The examples therefore map the outdoor temperature from −15 to 25 °C onto the 40 hours that end at the end of today (1 K = 1 hour). The axis labels convert the time back to °C. Adjust the limits of the y axis (`min`, `max`) to your installation.

Performance curve heating, previous and current season:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: "Performance curve heating (x: daily mean outdoor temperature)"
graph_span: 40h
span:
  end: day
now:
  show: false
apex_config:
  chart:
    height: 260
  xaxis:
    tickAmount: 8
    labels:
      formatter: "EVAL:(v, ts) => { const t = typeof ts === 'number' ? ts : Number(v); const e = new Date(); e.setHours(24, 0, 0, 0); return Math.round((t - e.getTime()) / 3600000 + 25) + ' °C'; }"
    tooltip:
      enabled: false
  yaxis:
    - min: 2
      max: 6
      tickAmount: 4
      decimalsInFloat: 1
      title:
        text: Performance factor
  tooltip:
    x:
      formatter: "EVAL:(v) => { const e = new Date(); e.setHours(24, 0, 0, 0); return (Math.round(((v - e.getTime()) / 3600000 + 25) * 10) / 10) + ' °C'; }"
  markers:
    size: 5
  legend:
    show: true
grid_options:
  columns: full
  rows: 6
series:
  - entity: sensor.warmepumpe_performance_curve_heating
    name: Previous season
    color: "#2F6FB0"
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      return (entity.attributes.previous || []).filter(c => c.ratio !== null).map(c => [x((c.lower + c.upper) / 2), c.ratio]);
  - entity: sensor.warmepumpe_performance_curve_heating
    name: Current season
    color: "#DE5E32"
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      return (entity.attributes.current || []).filter(c => c.ratio !== null).map(c => [x((c.lower + c.upper) / 2), c.ratio]);
```

Energy signature: the weeks as points and the line from the design outdoor temperature (−12 °C without the setting) to the heating limit (otherwise 15 °C):

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: "Energy signature (x: weekly mean outdoor temperature)"
graph_span: 40h
span:
  end: day
now:
  show: false
apex_config:
  chart:
    height: 260
  xaxis:
    tickAmount: 8
    labels:
      formatter: "EVAL:(v, ts) => { const t = typeof ts === 'number' ? ts : Number(v); const e = new Date(); e.setHours(24, 0, 0, 0); return Math.round((t - e.getTime()) / 3600000 + 25) + ' °C'; }"
    tooltip:
      enabled: false
  yaxis:
    - min: 0
      max: 4
      tickAmount: 4
      decimalsInFloat: 1
      title:
        text: Heating power kW
  tooltip:
    x:
      formatter: "EVAL:(v) => { const e = new Date(); e.setHours(24, 0, 0, 0); return (Math.round(((v - e.getTime()) / 3600000 + 25) * 10) / 10) + ' °C'; }"
  markers:
    size: [5, 0]
  legend:
    show: true
grid_options:
  columns: full
  rows: 6
series:
  - entity: sensor.warmepumpe_heat_load_per_kelvin
    name: Weeks
    color: "#2F6FB0"
    stroke_width: 0
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      return (entity.attributes.weeks || []).map(w => [x(w.mean_outdoor), w.power_kw]).sort((a, b) => a[0] - b[0]);
  - entity: sensor.warmepumpe_heat_load_per_kelvin
    name: Line
    color: "#DE5E32"
    stroke_width: 2
    extend_to: false
    curve: straight
    show:
      legend_value: false
      in_header: false
    data_generator: |
      const e0 = new Date(); e0.setHours(24, 0, 0, 0);
      const x = (t) => e0.getTime() + (t - 25) * 3600000;
      const a = entity.attributes;
      if (a.intercept_kw == null) return [];
      const lo = a.design_temp ?? -12, hi = a.heating_limit ?? 15;
      return [[x(lo), a.intercept_kw + a.slope_kw_per_k * lo], [x(hi), Math.max(0, a.intercept_kw + a.slope_kw_per_k * hi)]];
```

`start` and `end` are predefined in a `data_generator`, so the end of today is called `e0` (`e` in the formatters).

## System boundary and limits

- **System boundary:** A performance factor always applies to the meters it comes from. The usual boundaries follow SEPEMO: H1 heat pump or compressor, H2 plus fan or brine pump, H3 plus backup heater, H4 plus circulation and charging pumps. With the compressor meters of EMS-ESP, Wärmewacht corresponds to **roughly H1**, with backup heater **H3**. Circulation pumps, controller and storage charging pumps are missing. A system factor with an external electricity meter (as on [heatpumpmonitor.org](https://heatpumpmonitor.org/), H4) is therefore lower.
- **Standby as reported by the heat pump:** While the compressor stands still, Bosch heat pumps book electricity steadily into the heating meter, observed at about 25 W, also in summer. The constant value suggests a model value of the firmware rather than a measurement. Only an external meter can tell whether it is right. The factors per mode do not depend on it; heating + hot water does.
- **Whole-kWh meters:** Not every model provides meters in 0.01 kWh. With whole kWh a short period is inaccurate (1 kWh of 5 kWh is 20 %). The attribute `reliable` only becomes `true` once the electricity reaches 20 times the meter resolution.
- **Defrosting:** Bosch heat meters subtract the heat removed during defrosting (observed on a CS5800i/CS6800i); Wärmewacht therefore books net heat. How the meters of other makers handle it is not settled.
- **Look back:** Wärmewacht estimates the standby before the setup hour by hour (see [report](#report)). The sensors miss the partial hour of the setup: the long-term statistics have no value for it yet.
- **Gaps:** If Home Assistant was not running, the first meter reading afterwards books the whole increase. Whether that was running or standby is decided by the heat in the same span.

## Troubleshooting

Wärmewacht reports problems under *Settings → Repairs*. This happens at the earliest 10 minutes after start, so entities have time after a restart.

- **Entity missing:** A mapped entity no longer exists, e.g. because it was deleted. Choose it again under *Wärmewacht → ⋮ → Reconfigure*. Wärmewacht follows a renamed entity itself (since 0.2.2).
- **Unusable unit:** An energy meter does not report Wh, kWh or MWh. Its values are not counted until the unit fits. Check the unit at the source or choose another meter under *Reconfigure*.
- **Day counter instead of total:** An energy meter fell below half at least twice in the last four days, like an "energy today" counter. With an own mapping Wärmewacht needs total (lifetime) counters; it does not count a day counter correctly, on days below 1 kWh not at all. Choose the matching total counter under *Reconfigure*. Since 0.2.2 the setup refuses such counters. Templates for sources with day values (Bosch HomeCom, ViCare, MELCloud) are not affected.
- **Meter stands still:** The compressor ran, but a meter of the current mode did not rise: 1 hour for meters with decimals, 6 hours for whole kWh or daily values. Usually the source no longer sends values, the entity is disabled or the wrong meter is mapped. Check the source, enable the entity or choose the right meter under *Reconfigure*.
- **Source unreachable:** A mapped entity has been `unavailable` for more than 60 minutes. Check the source (EMS-ESP, MQTT, cloud).
- **Outdoor temperature unusable:** It has not changed for 48 hours or was outside −35 to +45 °C for more than 3 hours yesterday. The performance curve, heat load and health check depend on it. Check the sensor or choose another entity under *Reconfigure*.
- **Flow rate implausible:** Yesterday the measured flow rate while heating was more than ten times above or below the value heat and spread give (after at least 1 hour of heating, 1 kWh of heat and 2 K of spread). Usually the unit is wrong (e.g. l/h reported as L/min) or it is the wrong sensor. Check the entity or choose another one under *Reconfigure*. The notice disappears after a day with a fitting flow rate.
- **Flow rate 0 while heating:** 15 minutes of heating with a flow rate of 0. Usually the sensor delivers no real value. Check the entity or remove it under *Reconfigure*.
- **Flow and return swapped?** Yesterday the flow was on average more than 1 K colder than the return while heating, after at least one hour of heating. Usually the entities or the sensors are swapped; a flow sensor behind a mixing valve can also cause it. Swap the entities under *Reconfigure* or check the sensors. The notice disappears after a day with a normal spread.
- **Activity entity without an activity:** The mapped activity reports values that carry no activity on this device (for ViCare E3 controllers "ready" / "not_ready"). Defrosts and the mode of runs stay empty. Remove the entity under *Reconfigure*.
- **No new energy values:** For a source with hourly values (myVAILLANT) no new hourly energy values arrived for more than 30 hours. Set mypyllant's option "Seconds between energy data updates" to 3600 to 7200 seconds, or update one of its energy sensors with an automation. Wärmewacht catches up on the missing hours as soon as they arrive.
- **Energy entities changed meaning:** An energy entity no longer measures what it was chosen for. With myVAILLANT this happens when the cloud reorders its energy series, for example after cooling was enabled. Wärmewacht books nothing until the entities are chosen again under *Reconfigure*.

The issues disappear on their own once the problem is solved.

More:

- **Factor stays unknown:** There was no heat in the period or less electricity than the minimum. That is normal for heating in summer.
- **No cycling:** "Compressor running" is not mapped.
- **Performance curve or heat load empty:** After a restart wait about 2 minutes. If the outdoor temperature or the energy sensors have no long-term statistics (excluded from the [recorder](#keeping-the-recorder-lean)?), both stay empty. For the heat load, the attribute `reasons` tells what is missing.
- **Diagnostics:** *Wärmewacht → entry → ⋮ → Download diagnostics*. **Debug log:** *Wärmewacht → ⋮ → Enable debug logging*.

## Privacy

Wärmewacht calculates locally, reads only the entities you map and makes no network requests. Per entry it stores the booked energy, the runs and hot water charges of the last 40 days and the diary (up to 3 years). The diagnostics file contains the mapping, the settings, the current states of the source entities (that is, meter readings) and energy totals, but not the name of the entry. Under `source` it lists every entity of the source devices with manufacturer, model and firmware; serial numbers and entry ids in it are replaced by made-up values of the same length, device names and areas are left out. Check it before sharing it publicly.

## Removal

1. *Settings → Devices & services → Wärmewacht* → ⋮ at the entry → *Delete*. The stored figures and repair issues of this entry are deleted with it.
2. Optional: HACS → Wärmewacht → ⋮ → *Remove*, then restart Home Assistant.

The long-term statistics of the deleted sensors stay in Home Assistant until you remove them under *Settings → Tools → Statistics* (formerly *Developer tools*).

## Reporting issues

Please open an [issue](https://github.com/waermewacht/integration/issues), ideally with the diagnostics file, the heat pump model and the versions of Home Assistant, Wärmewacht and, if used, EMS-ESP. Please report security vulnerabilities privately, see [SECURITY.md](SECURITY.md).

**Do you own a heat pump with a beta template?** Especially for Viessmann (ViCare), Mitsubishi Ecodan (MELCloud) and Vaillant (myVAILLANT) some assumptions rest on the integrations' source code only. Feedback with a diagnostics file after a few days of operation helps to confirm them: whether the figures are plausible and when the day values jump.

**Heat pump without a template?** Set up Wärmewacht manually (at least heat and electricity for heating and "Compressor running") and attach the diagnostics file to an issue. Under `source` it lists every entity of the devices behind it, with platform, unique_id, unit and state. That is enough to build a template.

## Related projects

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance): performance factors from heat and electricity meters, vendor-neutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml): extensive analysis for Daikin Altherma with ESPAltherma. The right choice for Daikin.
- [eedc – Energie Effizienz Data Center](https://github.com/supernova1963/eedc-homeassistant): add-on analysing the whole household (PV, storage, EV, heat pump) including economics. Complements Wärmewacht, which goes deeper into the heat pump.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/): public comparison of many installations. Wärmewacht uses the same terms (SEPEMO boundaries, starts) so that figures can be put in context.

## License

MIT
