"""Protocol factory for detecting and managing BLE firmware protocols."""
from .protocol_base import BLEProtocol
from .protocol_atc import ATCProtocol
from .protocol_oepl import OEPLProtocol
from .exceptions import UnsupportedProtocolError


# Singleton protocol instances
_PROTOCOLS: dict[int, BLEProtocol] = {
    0x1337: ATCProtocol(),  # ATC firmware (4919 decimal)
    0x2446: OEPLProtocol(),  # OEPL firmware (9286 decimal)
}


def get_protocol_by_manufacturer_id(mfg_id: int) -> BLEProtocol:
    """Get protocol instance by Bluetooth manufacturer ID.

    Args:
        mfg_id: Manufacturer ID from BLE advertisement

    Returns:
        BLEProtocol: Protocol instance for the given manufacturer ID

    Raises:
        UnsupportedProtocolError: If manufacturer ID is not supported
    """
    protocol = _PROTOCOLS.get(mfg_id)
    if not protocol:
        supported_ids = [f"{mid:#06x} ({mid})" for mid in _PROTOCOLS.keys()]
        raise UnsupportedProtocolError(
            f"Unknown manufacturer ID: {mfg_id:#06x} ({mfg_id}). "
            f"Supported IDs: {', '.join(supported_ids)}"
        )
    return protocol


def get_protocol_by_name(name: str) -> BLEProtocol:
    """Get protocol instance by protocol name.

    Args:
        name: Protocol name ('atc' or 'oepl')

    Returns:
        BLEProtocol: Protocol instance for the given name

    Raises:
        UnsupportedProtocolError: If protocol name is not recognized
    """
    for protocol in _PROTOCOLS.values():
        if protocol.protocol_name == name:
            return protocol

    supported_names = [p.protocol_name for p in _PROTOCOLS.values()]
    raise UnsupportedProtocolError(
        f"Unknown protocol: '{name}'. Supported protocols: {', '.join(supported_names)}"
    )


def get_supported_manufacturer_ids() -> list[int]:
    """Get list of supported manufacturer IDs for discovery.

    Returns:
        list[int]: List of manufacturer IDs that can be auto-discovered
    """
    return list(_PROTOCOLS.keys())
