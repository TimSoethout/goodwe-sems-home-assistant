# Goodwe SEMS scraper for Home Assistant

## Setup

Crude sensor for Home Assistant that scrapes from GoodWe SEMS portal. Put the following files in `custom_components/sems/` in your Home Assistant config dir:
- `sensor.py`
- `__init__.py`
- `manifest.json`

For example by running `../custom_components$ git clone git@github.com:TimSoethout/goodwe-sems-home-assistant.git sems`.
And update configuration.

Example entry in `configuration.yaml`:

```
sensor:
  - platform: sems
    username: 'XXXX'
    password: 'XXXX'
    scan_interval: 60
```

Use the credentials you use to login to https://www.semsportal.com/. 

`scan_interval` controls how often the sensor updates/scrapes. By default this seems to be every 60 seconds.

## Screenies

![Overview icon](images/sems-icon.png)

![Detail window](images/sems-details.png)

## Credits

Reuses code from https://github.com/Sprk-nl/goodwe_sems_portal_scraper.
