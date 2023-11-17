from custom_components.sems.sensor import sensor_options_for_data
from data.test_data_001 import data_001
from data.test_data_002 import data_002


def get_value_from_path(data, path):
    """
    Get value from a nested dictionary.
    """
    value = data
    try:
        for key in path:
            value = value[key]
    except KeyError:
        return None
    return value


def len_of_all_list_items(list_of_str):
    return sum([len(str(item)) for item in list_of_str])


def print_sensor_options(data, sensor_options):
    max_length = max(
        [
            len_of_all_list_items(sensor_option.value_path)
            + (len(sensor_option.value_path) * 2)
            for sensor_option in sensor_options
        ]
    )
    for sensor_option in sensor_options:
        value = get_value_from_path(data, sensor_option.value_path)
        path = ""
        for key in sensor_option.value_path:
            path += str(key) + "->"
        path = path[:-2]
        path += ":"
        path += " " * (
            max_length
            - (
                len_of_all_list_items(sensor_option.value_path)
                + (len(sensor_option.value_path) * 2)
            )
        )
        print(f"{path} {value}")


def check_value_paths(data, sensor_options):
    for sensor_option in sensor_options:
        value = get_value_from_path(data, sensor_option.value_path)
        if value is None:
            print("Value not found for path: {}".format(sensor_option.value_path))


if __name__ == "__main__":
    for data_info in [("data_001", data_001), ("data_002", data_002)]:
        (name, data) = data_info
        print("\n")
        print(f"===== {name} =====")
        sensor_options = sensor_options_for_data(data)
        check_value_paths(data, sensor_options)
        print_sensor_options(data, sensor_options)
