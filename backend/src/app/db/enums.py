from __future__ import annotations

from enum import Enum

import sqlalchemy as sa


def enum_values(enum_cls: type[Enum], **kwargs) -> sa.Enum:
    return sa.Enum(enum_cls, values_callable=lambda x: [e.value for e in x], **kwargs)
