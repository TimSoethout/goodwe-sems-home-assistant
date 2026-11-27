"""Pure SEMS+ inverter control metadata resolution."""

import json
from typing import Any


def find_control_function(
    function_menus: dict[str, Any],
    function_name: str,
) -> dict[str, Any] | None:
    """Find a dedicated function or its shared status-setting fallback."""
    functions = function_menus.get("functions")
    if not isinstance(functions, list):
        return None
    dedicated = next(
        (
            item
            for item in functions
            if isinstance(item, dict) and item.get("translateKey") == function_name
        ),
        None,
    )
    if dedicated is not None:
        return dedicated
    return next(
        (
            item
            for item in functions
            if isinstance(item, dict) and item.get("translateKey") == "status_setting"
        ),
        None,
    )


def parse_control_attributes(
    function: dict[str, Any],
    function_name: str,
) -> tuple[str, str, int, str, str] | None:
    """Parse one discovered write command into address/value metadata."""
    address = function.get("address")
    function_id = function.get("id")
    control_attrs = function.get("controlAttr")
    if isinstance(control_attrs, str):
        try:
            control_attrs = json.loads(control_attrs)
        except json.JSONDecodeError:
            control_attrs = []
    if not isinstance(control_attrs, list):
        return None
    control_action = (
        "stop"
        if function.get("translateKey") == "status_setting"
        and function_name == "shutdown"
        else function_name
    )
    control_attr = next(
        (
            item
            for item in control_attrs
            if isinstance(item, dict) and item.get("transKey") == control_action
        ),
        None,
    )
    log_name = function.get("translateKey")
    log_action = (
        control_attr.get("transKey") if isinstance(control_attr, dict) else None
    )
    try:
        if (
            address is None
            or function_id is None
            or not str(address)
            or not str(function_id)
            or control_attr is None
            or not isinstance(log_name, str)
            or not isinstance(log_action, str)
        ):
            return None
        value = int(control_attr["value"])
    except KeyError, TypeError, ValueError:
        return None
    return str(address), str(function_id), value, log_name, log_action
