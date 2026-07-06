from __future__ import annotations

import pytest

from mozilcode.teams.fields import (
    non_negative_number_field,
    object_field,
    optional_bool_field,
    string_field,
    string_list_field,
)


def test_string_field_validates_required_and_type() -> None:
    assert string_field({"name": "team"}, "name", prefix="team") == "team"

    with pytest.raises(ValueError, match="team.name is required"):
        string_field({}, "name", prefix="team")

    with pytest.raises(ValueError, match="team.name must be a string"):
        string_field({"name": []}, "name", prefix="team")


def test_string_list_field_validates_items() -> None:
    assert string_list_field({"blocks": ["1"]}, "blocks", prefix="task") == ["1"]

    with pytest.raises(ValueError, match="task.blocks must be a list of strings"):
        string_list_field({"blocks": [1]}, "blocks", prefix="task")


def test_object_field_validates_shape() -> None:
    assert object_field({"metadata": {"x": 1}}, "metadata", prefix="message") == {
        "x": 1
    }

    with pytest.raises(ValueError, match="message.metadata must be an object"):
        object_field({"metadata": []}, "metadata", prefix="message")


def test_non_negative_number_field_rejects_bool_and_negative() -> None:
    assert non_negative_number_field({"timestamp": 1}, "timestamp", prefix="message") == 1.0

    with pytest.raises(ValueError, match="message.timestamp must be"):
        non_negative_number_field({"timestamp": True}, "timestamp", prefix="message")

    with pytest.raises(ValueError, match="message.timestamp must be"):
        non_negative_number_field({"timestamp": -1}, "timestamp", prefix="message")


def test_optional_bool_field_accepts_null_and_bool() -> None:
    assert optional_bool_field({"is_active": None}, "is_active", prefix="teammate") is None
    assert optional_bool_field({"is_active": False}, "is_active", prefix="teammate") is False

    with pytest.raises(ValueError, match="teammate.is_active must be a boolean or null"):
        optional_bool_field({"is_active": "yes"}, "is_active", prefix="teammate")
