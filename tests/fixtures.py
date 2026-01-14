"""Test fixtures with anonymized SEMS API response data.

This file contains test fixtures based on real SEMS API responses, but with all
personally identifiable information anonymized to protect user privacy:

ANONYMIZED DATA:
- Power Station ID: xxx → 12345678-1234-5678-9abc-123456789abc
- Inverter Serial: xxx → GW0000SN000TEST1
- Inverter Model: xxx → GW0000-TEST
- Station Name: xxx → Test Solar Farm
- Location: xxx → Test City, Test Country
- Email Addresses: xxx → test@example.com
- Coordinates: longitude xxx, latitude xxx → 0.0, 0.0
- Relation IDs: xxx → aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee

UNCHANGED DATA:
- API response structure (preserved for testing accuracy)
- Chinese success message: 操作成功 (not personally identifiable)
- Numerical values and timestamps (randomized or anonymized)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json_fixture(relative_path: str) -> dict[str, Any]:
    fixture_path = Path(__file__).resolve().parent.parent / relative_path
    return json.loads(fixture_path.read_text(encoding="utf-8"))


# Anonymized login response based on SEMS API structure
MOCK_LOGIN_RESPONSE = {
    "language": "en",
    "function": [
        "ADD",
        "VIEW",
        "EDIT",
        "DELETE",
        "INVERTER_A",
        "INVERTER_E",
        "INVERTER_D",
    ],
    "hasError": False,
    "msg": "操作成功",
    "code": "0",
    "data": {
        "uid": "test-uid-123",
        "timestamp": 1757355815062,
        "token": "test-token-abc123",
        "client": "ios",
        "version": "",
        "language": "en",
    },
    "api": "https://eu.semsportal.com/api/",
}

# Real power station IDs response
MOCK_POWER_STATION_IDS_RESPONSE = {
    "code": 0,
    "data": "12345678-1234-5678-9abc-123456789abc",
    "msg": "操作成功",
}

# Real getData response (simplified from the full JSON)
MOCK_GET_DATA_RESPONSE = {
    "language": "en",
    "function": [
        "ADD",
        "VIEW",
        "EDIT",
        "DELETE",
        "INVERTER_A",
        "INVERTER_E",
        "INVERTER_D",
    ],
    "hasError": False,
    "msg": "操作成功",
    "code": "0",
    "data": {
        "info": {
            "powerstation_id": "12345678-1234-5678-9abc-123456789abc",
            "time": "09/08/2025 16:48:27",
            "date_format": "dd/MM/yyyy",
            "date_format_ym": "MM/yyyy",
            "stationname": "Test Solar Farm",
            "address": "Test City, Test Country",
            "owner_name": "test@example.com",
            "owner_phone": None,
            "owner_email": "test@example.com",
            "battery_capacity": 0.0,
            "turnon_time": "12/21/2018 00:00:00",
            "create_time": "12/21/2018 15:18:15",
            "capacity": 3.2,
            "longitude": 0.0,
            "latitude": 0.0,
            "powerstation_type": "Residential",
            "status": 1,
            "is_stored": False,
            "is_powerflow": False,
            "charts_type": 4,
            "has_pv": True,
            "has_statistics_charts": False,
            "only_bps": False,
            "only_bpu": False,
            "time_span": -2.0,
            "pr_value": "",
            "org_code": "GW000000",
            "org_name": "Goodwe",
        },
        "kpi": {
            "month_generation": 85.7,
            "pac": 589.0,
            "power": 8.9,
            "total_power": 18843.2,
            "day_income": 1.96,
            "total_income": 4145.5,
            "yield_rate": 0.22,
            "currency": "EUR",
        },
        "powercontrol_status": 0,
        "images": [],
        "weather": {
            "HeWeather6": [
                {
                    "basic": {
                        "cid": None,
                        "location": None,
                        "parent_city": None,
                        "admin_area": None,
                        "cnty": None,
                        "lat": None,
                        "lon": None,
                        "tz": None,
                    },
                    "update": {"loc": None, "utc": None},
                    "status": "ok",
                    "daily_forecast": [
                        {
                            "cond_code_d": "103",
                            "cond_code_n": "153",
                            "cond_txt_d": "Partly Cloudy",
                            "cond_txt_n": "Partly Cloudy",
                            "date": "2025-09-08",
                            "hum": "74",
                            "pcpn": "0.0",
                            "pop": "11",
                            "pres": "1017",
                            "tmp_max": "24",
                            "tmp_min": "12",
                            "uv_index": "4",
                            "vis": "9",
                            "wind_deg": "276",
                            "wind_dir": "W",
                            "wind_sc": "1-3",
                            "wind_spd": "9",
                        }
                    ],
                }
            ]
        },
        "inverter": [
            {
                "sn": "GW0000SN000TEST1",
                "dict": {
                    "left": [
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "dmDeviceType",
                            "value": "GW0000-TEST",
                            "unit": "",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "serialNum",
                            "value": "GW0000SN000TEST1",
                            "unit": "",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "capacity",
                            "value": "3",
                            "unit": "kW",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "InverterPowerOfPlantMonitor",
                            "value": "0.583",
                            "unit": "kW",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "acVacVol",
                            "value": "234.0",
                            "unit": "V",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "acCurrent",
                            "value": "2.5",
                            "unit": "A",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "acFrequency",
                            "value": "50.00",
                            "unit": "Hz",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                    ],
                    "right": [
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "innerTemp",
                            "value": "32.0",
                            "unit": "℃",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                        {
                            "isHT": False,
                            "isStoreSkip": False,
                            "key": "dcVandC1",
                            "value": "306.1/1.9",
                            "unit": "V/A",
                            "isFaultMsg": 0,
                            "faultMsgCode": 0,
                        },
                    ],
                },
                "is_stored": False,
                "name": "Zolder",
                "in_pac": 1.8,
                "out_pac": 589.0,
                "eday": 8.9,
                "emonth": 76.8,
                "etotal": 18843.2,
                "status": 1,
                "turnon_time": "12/21/2018 15:19:52",
                "releation_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "type": "GW0000-TEST",
                "capacity": 3.0,
                "tempperature": 32.0,
                "check_code": "053241",
            }
        ],
        "hjgx": {"co2": 15.074560000000002, "tree": 1029.78088, "coal": 7.6126528},
        "homKit": {"homeKitLimit": False, "sn": None},
        "isTigo": False,
        "tigoIntervalTimeMinute": 15,
        "smuggleInfo": {
            "isAllSmuggle": False,
            "isSmuggle": False,
            "descriptionText": None,
            "sns": None,
        },
        "hasPowerflow": False,
        "hasGenset": False,
        "hasMicroGrid": False,
        "powerflow": None,
        "hasGridLoad": False,
        "isShowBattery": False,
        "hasMicroInverter": False,
        "hasLayout": False,
        "layout_id": "",
        "isParallelInventers": False,
        "isEvCharge": False,
        "evCharge": None,
        "is3rdEms": False,
        "hasEnergeStatisticsCharts": False,
        "energeStatisticsCharts": {
            "contributingRate": 1.0,
            "selfUseRate": 1.0,
            "sum": 8.9,
            "buy": 0.0,
            "buyPercent": 0.0,
            "sell": 0.0,
            "sellPercent": 0.0,
            "selfUseOfPv": 8.9,
            "consumptionOfLoad": 8.9,
            "chartsType": 4,
            "hasPv": True,
            "hasCharge": False,
            "charge": 0.0,
            "disCharge": 0.0,
            "gensetGen": 0.0,
            "hasGenset": False,
            "isStored": False,
            "hasMicroGrid": False,
            "microGridGen": 0.0,
        },
        "soc": {"power": 0, "status": 0},
        "environmental": [],
        "equipment": [
            {
                "type": "5",
                "title": "Zolder",
                "status": 1,
                "model": None,
                "statusText": None,
                "capacity": None,
                "actionThreshold": None,
                "subordinateEquipment": "",
                "powerGeneration": "Power: 0.589kW",
                "eday": "Generation Today: 8.9kWh",
                "brand": "",
                "isStored": False,
                "soc": "SOC: 536%",
                "isChange": False,
                "relationId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "sn": "GW0000SN000TEST1",
                "has_tigo": False,
                "is_sec": False,
                "is_secs": False,
                "targetPF": None,
                "exportPowerlimit": None,
                "batterySN": None,
                "batterySN1": None,
                "batteryModule": None,
                "moreBatterySign": None,
                "batteryModuleNum": None,
                "batteryModuleAdded": None,
                "mark": False,
                "master": -1,
                "changerVer": 0,
            }
        ],
        "isSec1000EtPlant": False,
    },
}

# Coordinator-compatible getData() result (this corresponds to SemsApi.getData() return value)
#
# The Home Assistant integration coordinator expects:
# - `result["inverter"]`: list of items each containing `{"invert_full": {...}}`
# - `result["kpi"]`: dict with optional `currency`
# - `result["hasPowerflow"]` and `result["hasEnergeStatisticsCharts"]`
MOCK_GET_DATA_RESULT_MINIMAL = {
    "inverter": [
        {
            "invert_full": {
                "name": "Test Inverter",
                "sn": "GW0000SN000TEST1",
                "powerstation_id": "12345678-1234-5678-9abc-123456789abc",
                "status": 1,
                "capacity": 3.0,
                "pac": 589,
                "etotal": 18843.2,
                "hour_total": 1234,
                "tempperature": 32.0,
                "eday": 8.9,
                "thismonthetotle": 85.7,
                "lastmonthetotle": 76.8,
                "iday": 1.96,
                "itotal": 4145.5,
            }
        }
    ],
    "kpi": {
        "currency": "EUR",
        "total_power": 18843.2,
    },
    "hasPowerflow": False,
    "hasEnergeStatisticsCharts": False,
}

# Coordinator-compatible getData() result that includes HomeKit/powerflow data.
#
# The coordinator will detect `hasPowerflow=True` and expose a pseudo-inverter
# under `data.inverters["homeKit"]`.
MOCK_HOMEKIT_GET_DATA = {
    "inverter": [
        {
            "invert_full": {
                "name": "Test Inverter",
                "sn": "GW0000SN000TEST1",
                "powerstation_id": "12345678-1234-5678-9abc-123456789abc",
                "status": 1,
                "capacity": 3.0,
                "pac": 589,
                "etotal": 18843.2,
                "hour_total": 1234,
                "tempperature": 32.0,
                "eday": 8.9,
                "thismonthetotle": 85.7,
                "lastmonthetotle": 76.8,
                "iday": 1.96,
                "itotal": 4145.5,
            }
        }
    ],
    "kpi": {
        "currency": "EUR",
        "total_power": 18843.2,
    },
    "homKit": {
        "homeKitLimit": False,
        "sn": None,
    },
    "hasPowerflow": True,
    "hasEnergeStatisticsCharts": False,
    "powerflow": {
        "pv": "0(W)",
        "pvStatus": 0,
        "load": "100(W)",
        "loadStatus": 1,
        "grid": "100(W)",
        "gridStatus": -1,
        "bettery": "0(W)",
        "betteryStatus": 0,
        "genset": "0(W)",
        "soc": 0,
    },
}

MOCK_GET_DATA_ACTUAL_JSON: dict[str, Any] = _load_json_fixture(
    "tests/test-data/20260110_singleInverter_getData.json"
)

# Anonymized inverter serial number for testing
MOCK_INVERTER_SN = "GW0000SN000TEST1"

# Anonymized power station ID for testing
MOCK_POWER_STATION_ID = "12345678-1234-5678-9abc-123456789abc"

# Success message in Chinese as returned by SEMS API (unchanged as it's not personal data)
SUCCESS_MESSAGE = "操作成功"
