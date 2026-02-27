from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast


def coerce_str_object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    mapping_value = cast(Mapping[object, object], value)
    out: dict[str, object] = {}
    for key_obj, mapped_value in mapping_value.items():
        if isinstance(key_obj, str):
            out[key_obj] = mapped_value
    return out


def coerce_object_list(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []
