from dataclasses import replace

import pytest

from event_logic import FIXED_SENSOR_MAPPING, validate_sensor_mapping


def test_fixed_mapping_passes():
    validate_sensor_mapping()


def test_duplicate_gpio_fails():
    mapping = list(FIXED_SENSOR_MAPPING)
    mapping[1] = replace(mapping[1], gpio_pin=17)
    with pytest.raises(ValueError, match="GPIO"):
        validate_sensor_mapping(mapping)


def test_wrong_gpio_fails():
    mapping = list(FIXED_SENSOR_MAPPING)
    mapping[0] = replace(mapping[0], gpio_pin=18)
    with pytest.raises(ValueError, match="GPIO17"):
        validate_sensor_mapping(mapping)


def test_duplicate_sensor_id_fails():
    mapping = list(FIXED_SENSOR_MAPPING)
    mapping[1] = replace(mapping[1], sensor_id="S1")
    with pytest.raises(ValueError, match="unique"):
        validate_sensor_mapping(mapping)


def test_incompatible_role_fails():
    mapping = list(FIXED_SENSOR_MAPPING)
    mapping[0] = replace(mapping[0], kind="state")
    with pytest.raises(ValueError, match="semantics"):
        validate_sensor_mapping(mapping)
