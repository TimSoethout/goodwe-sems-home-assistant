# GoodWe SEMS API integration for Home Assistant

[![Paypal-shield]](https://www.paypal.com/donate?business=9NWEEX4P6998J&currency_code=EUR)
<a href="https://www.buymeacoffee.com/TimSoethout" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="20"></a>
<a href="https://github.com/sponsors/timsoethout"><img alt="Sponsor" src="https://img.shields.io/badge/sponsor-30363D?&logo=GitHub-Sponsors&logoColor=#white" height="20"/></a>

Integration for Home Assistant that retrieves PV data from GoodWe SEMS API.

![GitHub Repo stars](https://img.shields.io/github/stars/TimSoethout/goodwe-sems-home-assistant)
[![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/TimSoethout/goodwe-sems-home-assistant/total)](https://tooomm.github.io/github-release-stats/?username=TimSoethout&repository=goodwe-sems-home-assistant)
[![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/TimSoethout/goodwe-sems-home-assistant/latest/total)](https://tooomm.github.io/github-release-stats/?username=TimSoethout&repository=goodwe-sems-home-assistant)

## Setup

### Easiest install method via HACS

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

The repository folder structure is compatible with [HACS](https://hacs.xyz) and is included by default in HACS.

Install HACS via: https://hacs.xyz/docs/installation/manual.
Then search for "SEMS" in the Integrations tab (under Community). Click `HACS` > `Integrations` > `Explore and Download Repositories` > search for `SEMS` > click the result > `Download`.

### Manual Setup

Crude sensor for Home Assistant that scrapes from GoodWe SEMS portal. Copy all the files in `custom_components/sems/` to `custom_components/sems/` your Home Assistant config dir.

## Configure integration

The required ID of your Power Station is automatically retrieved when left empty. It will pick the first found ID.

To manually find you Power Station ID, log in to the SEMS Portal with your credentials:
https://www.semsportal.com

After login you'll see the ID in your URL, e.g.:
https://semsportal.com/PowerStation/PowerStatusSnMin/12345678-1234-1234-1234-123456789012

In this example the ID of the Power Station is: 12345678-1234-1234-1234-123456789012

In the home assistant GUI, go to `Configuration` > `Integrations` and click the `Add Integration` button. Search for `GoodWe SEMS API`.

Fill in the required configuration and it should find your inverters.

### Optional: control the invertor power output via the "switch" entity

It is possible to temporarily pause the energy production via "downtime" functionality available on the invertor. This is exposed as a switch and can be used in your own automations.

Please note that it is using an undocumented API and can take a few minutes for the invertor to pick up the change. It takes approx 60 seconds to start again when the invertor is in a downtime mode.

### Recommended: use visitor account if you do not need to control the inverter

In case you are only reading the inverter stats, you can use a Visitor (read-only) account.

Create via the official app, or via the web portal:
Login to www.semsportal.com, go to https://semsportal.com/powerstation/stationInfonew. Create a new visitor account.
Login to the visitor account once to accept the EULA. Now you should be able to use it in this component.

## Screenies

![Detail window](images/sems-details.webp)

![Add as Integration](images/search-integration.webp)

![Integration configuration flow](images/integration-flow.webp)

## Debug info

Enable debugging in the GUI, by going to the integration, and selecting "Enable Debug Logging" in the top right corner. [https://www.home-assistant.io/docs/configuration/troubleshooting/#enabling-debug-logging](See HA documentation for more info.)

Or add the last line in `configuration.yaml` in the relevant part of `logger`:

```yaml
logger:
  default: info
  logs:
    custom_components.sems: debug
```

## Notes

* Sometimes the SEMS API is a bit slow, so time-out messages may occur in the log as `[ERROR]`. The component should continue to work normally and try fetch again the next minute.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines on how to contribute to this project.

### Quick Development Setup

- Setup HA development environment using https://developers.home-assistant.io/docs/development_environment
- clone this repo in config directory:
  - `cd core/config`
  - `git clone git@github.com:TimSoethout/goodwe-sems-home-assistant.git`
- go to terminal in remote VSCode environment
- `cd core/config/custom_components`
- `ln -s ../goodwe-sems-home-assistant/custom_components/sems sems`

### Linting

Run the same lint checks as the CI workflow:

```bash
ruff check custom_components/
ruff format --check custom_components/
mypy custom_components/ --ignore-missing-imports --python-version 3.13
```

To fix lint issues locally:

```bash
ruff check --fix custom_components/
ruff format custom_components/
```

For more information, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Credits

Inspired by https://github.com/Sprk-nl/goodwe_sems_portal_scraper and https://github.com/bouwew/sems2mqtt .
Also supported by generous contributions by various helpful community members.

[Paypal-shield]: https://img.shields.io/badge/donate-paypal-blue.svg?style=flat-square&colorA=273133&colorB=b008bb "Paypal"
