# GoodWe SEMS API integration for Home Assistant

{% if prerelease %}
### NB!: This is a Beta version!
{% endif %}

## Easiest install method via HACS

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)

The repository folder structure is compatible with [HACS](https://hacs.xyz) and is included by default in HACS.

Install HACS via: https://hacs.xyz/docs/installation/manual.
Then search for "SEMS" in the Integrations tab (under Community).

## Setup

Crude sensor for Home Assistant that scrapes from GoodWe SEMS portal. Copy all the files in `custom_components/sems/` in your Home Assistant config dir:
- `sensor.py`
- `__init__.py`
- `manifest.json`

And update configuration. The ID of your Power Station can be retrieved by logging in to the SEMS Portal with your credentials:
https://www.semsportal.com

After login you'll see the ID in your URL. E.g.:
https://www.semsportal.com/powerstation/powerstatussnmin/12345678-1234-1234-1234-123456789012

In this example the ID of the Power Station is: 12345678-1234-1234-1234-123456789012

Example entry in `configuration.yaml`:

```
sensor:
  - platform: sems
    username: 'XXXX'
    password: 'XXXX'
    station_id : '12345678-1234-1234-1234-123456789012'
    scan_interval: 60

# Optional/example
# A template to ease access to the data as "sensor.pv_outputpower" etc.
  - platform: template
    sensors:
      pv_outputpower:
        value_template: '{{ states.sensor.sems_portal.attributes.outputpower }}'
        unit_of_measurement: 'W'
        friendly_name: "PV Power output"
      pv_temperature:
        value_template: '{{ states.sensor.sems_portal.attributes.tempperature }}'
        unit_of_measurement: 'C'
        friendly_name: "PV Temperature"
      pv_eday:
        value_template: '{{ states.sensor.sems_portal.attributes.eday }}'
        unit_of_measurement: 'kWh'
        friendly_name: "PV energy day"
      pv_etotal:
        value_template: '{{ states.sensor.sems_portal.attributes.etotal }}'
        unit_of_measurement: 'kWh'
        friendly_name: "PV energy total"
      pv_iday:
        value_template: '{{ states.sensor.sems_portal.attributes.iday }}'
        unit_of_measurement: '€'
        friendly_name: "PV income day"
      pv_itotal:
        value_template: '{{ states.sensor.sems_portal.attributes.itotal }}'
        unit_of_measurement: '€'
        friendly_name: "PV income total"
      pv_excess:
        value_template: '{{ states.sensor.sems_portal.attributes.pmeter }}'
        unit_of_measurement: 'W'
        friendly_name: "PV spare"
      # battery soc
      pv_soc:
        value_template: '{{ states.sensor.sems_portal.attributes.soc }}'
        unit_of_measurement: '%'
        friendly_name: "Battery power"
      # PV output power only
      pv_outputpower:
        value_template: '{{ states.sensor.sems_portal.attributes.outputpower }}'
        unit_of_measurement: 'W'
        friendly_name: "PV Power output"
```

Use the credentials you use to login to https://www.semsportal.com/.

`scan_interval` controls how often the sensor updates/scrapes. By default this seems to be every 60 seconds.

## Screenies

![Overview icon](images/sems-icon.png)

![Detail window](images/sems-details.png)

## Debug info

Add the last line in `configuration.yaml` in the relevant part of `logger`:

```yaml
logger:
  default: info
  logs:
    custom_components.sems: debug
```

## Credits

Reuses code from https://github.com/Sprk-nl/goodwe_sems_portal_scraper.
Generous contributions done by various helpful community members.