# Wärmewacht

[![Release](https://img.shields.io/github/v/release/waermewacht/integration)](https://github.com/waermewacht/integration/releases)
[![CI](https://github.com/waermewacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/waermewacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[Deutsch](https://github.com/waermewacht/integration/blob/main/README.md) · **English**

> **Beta, work in progress.** Wärmewacht is new and not yet meant for everyday use. There is no release yet. Feedback is welcome – see [Reporting issues](#reporting-issues).

**How efficient is your heat pump really?** Wärmewacht ("heat watch") calculates performance factors per operating mode and period in Home Assistant, counts starts, short runs and defrosts and shows a few diagnostic values. It works from the entities your heat pump already provides. Wärmewacht only reads and never controls anything. No cloud, no network requests.

> **A guide, not an expert diagnosis.** The figures depend on what your heat pump's meters measure – see [System boundary and limits](#system-boundary-and-limits).

The user interface is available in German and English and follows the language of your Home Assistant.

## Features

- **Performance factors** for heating, hot water and heating + hot water, plus the **energy efficiency ratio for cooling (EER)** – each for today, yesterday, month, season and total.
- **Heat and electricity sensors per mode** and a sensor for **standby**, with long-term statistics for statistics cards.
- **Cycling:** starts, run time, run time per start, short runs, shortest pause, defrosts and a binary sensor **Conspicuous cycling**.
- **Diagnostics:** backup heater share, flow-return spread and mean flow temperature while heating.
- **Report for any period** via an action, broken down by month – also **before the setup**, as far back as the long-term statistics of your meters go.
- **Template for EMS-ESP:** finds Bosch/Buderus heat pumps on its own and fills in the entities. Other heat pumps are mapped by hand.
- **Easy on SD cards:** writes at most every 10 minutes, at the end of a run, at midnight and on shutdown. Sensors update once a minute and on events.

## What Wärmewacht does differently from template sensors

- **Performance factor of a period = Σ heat / Σ electricity**, never the mean of daily values.
- **Unknown instead of 0:** Without heat or below the minimum electricity (default 0.5 kWh) a performance factor is unknown. Zeros would drag means and statistics down.
- **Standby kept separate:** Electricity while the compressor stands still does not count in the factor per mode, but it does in heating + hot water. Fraunhofer ISE calculates the same way in its field tests.
- **Cooling never enters the seasonal factor.** It has its own EER.
- **Cycling from real compressor runs:** A Home Assistant restart in the middle of a run is not a new start. If the heat pump switches from heating to hot water without stopping, it stays one run. A run that was already going when first seen does not count as a start.
- **Meter resets and steps back:** Small steps back (up to 0.1 kWh) are ignored, a reset sets a new baseline, implausible jumps are not booked. `unknown` and `unavailable` never count as 0.
- **Look back from the long-term statistics:** Today, yesterday, month, season and total already include the time before the setup.

## Requirements

- Home Assistant 2026.4 or newer.
- The recorder (on by default in Home Assistant) for the look back and the report.
- At least one mode with a **heat meter** and a **compressor electricity meter**: cumulative energy sensors in Wh, kWh or MWh.

| Source | Status |
| --- | --- |
| [EMS-ESP](https://github.com/emsesp/EMS-ESP32) (MQTT) with Bosch/Buderus heat pumps, e.g. CS5800i/CS6800i, WLW176i/WLW186i | template, tested on a CS5800i/CS6800i |
| Bosch HomeCom (`bosch_homecom`) | template to follow |
| any heat and electricity meters | manual mapping |

The EMS-ESP template recognizes the heat pump by the `boiler` device. It needs the compressor state (`hpcompon`) and the heating meters. It finds the entities through the entity registry, not by entity ID – renaming and all of EMS-ESP's naming formats are fine. It understands the activity (`hpactivity`) in all EMS-ESP languages and in the index format.

## Installation

Installable from the first release on.

1. HACS → ⋮ → *Custom repositories* → `https://github.com/waermewacht/integration`, type *Integration*.
2. Search for Wärmewacht and download it. Restart Home Assistant.
3. *Settings → Devices & services → Add integration → Wärmewacht*.

## Setup

1. **Name and source:** The name (default "Wärmepumpe") becomes the device name and the prefix of the entity IDs. As source you choose one of the EMS-ESP heat pumps found, with their MQTT prefix if there are several EMS-ESP, or *Manual*.
2. **Entities:** With a template the form is filled in; every field can be changed. With *Manual* you pick them yourself.

| Section | Field | EMS-ESP (standard format) |
| --- | --- | --- |
| Heating | Heat heating (meter) | `sensor.boiler_nrgheat` |
| | Compressor electricity heating | `sensor.boiler_meterheat` |
| | Backup heater heating | `sensor.boiler_auxelecheatnrgconsheating` |
| Hot water | Heat hot water (meter) | `sensor.boiler_dhw_nrg` |
| | Compressor electricity hot water | `sensor.boiler_dhw_meter` |
| | Backup heater hot water | `sensor.boiler_dhw_auxelecheatnrgcons` |
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

- The electricity meters per mode are those of the **compressor without backup heater**. Enter the backup heater separately: either per mode or as "Backup heater total", not both. The total is assigned to the mode that is currently running.
- The template takes meters in 0.01 kWh where available, otherwise the whole-kWh ones (e.g. `sensor.boiler_nrgsuppheating`). EMS-ESP provides the backup heater per mode in whole kWh only.
- Without "Compressor running" there is no cycling. Without "Activity" no defrosts. With a manual mapping, Wärmewacht understands the values of EMS-ESP: `0`–`7` or texts such as `heating`, `hot water`, `defrost` (or the German "Heizen", "Warmwasser", "Abtauen").
- Outdoor temperature and flow rate can already be mapped, but are only evaluated in a later version.

Several heat pumps: add one entry each.

### Settings

*Wärmewacht → entry → cogwheel (Configure)*. Every change reloads the entry.

| Setting | Default | Meaning |
| --- | --- | --- |
| Minimum electricity for a ratio | 0.5 kWh | Below it the performance factor is unknown instead of a random value. |
| Short run below | 10 min | Fraunhofer ISE reports cycles under about 10 minutes separately. |
| Critical run below | 6 min | Minimum run time of about 6 minutes according to the Dimplex planning manual. |
| Conspicuous above starts per hour | 3 | More starts within one hour count as conspicuous. Compressor manufacturers give 6 to 12 starts per hour as the upper limit. |
| Season starts in | July | Start of the season (heating period July to June). |

Sources of the defaults in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md) (German). If you change the season start, Wärmewacht recomputes the current season from the long-term statistics (standby before the setup estimated per hour).

### Reconfigure

*Wärmewacht → ⋮ → Reconfigure* shows the entity form again with the current mapping. The figures booked so far are kept. A newly added meter counts from that moment.

## Entities

All entities belong to a separate device per heat pump. Which ones are created depends on the mapped signals.

### Performance factors

| Entity | Needs |
| --- | --- |
| COP heating *period* | heat and electricity heating |
| COP hot water *period* | heat and electricity hot water |
| COP heating + hot water *period* | heating or hot water complete |
| EER cooling *period* | heat and electricity cooling |

*Period* is **today**, **yesterday**, **month**, **season** or **total** – up to 20 sensors without a unit. Today and yesterday swing a lot and are therefore disabled by default. "Total" goes as far back as the long-term statistics of your meters at the time of setup.

- Factor per mode = heat / electricity (compressor plus backup heater), **without** standby.
- Heating + hot water = heat of both / (electricity of both + standby). This corresponds to a seasonal performance factor.

Attributes:

| Attribute | Meaning |
| --- | --- |
| `heat_kwh` | heat in the period |
| `electricity_kwh` | electricity in the period (compressor plus backup heater, without standby) |
| `standby_kwh` | standby in the period (heating + hot water only) |
| `period_start` | start of the period (empty for "total") |
| `counter_step_kwh` | resolution of the coarsest meter involved: 0.01 or 1 kWh |
| `reliable` | `true` if meter rounding accounts for at most 5 % of the electricity |

These sensors deliberately have no long-term statistics: Home Assistant would average quotients. For monthly or yearly values use the energy sensors and the [report](#report-for-a-period).

### Energy

| Entity | Unit | Meaning |
| --- | --- | --- |
| Heat heating / hot water, Heat removed cooling | kWh | heat since the setup (cooling: heat removed) |
| Electricity heating / hot water / cooling | kWh | electricity while the compressor runs, with backup heater, without standby |
| Standby electricity | kWh | electricity while the compressor stands still, all modes |

All with long-term statistics (`total_increasing`). Each sensor is only created if the matching meter is mapped. Please do not disable them: the report reads their statistics for the time after the setup.

**Standby:** Electricity of a mode counts as standby if, since the previous meter reading, that mode delivered no heat and the compressor did not run in it. Without a compressor state, only the heat decides.

### Cycling

Only with "Compressor running"; defrosts need the activity.

| Entity | Unit | Meaning |
| --- | --- | --- |
| Starts today, Starts yesterday | – | observed compressor starts |
| Starts total | – | the heat pump's counter if mapped (attribute `source: heat_pump`), otherwise starts observed since the setup (`since_setup`) |
| Run time today | h | compressor run time |
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

### Diagnostics

| Entity | Unit | Meaning | Needs |
| --- | --- | --- | --- |
| Backup heater share month, season | % | backup heater share of the electricity for heating and hot water (with standby) | backup heater meter |
| Flow-return spread today | K | flow minus return, time-weighted over the time the compressor was heating | flow and return |
| Flow temperature today | °C | mean flow temperature, weighted the same way | flow |

## Statistics card: heat and electricity per month

The [report](#report-for-a-period) gives a performance factor per month. A statistics card shows heat and electricity per month (*Edit dashboard → Add card → Manual*); the entity IDs depend on your name and language:

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

## Report for a period

*Settings → Tools → Actions* (formerly *Developer tools → Actions*) → **Wärmewacht: Report**, choose the heat pump and the period, "Show response":

```yaml
action: waermewacht.report
data:
  config_entry: <choose entry>
  start: "2026-09-01 00:00:00"
```

Without start: start of the current season. Without end: now. Times without a time zone are local time of your Home Assistant. Example response (made-up values):

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
- `data_until`: until when hourly values were available. `estimated_until`: until when the figures come from the heat pump's own meters (see below); `null` if the period starts after the setup.
- **Before the setup**, Wärmewacht calculates from the long-term statistics of your meters. They hold no compressor state. So the electricity of a mode in an hour without heat of that mode counts as standby. Hours with a run keep their minutes of standby as running; the factor per mode comes out slightly lower there.
- **From the first full hour after the setup** the report uses the statistics of Wärmewacht's own [energy sensors](#energy).

The response can also be used in scripts and automations (`response_variable`).

## System boundary and limits

- **System boundary:** A performance factor always applies to the meters it comes from. The usual boundaries follow SEPEMO: H1 heat pump or compressor, H2 plus fan or brine pump, H3 plus backup heater, H4 plus circulation and charging pumps. With the compressor meters of EMS-ESP, Wärmewacht corresponds to **roughly H1**, with backup heater **H3**. Circulation pumps, controller and storage charging pumps are missing. A system factor with an external electricity meter (as on [heatpumpmonitor.org](https://heatpumpmonitor.org/), H4) is therefore lower.
- **Standby as reported by the heat pump:** While the compressor stands still, Bosch heat pumps book electricity steadily into the heating meter, observed at about 25 W, also in summer. The constant value suggests a model value of the firmware rather than a measurement. Only an external meter can tell whether it is right. The factors per mode do not depend on it; heating + hot water does.
- **Whole-kWh meters:** Not every model provides meters in 0.01 kWh. With whole kWh a short period is inaccurate (1 kWh of 5 kWh is 20 %). The attribute `reliable` only becomes `true` once the electricity reaches 20 times the meter resolution.
- **Defrosting:** Whether Bosch heat meters subtract the heat removed during defrosting is not settled.
- **Look back:** Wärmewacht estimates the standby before the setup hour by hour (see [report](#report-for-a-period)). The sensors miss the partial hour of the setup: the long-term statistics have no value for it yet.
- **Gaps:** If Home Assistant was not running, the first meter reading afterwards books the whole increase. Whether that was running or standby is decided by the heat in the same span.
- **Not yet included:** performance curve over outdoor temperature, cost and CO₂ compared with a gas boiler, heat load.

## Troubleshooting

Wärmewacht reports problems under *Settings → Repairs* (at the earliest 10 minutes after start, so entities have time after a restart):

- **Entity missing:** A mapped entity no longer exists, e.g. after renaming. Choose it again under *Wärmewacht → ⋮ → Reconfigure*.
- **Unusable unit:** An energy meter does not report Wh, kWh or MWh. Its values are not counted until the unit fits.

The issues disappear on their own once the problem is solved.

More:

- **Factor stays unknown:** There was no heat in the period or less electricity than the minimum. That is normal for heating in summer.
- **No cycling:** "Compressor running" is not mapped.
- **Diagnostics:** *Wärmewacht → entry → ⋮ → Download diagnostics*. **Debug log:** *Wärmewacht → ⋮ → Enable debug logging*.

## Privacy

Wärmewacht calculates locally, reads only the entities you map and makes no network requests. Per entry it stores the booked energy and the runs of the last 40 days. The diagnostics file contains the mapping, the settings, the current states of the source entities (that is, meter readings) and energy totals, but not the name of the entry. Check it before sharing it publicly.

## Removal

1. *Settings → Devices & services → Wärmewacht* → ⋮ at the entry → *Delete*. The stored figures and repair issues of this entry are deleted with it.
2. Optional: HACS → Wärmewacht → ⋮ → *Remove*, then restart Home Assistant.

The long-term statistics of the deleted sensors stay in Home Assistant until you remove them under *Settings → Tools → Statistics* (formerly *Developer tools*).

## Reporting issues

Please open an [issue](https://github.com/waermewacht/integration/issues) – ideally with the diagnostics file, the heat pump model and the versions of Home Assistant, Wärmewacht and, if used, EMS-ESP. Please report security vulnerabilities privately, see [SECURITY.md](SECURITY.md).

## Related projects

- [home-assistant-heat-pump-performance](https://github.com/vandecook/home-assistant-heat-pump-performance) – performance factors from heat and electricity meters, vendor-neutral.
- [daikin_cycle_ml](https://github.com/elRadix/daikin_cycle_ml) – extensive analysis for Daikin Altherma with ESPAltherma. The right choice for Daikin.
- [heatpumpmonitor.org](https://heatpumpmonitor.org/) – public comparison of many installations. Wärmewacht uses the same terms (SEPEMO boundaries, starts) so that figures can be put in context.

## License

MIT
