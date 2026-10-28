<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Wärmewacht – Every kilowatt-hour. Every cycle." src="https://raw.githubusercontent.com/waermewacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/waermewacht/integration?color=DE5E32)](https://github.com/waermewacht/integration/releases)
[![CI](https://github.com/waermewacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/waermewacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

[Deutsch](https://github.com/waermewacht/integration/blob/main/README.md) · **English**

> **Beta.** Wärmewacht is new; the current versions are betas. Feedback is welcome, see [Reporting issues](#reporting-issues).

**How efficient is your heat pump really?** Wärmewacht ("heat watch") calculates performance factors per operating mode and period in Home Assistant, counts starts, short runs and defrosts and shows a few diagnostic values. It works from the entities your heat pump already provides. Wärmewacht only reads and never controls anything. No cloud, no network requests.

> **A guide, not an expert diagnosis.** The figures depend on what your heat pump's meters measure. See [System boundary and limits](#system-boundary-and-limits).

The user interface is available in German and English and follows the language of your Home Assistant.

## Features

- **Performance factors** for heating, hot water and heating + hot water, plus the **energy efficiency ratio for cooling (EER)**, each for today, yesterday, month, season and total.
- **Heat and electricity sensors per mode** and a sensor for **standby**, with long-term statistics for statistics cards.
- **Cycling:** starts, run time, run time per start, short runs, shortest pause, defrosts and a binary sensor **Conspicuous cycling**.
- **Diagnostics:** backup heater share, flow-return spread and mean flow temperature while heating (with an activity).
- **Hot water per charge:** performance factor of the last charge and of the charges of the last 30 days, last thermal disinfection.
- **Health check:** reports a dropped efficiency at the same weather and the backup heater on mild days. Repair issues when a meter stands still, a source fails or the outdoor temperature is stuck.
- **Costs and gas comparison** (optional, with fixed prices): electricity cost, heat cost per kWh and the savings against a gas boiler.
- **Performance curve and heat load:** heating performance factor over the outdoor temperature and heat load from the energy signature. As sensors and via actions for any period.
- **Report for any period** via an action, broken down by month. Also **before the setup**, as far back as the long-term statistics of your meters go.
- **Templates for EMS-ESP and Bosch HomeCom:** find Bosch/Buderus heat pumps on their own and fill in the entities. As beta also Luxtronik (alpha innotec, Novelan), Stiebel Eltron/Tecalor (ISG), Panasonic Aquarea (HeishaMon), Lambda and iDM. Other heat pumps are mapped by hand.
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

- Home Assistant 2026.4 or newer.
- The recorder (on by default in Home Assistant) for the look back, the report, the performance curve and the heat load.
- At least one mode with a **heat meter** and a **compressor electricity meter**: cumulative energy sensors in Wh, kWh or MWh.

| Source | Status |
| --- | --- |
| [EMS-ESP](https://github.com/emsesp/EMS-ESP32) (MQTT) with Bosch/Buderus heat pumps, e.g. CS5800i/CS6800i, WLW176i/WLW186i | template, tested on a CS5800i/CS6800i |
| [Bosch HomeCom](https://github.com/serbanb11/bosch-homecom-hass) (`bosch_homecom`, local and cloud) | template, new, compared with EMS-ESP on the same CS5800i/CS6800i |
| any heat and electricity meters | manual mapping |

The EMS-ESP template recognizes the heat pump by the `boiler` device. It needs the compressor state (`hpcompon`) and the heating meters. It finds the entities through the entity registry, not by entity ID, so renaming and all of EMS-ESP's naming formats are fine. It understands the activity (`hpactivity`) in all EMS-ESP languages and in the index format.

The HomeCom template needs the energy per mode ("Wärme erzeugt Heizung", "Strom Kompressor Heizung" etc.; English: heat produced and compressor energy per heating, hot water and cooling). `bosch_homecom` creates these entities disabled: enable them first. The setup shows which ones are still disabled. "Compressor running" is the compressor speed above 0. Compared with EMS-ESP, HomeCom has limits:

- **Day values from the cloud:** the energy arrives as the day's sum, up to two hours late. Wärmewacht books it when it arrives, so "today" lags behind. The cloud never delivers the last one or two hours of a day (observed up to 0.5 kWh per day).
- **Standby:** electricity of a fetch that brought no heat of the same mode.
- **No activity:** no defrosts, no flow-return spread and no mean flow temperature.
- **No flow rate:** `bosch_homecom` reports "L/min" but delivers l/h.

If you run EMS-ESP, use EMS-ESP: meters in 0.01 kWh every minute, and the activity.

## Installation

Wärmewacht is installed through HACS as a custom repository. Every version is a regular GitHub release, betas included.

1. HACS → ⋮ → *Custom repositories* → `https://github.com/waermewacht/integration`, type *Integration*.
2. Search for Wärmewacht and download it. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Wärmewacht*.

## Setup

1. **Name and source:** The name (default "Wärmepumpe") becomes the device name and the prefix of the entity IDs. As source you choose one of the heat pumps found (EMS-ESP, with the MQTT prefix if there are several; Bosch HomeCom with the gateway number) or *Manual*.
2. **Entities:** With a template the form is filled in; every field can be changed. With *Manual* you pick them yourself.

| Section | Field | EMS-ESP (standard format) |
| --- | --- | --- |
| Heating | Heat heating (meter) | `sensor.boiler_nrgheat` |
| | Compressor electricity heating | `sensor.boiler_meterheat` |
| | Backup heater heating | `sensor.boiler_auxelecheatnrgconsheating` |
| Hot water | Heat hot water (meter) | `sensor.boiler_dhw_nrg` |
| | Compressor electricity hot water | `sensor.boiler_dhw_meter` |
| | Backup heater hot water | `sensor.boiler_dhw_auxelecheatnrgcons` |
| | Hot water temperature | `sensor.boiler_dhw_curtemp` |
| Cooling | Heat removed cooling (meter) | `sensor.boiler_nrgcool` |
| | Compressor electricity cooling | `sensor.boiler_metercool` |
| Operation | Compressor running | `binary_sensor.boiler_hpcompon` |
| | Activity | `sensor.boiler_hpactivity` |
| | Compressor starts total | `sensor.boiler_totalcompstarts` |
| | Backup heater total | – |
| Measurements | Outdoor temperature | `sensor.boiler_outdoortemp` |
| | Flow temperature | `sensor.boiler_hptc1` |
| | Return temperature | `sensor.boiler_hptc0` |
| | Flow rate | `sensor.boiler_pc0flow` |

- The electricity meters per mode are those of the **compressor without backup heater**. Enter the backup heater separately: either per mode or as "Backup heater total", not both. The total is assigned to the mode that is running or ran last. Without an activity it counts as heating.
- The template takes meters in 0.01 kWh where available, otherwise the whole-kWh ones (e.g. `sensor.boiler_nrgsuppheating`). EMS-ESP provides the backup heater per mode in whole kWh only.
- Without "Compressor running" there is no cycling. Without "Activity" no defrosts, no flow-return spread and no mean flow temperature. "Compressor running" may be a binary sensor or a speed or modulation (running above 0). With a manual mapping, Wärmewacht understands the values of EMS-ESP: `0`–`7` or texts such as `heating`, `hot water`, `defrost` (or the German "Heizen", "Warmwasser", "Abtauen").
- The outdoor temperature is used by the [performance curve and heat load](#performance-curve-and-heat-load). Wärmewacht reads its hourly means from the long-term statistics, so the sensor needs statistics (`state_class: measurement`). The flow rate can already be mapped, but is not evaluated yet.

- **Activity from several entities** (collapsed section): If the heat pump has no single activity entity but flags (on/off) for defrost, hot water, cooling and heating, enter those. An "on" flag wins in this order: defrost, hot water, cooling, heating. The *set operating mode* (e.g. "Cool") turns heating into cooling when the activity entity only tells heating from hot water (three-way valve). The templates for Stiebel and HeishaMon fill this in.

Several heat pumps: add one entry each.

### Settings

*Wärmewacht → entry → cogwheel (Configure)*. Every change reloads the entry. The fields in the order of the form:

| Setting | Default | Meaning |
| --- | --- | --- |
| Minimum electricity for a ratio | 0.5 kWh | Below it the performance factor is unknown instead of a random value. |
| Short run below | 10 min | Fraunhofer ISE reports cycles under about 10 minutes separately. |
| Critical run below | 6 min | Minimum run time of about 6 minutes according to the Dimplex planning manual. |
| Conspicuous above starts per hour | 3 | More starts within one hour count as conspicuous. Compressor manufacturers give 6 to 12 starts per hour as the upper limit. |
| Season starts in | July | Start of the season (heating period July to June). |
| ***Health check*** | | |
| Backup heater: mild weather from | 5 °C | Daily mean outdoor temperature from which the heat pump should heat alone (own assumption). |
| Thermal disinfection from | 60 °C | Hot water temperature from which a charge counts as thermal disinfection. DVGW W 551 requires 60 °C at the outlet; the storage sensor often reads a little lower. |
| Efficiency dropped from | 15 % | Drop of the heating performance factor against the previous season at the same outdoor temperature; off again only 5 points lower (own assumption). |
| ***Costs and gas comparison (optional)*** | | |
| Electricity price | – | ct/kWh gross. Without it there are no cost sensors. |
| Electricity base price | – | €/year gross, only for a separate heat pump meter (heat pump tariff). On the household meter leave it empty: that base price is paid anyway. |
| Gas working price | – | ct/kWh gross on the gross calorific value (as on the gas bill). For the savings against a gas boiler. |
| Gas base price | – | €/year gross, spread per day. Without it only the working prices are compared. |
| ***Heat load (optional)*** | | |
| Design outdoor temperature | – | °C per DIN/TS 12831-1 for your postcode (e.g. the BWP climate map). For the heat load at the design temperature. |

Every optional field may stay empty. Sources of the defaults in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md) (German). If you change the season start, Wärmewacht recomputes the current season from the long-term statistics (standby before the setup estimated per hour).

### Reconfigure

*Wärmewacht → ⋮ → Reconfigure* shows the entity form again with the current mapping. The figures booked so far are kept. A newly added meter counts from that moment.

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
| Electricity heating / hot water / cooling | kWh | electricity while the compressor runs, with backup heater, without standby |
| Standby electricity | kWh | electricity while the compressor stands still, all modes |

All with long-term statistics (`total_increasing`). Each sensor is only created if the matching meter is mapped. Please do not disable them: the report, the performance curve and the heat load read their statistics for the time after the setup.

**Statistics before the setup:** Once after the setup (for older entries on the update), Wärmewacht writes the hours before it into the statistics of these sensors. They are computed from the statistics of your meters, with standby estimated per hour. Statistics cards then show the months before the setup as well. Wärmewacht only writes hours before the first row Home Assistant recorded itself. About 15 minutes after the start, Wärmewacht shifts the sums once, from the first imported hour on. So they start at 0, and the first bar of a statistics card is not negative. The change per hour stays the same. The hour of the setup is missing up to the moment of the setup.

**Standby:** Electricity of a mode counts as standby if, since the previous meter reading, that mode delivered no heat and the compressor did not run in it. Without a compressor state, only the heat decides.

### Cycling

Most cycling sensors need "Compressor running". Defrosts only need the activity. "Starts total" also exists when only the heat pump's starts counter is mapped.

| Entity | Unit | Meaning |
| --- | --- | --- |
| Starts today, Starts yesterday | – | observed compressor starts |
| Starts season | – | Starts since the start of the season from the heat pump's counter and its long-term statistics. If the statistics do not reach back that far, it counts from their first value. Attributes `since` and `per_day`. For comparison: 90 % of the air/water heat pumps in the Fraunhofer field test stay below 5,500 starts a year, about 15 a day. Needs the start counter and the outdoor temperature (set with the daily analysis). |
| Starts total | – | the heat pump's counter if mapped (attribute `source: heat_pump`), otherwise starts observed since the setup (`since_setup`) |
| Run time today | min | compressor run time |
| Run time per start today, 7 days, month | min | mean duration of the runs that ended in the period |
| Short runs today | – | runs below the short-run limit; attributes `threshold_minutes`, `critical_runs`, `critical_threshold_minutes` |
| Shortest pause today | min | shortest time between the end of a run and the next start |
| Defrosts today | – | count; attributes `minutes` (duration today) and `yesterday` (count yesterday) |

If the compressor state was missing for more than 5 minutes (Home Assistant or the source down), the affected run counts as uncertain. It is then left out of run time per start, short runs and pauses.

### Conspicuous cycling

Binary sensor (problem), only with "Compressor running". It is on if within the last 24 hours

- there were more starts within one hour than set (default: more than 3) **or**
- at least 3 runs were shorter than the critical run (default: 6 minutes).

Attributes: `max_starts_per_hour`, `critical_runs_24h`, `short_runs_24h`, `starts_per_hour_limit`.

### Hot water charges

A charge is one continuous period of the activity hot water. A defrost in between does not end it. Heat and electricity of the charge come from the hot water meters, without standby. What the meters report up to 5 minutes after the end still counts. Wärmewacht keeps charges for 40 days.

| Entity | Meaning | Needs |
| --- | --- | --- |
| COP hot water last charge | Heat over electricity (compressor and backup heater) of the last finished charge. Attributes: `start`, `minutes`, `heat_kwh`, `electricity_kwh`, `aux_kwh`, `start_temp`, `max_temp`, `disinfection`, `uncertain` | hot water complete and activity, running meters (not Bosch HomeCom: daily values arrive too late) |
| COP hot water charges 30 days | the same over the normal charges of the last 30 days, without thermal disinfection. Attributes: `charges`, `uncertain`, `mean_minutes`, `mean_heat_kwh`, `mean_lift` (temperature lift in K), `aux_share`, `disinfections` | the same |
| Last thermal disinfection | When the storage last reached the set temperature (default 60 °C after DVGW W 551). A new one counts only after it was 5 K below in between. | hot water temperature |

`uncertain`: the activity was unknown during the charge, or Home Assistant was not running. Such charges count in the ratio, but not in duration, heat and lift per charge.

### Health check

Once a day (around 3 am) Wärmewacht checks for anomalies that cost money or hint at a fault. It says **what** stands out and **how** that shows, not **why**. If the data are not enough, a sensor is *unknown* and gives the reason in the attribute `reason`, never "off" for lack of data. Derived and referenced in [docs/GESUNDHEITSCHECK.md](docs/GESUNDHEITSCHECK.md) (German).

| Binary sensor (problem) | On if | Needs |
| --- | --- | --- |
| Efficiency dropped | The heating performance factor of the current season is at least 15 % (adjustable) below the previous season at the same outdoor temperature. Off again only 5 points lower. | heating complete and outdoor temperature |
| Backup heater in hot water charges | In the last 30 days the backup heater used more than 10 % of the electricity of normal [hot water charges](#hot-water-charges) (without thermal disinfection, at least 10 charges). | charges, hot water temperature and a backup heater meter |
| Backup heater on mild days | In the last 7 days, on days with a daily mean of 5 °C or more (adjustable), the backup heater used at least 2 kWh for heating in total. | in addition a backup heater meter |

- **Same weather:** The comparison is per 2 K class of the [performance curve](#performance-curve-and-heat-load), weighted by the heat of the current season. If one season merged classes (common early in a season with few days), Wärmewacht sums the classes of the other over the same range. It needs a common range of at least 4 K with 14 days and 10 kWh of electricity together.
- **Attributes:** Efficiency: `ratio_current`, `ratio_previous_same_weather`, `drop_percent`, `threshold_percent` and `classes` (days and performance factor of both seasons per class). Backup heater: `aux_kwh_7d`, `mild_days_7d`, `min_outdoor_temp`, `threshold_kwh` and `days` (per mild day). The lists are not recorded.
- **Reasons for *unknown*:** `not_analysed_yet` (after start), `no_previous_season`, `too_few_classes`, `too_few_days`, `too_little_electricity`, `comparison_restarted`, `too_few_charges`.
- **Restart efficiency comparison** (button, configuration): after a deliberate change such as a new heating curve. The next 28 days become the new reference; until then "Efficiency dropped" is unknown.
- **Data faults** (meter stands still, source unreachable, outdoor temperature unusable, flow and return swapped) are reported as a [repair issue](#troubleshooting), not as a sensor.
- **Diary:** At midnight Wärmewacht adds an entry for the previous day (outdoor temperature, starts, run time per mode, short runs, defrosts, spread, flow temperature, energy), for up to 3 years. It is kept in the history file and written once a day. Later checks will evaluate it.

### Diagnostics

| Entity | Unit | Meaning | Needs |
| --- | --- | --- | --- |
| Backup heater share month, season | % | backup heater share of the electricity for heating and hot water (with standby) | backup heater meter |
| Flow-return spread today | K | flow minus return, time-weighted over the time the compressor was heating | flow, return and activity |
| Flow temperature today | °C | mean flow temperature, weighted the same way | flow and activity |

### Costs and gas comparison

With an electricity price in the [settings](#settings) and heating or hot water mapped completely.

| Entity | Unit | Meaning | Needs |
| --- | --- | --- | --- |
| Electricity cost month, season | € | all electricity of the heat pump (all modes, standby, backup heater) × electricity price, plus the prorated electricity base price | electricity price |
| Heat cost per kWh season | €/kWh | cost of heating and hot water (electricity with standby, prorated electricity base price) per kWh of heat; unknown below 0.5 kWh of heat | electricity price |
| Savings vs. gas boiler season | € | gas cost (working price plus prorated gas base price) for the same heat minus the heat pump's cost of heating and hot water (electricity with standby, prorated electricity base price) | electricity price and gas working price |

- **Season** means the heating period from the set month (default: 1 July to 30 June). The attribute `period_start` gives its start.
- **Prices** are fixed, as entered in the settings. Wärmewacht does not support dynamic tariffs.
- **Base prices** are spread per day (annual price ÷ 365 or 366). The electricity base price only counts for a separate heat pump meter and belongs to heating and hot water.
- **Gas boiler:** For the same heat (heating and hot water, no cooling) it would need heat ÷ 0.87 of gas on the gross calorific value. 0.87 is the efficiency that field measurements of condensing boilers found (Jagnow/Wolff, DBU 2004). Gas is billed on the gross calorific value, so the figure refers to it.
- **No CO₂ comparison:** it would depend too much on assumptions (average or hourly mix, upstream chains, own PV use, battery, green tariffs).

Attributes of "Savings vs. gas boiler season":

| Attribute | Meaning |
| --- | --- |
| `heat_kwh` | heat of heating and hot water in the season |
| `heat_pump_cost_eur` | the heat pump's cost of this heat (electricity with standby, prorated electricity base price) |
| `electricity_base_cost_eur` | prorated electricity base price included in it (0 without the setting) |
| `gas_kwh` | gas for the same heat, on the gross calorific value |
| `gas_cost_eur` | gas cost with the prorated base price |
| `gas_base_cost_eur` | prorated gas base price included in it (0 without the setting) |
| `boiler_efficiency` | boiler efficiency on the gross calorific value (0.87) |

### Performance curve and heat load

Both need the outdoor temperature plus heat and electricity heating, and the recorder. Wärmewacht computes them 2 minutes after the start and then daily from 3 am, from the long-term statistics (before the setup from the statistics of your meters, like the [report](#report)). The results are kept in memory only. After a restart the sensors are therefore empty for about 2 minutes.

| Entity | Unit | Meaning |
| --- | --- | --- |
| Performance curve heating | timestamp | When it was last computed. The curve is in the attributes. |
| Heat load per kelvin | W/K | Slope of the energy signature of the last complete season. |
| Heat load at design temperature | kW | Standard heat load (line through 0 at 20 °C). Only with the setting design outdoor temperature. |
| Flow temperature at 0 °C | °C | The heating curve as a figure: least-squares line of the flow over the outdoor temperature, read off at 0 °C. Per day only hours with heating heat (at least 0.3 kWh) and no hot water count, at least 2 per day; it needs 14 days spanning 6 K. Attributes `slope` (K flow per K outdoor), `r_squared`, `days`, `spread`, `reasons`, `previous_season` and `previous_slope` (the same for the previous season). Shows whether a changed heating curve works. A little below the set value, because pauses within the hour count. |
| Degree days season | K·d | Degree days G20/15 after VDI 3807 from the start of the season to yesterday: per day 20 °C minus the daily mean, only on days below 15 °C. As a meter: a statistics card shows the degree days per month. Attributes `days_counted`, `days_missing` (fewer than 20 hourly values), `days_without_heating`. |
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
- A full day has at least 20 hourly outdoor values and no cooling. Values outside −35 to 45 °C are discarded. A frost day has a daily mean below 0 °C.
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
| `start` | start of the last complete season | |
| `end` | end of the last complete season; with `start`: now | |
| `design_outdoor_temp` | design outdoor temperature from the settings | °C, for `measured_kw` and `standard_kw` |

The response contains the same values as the attributes of "Heat load per kelvin".

Performance curve and heat load report an error when no outdoor temperature is mapped or the recorder is missing.

## Dashboard examples

The entity IDs depend on the name of the entry (here the default "Wärmepumpe") and on the language of Home Assistant at setup; the examples use the IDs of an English setup. Add a card with *Edit dashboard → Add card → Manual*.

### Statistics card: heat and electricity per month

The [report](#report) gives a performance factor per month. A statistics card shows heat and electricity per month:

```yaml
type: statistics-graph
title: Heating per month
chart_type: bar
period: month
stat_types:
  - change
days_to_show: 365
entities:
  - entity: sensor.warmepumpe_heat_heating
    name: Heat
  - entity: sensor.warmepumpe_electricity_heating
    name: Electricity
```

### Performance curve and energy signature

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
- **Defrosting:** Whether Bosch heat meters subtract the heat removed during defrosting is not settled.
- **Look back:** Wärmewacht estimates the standby before the setup hour by hour (see [report](#report)). The sensors miss the partial hour of the setup: the long-term statistics have no value for it yet.
- **Gaps:** If Home Assistant was not running, the first meter reading afterwards books the whole increase. Whether that was running or standby is decided by the heat in the same span.

## Troubleshooting

Wärmewacht reports problems under *Settings → Repairs*. This happens at the earliest 10 minutes after start, so entities have time after a restart.

- **Entity missing:** A mapped entity no longer exists, e.g. after renaming. Choose it again under *Wärmewacht → ⋮ → Reconfigure*.
- **Unusable unit:** An energy meter does not report Wh, kWh or MWh. Its values are not counted until the unit fits.
- **Meter stands still:** The compressor ran, but a meter of the current mode did not rise: 1 hour for meters with decimals, 6 hours for whole kWh or daily values. Usually the source no longer sends values, the entity is disabled or the wrong meter is mapped.
- **Source unreachable:** A mapped entity has been `unavailable` for more than 60 minutes. Check the source (EMS-ESP, MQTT, cloud).
- **Outdoor temperature unusable:** It has not changed for 48 hours or was outside −35 to +45 °C for hours yesterday. The performance curve, heat load and health check depend on it.
- **Flow and return swapped?** Yesterday the flow was on average more than 1 K colder than the return while heating, after at least one hour of heating. Usually the entities or the sensors are swapped; a flow sensor behind a mixing valve can also cause it. The notice disappears after a day with a normal spread.

The issues disappear on their own once the problem is solved.

More:

- **Factor stays unknown:** There was no heat in the period or less electricity than the minimum. That is normal for heating in summer.
- **No cycling:** "Compressor running" is not mapped.
- **Performance curve or heat load empty:** After a restart wait about 2 minutes. If the outdoor temperature has no long-term statistics, both stay empty. For the heat load, the attribute `reasons` tells what is missing.
- **Diagnostics:** *Wärmewacht → entry → ⋮ → Download diagnostics*. **Debug log:** *Wärmewacht → ⋮ → Enable debug logging*.

## Privacy

Wärmewacht calculates locally, reads only the entities you map and makes no network requests. Per entry it stores the booked energy and the runs of the last 40 days. The diagnostics file contains the mapping, the settings, the current states of the source entities (that is, meter readings) and energy totals, but not the name of the entry. Under `source` it lists every entity of the source devices with manufacturer, model and firmware; serial numbers and entry ids in it are replaced by made-up values of the same length, device names and areas are left out. Check it before sharing it publicly.

## Removal

1. *Settings → Devices & services → Wärmewacht* → ⋮ at the entry → *Delete*. The stored figures and repair issues of this entry are deleted with it.
2. Optional: HACS → Wärmewacht → ⋮ → *Remove*, then restart Home Assistant.

The long-term statistics of the deleted sensors stay in Home Assistant until you remove them under *Settings → Tools → Statistics* (formerly *Developer tools*).

## Reporting issues

Please open an [issue](https://github.com/waermewacht/integration/issues), ideally with the diagnostics file, the heat pump model and the versions of Home Assistant, Wärmewacht and, if used, EMS-ESP. Please report security vulnerabilities privately, see [SECURITY.md](SECURITY.md).

**Heat pump without a template?** Set up Wärmewacht manually (at least heat and electricity for heating and "Compressor running") and attach the diagnostics file to an issue. Under `source` it lists every entity of the devices behind it, with platform, unique_id, unit and state. That is enough to build a template.

## Related projects

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance): performance factors from heat and electricity meters, vendor-neutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml): extensive analysis for Daikin Altherma with ESPAltherma. The right choice for Daikin.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/): public comparison of many installations. Wärmewacht uses the same terms (SEPEMO boundaries, starts) so that figures can be put in context.

## License

MIT
