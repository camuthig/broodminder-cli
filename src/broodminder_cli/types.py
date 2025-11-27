from dataclasses import dataclass


@dataclass
class BroodminderData:
    """Class for storing parsed Broodminder device data"""
    address: str
    name: str
    friendly_name: str
    rssi: int
    model_number: int
    model_name: str
    firmware_version: str
    temperature_f: float | None = None
    temperature_c: float | None = None
    humidity: float | None = None
    weight_left_lbs: float | None = None
    weight_right_lbs: float | None = None
    total_weight_lbs: float | None = None
    battery: int | None = None
    elapsed_time: int | None = None
    raw_data: bytes | None = None

