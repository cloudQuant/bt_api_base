"""Neutral and explicitly selected historical order-identity aliases.

Field presence is not a source or authorization attestation.
"""
from types import MappingProxyType

NEUTRAL_ORDER_IDENTITY_FIELDS = MappingProxyType({'side': ('side', 'order_side', 'trade_side'), 'position_side': ('position_side',), 'position_bucket': ('position_bucket',), 'offset': ('offset', 'order_offset', 'trade_offset'), 'quantity_unit': ('quantity_unit',), 'position_mode': ('position_mode',)})

LEGACY_ORDER_IDENTITY_FIELDS = MappingProxyType({'side': ('side', 'order_side', 'trade_side', 'S'), 'position_side': ('position_side', 'posSide', 'positionSide', 'ps'), 'position_bucket': ('position_bucket',), 'offset': ('offset', 'order_offset', 'trade_offset'), 'quantity_unit': ('quantity_unit',), 'position_mode': ('position_mode', 'positionMode', 'posMode', 'dualSidePosition')})
