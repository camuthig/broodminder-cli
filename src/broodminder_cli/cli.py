#!/usr/bin/env python3
"""
Broodminder BLE Scanner CLI Application

A command-line tool to scan for and read data from Broodminder devices
using the Bluetooth Low Energy (BLE) advertising protocol.
"""

import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import logging
from pathlib import Path
import time
from typing import Any
from typing import List
from typing import Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from rich.console import Console
from rich.table import Table
import typer

from broodminder_cli.influx import InfluxDBConfig
from broodminder_cli.influx import send_batch_to_influxdb
from broodminder_cli.types import BroodminderData


# Define manufacturer ID for IF, LLC (Broodminder)
BROODMINDER_MANUFACTURER_ID = 0x028D  # 653 decimal

# Model number to name mapping
MODEL_NAMES = {
    41: "BroodMinder-T",
    42: "BroodMinder-TH",
    43: "BroodMinder-W",
    47: "BroodMinder-TMWC",
    49: "BroodMinder-XLR",
    52: "BroodMinder-SubHub",
    56: "BroodMinder-WS",
    57: "BroodMinder-WSLR",
    58: "BroodMinder-WSXLR",
}

# Scale factor for Broodminder scales
# This assumes a basic configuration with the front of the hive on a 2x4 and the back on the scales.
# Calculations can be taken from https://doc.mybroodminder.com/87_physics_and_tech_stuff/
# SCALE_FACTOR = 1.91
SCALE_FACTOR = 2.0

# Create Typer app and console
app = typer.Typer(help="Scan for Broodminder BLE devices")
console = Console()


class OutputFormat(str, Enum):
    """Output format options"""

    TEXT = "text"
    TABLE = "table"
    JSON = "json"
    CSV = "csv"


type DeviceAddress = str


@dataclass
class BroodminderDevice:
    address: DeviceAddress
    name: str | None
    friendly_name: str | None = None


# Define the path to store device information
def get_devices_file_path():
    # Create in user's home directory under .broodminder
    home_dir = Path.home()
    config_dir = home_dir / ".broodminder"
    config_dir.mkdir(exist_ok=True)
    return config_dir / "devices.json"


# Function to load existing devices
def load_saved_devices() -> dict[DeviceAddress, BroodminderDevice]:
    file_path = get_devices_file_path()
    if file_path.exists():
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
                return {addr: BroodminderDevice(**device) for addr, device in data.items()}
        except (json.JSONDecodeError, TypeError):
            # Handle corrupt file
            return {}
    return {}


# Function to save devices
def save_devices(saved_devices: dict[DeviceAddress, BroodminderDevice], found_devices: list[BroodminderData]) -> None:
    # Update the saved devices
    for device in found_devices:
        address = device.address
        if address not in saved_devices:
            saved_devices[address] = BroodminderDevice(address=address, name=None, friendly_name=None)

        # Update name only if it's not None
        if device.name is not None:
            saved_devices[address].name = device.name

    file_path = get_devices_file_path()
    # Convert dataclasses to plain dicts for JSON serialization
    devices_dict = {address: asdict(device) for address, device in saved_devices.items()}
    with open(file_path, "w") as f:
        json.dump(devices_dict, f, indent=2)


def parse_broodminder_data(
    device: BLEDevice, saved_device: BroodminderDevice | None, adv_data: AdvertisementData
) -> Optional[BroodminderData]:
    """
    Parse BLE advertisement data from Broodminder devices.

    Args:
        device: The BLE device
        saved_device: The saved Broodminder device
        adv_data: The advertisement data

    Returns:
        Parsed BroodminderData object or None if not a Broodminder device
    """
    # Check for manufacturer data
    if not adv_data.manufacturer_data:
        return None

    # Check for Broodminder manufacturer ID
    for manufacturer_id, data in adv_data.manufacturer_data.items():
        if manufacturer_id == BROODMINDER_MANUFACTURER_ID:
            return _process_broodminder_manufacturer_data(device, saved_device, adv_data, data)

    return None


def _process_broodminder_manufacturer_data(
    device: BLEDevice, saved_device: BroodminderDevice | None, adv_data: AdvertisementData, data: bytes
) -> Optional[BroodminderData]:
    """Process the manufacturer-specific data for Broodminder devices"""
    # Verify we have enough data (at least the model and version bytes)
    if len(data) < 3:
        return None

    model_number = data[0]
    version_minor = data[1]
    version_major = data[2]

    # Check if this is a valid Broodminder model
    model_name = MODEL_NAMES.get(model_number, f"Unknown-{model_number}")

    result = BroodminderData(
        address=device.address,
        name=adv_data.local_name or saved_device.name,
        friendly_name=saved_device.friendly_name,
        rssi=adv_data.rssi,
        model_number=model_number,
        model_name=model_name,
        firmware_version=f"{version_major}.{version_minor}",
        raw_data=data,
    )

    # Process the rest of the data based on the model number
    if len(data) >= 15:
        # Extract battery level (byte 4)
        result.battery = data[4] if len(data) > 4 else None

        # Extract elapsed time (bytes 5-6)
        if len(data) > 6:
            result.elapsed_time = data[5] + (data[6] << 8)

        # Parse temperature - depends on model
        if model_number in (41, 42, 43) and len(data) > 8:
            # Temperature calculation for older models
            temp_raw = data[7] + (data[8] << 8)
            result.temperature_f = (temp_raw / 65536 * 165 - 40) * 9 / 5 + 32
            result.temperature_c = temp_raw / 65536 * 165 - 40
        elif model_number >= 47 and len(data) > 8:
            # Temperature calculation for newer models
            temp_raw = data[7] + (data[8] << 8)
            if temp_raw > 5000:  # Temperature is in centigrade + 5000
                result.temperature_c = (temp_raw - 5000) / 100
                result.temperature_f = result.temperature_c * 9 / 5 + 32

        # Parse humidity (byte 14) - only for TH models
        if model_number in (42, 47) and len(data) > 14:
            result.humidity = data[14]

        # Parse weight for scale models
        if model_number in (43, 47, 49, 56, 57, 58) and len(data) > 13:
            # Weight left (bytes 10-11)
            if len(data) > 11:
                weight_left_raw = data[10] + (data[11] << 8)
                if weight_left_raw != 0x7FFF:  # 0x7FFF indicates no reading
                    result.weight_left_lbs = (weight_left_raw - 32767) / 100

            # Weight right (bytes 12-13)
            if len(data) > 13:
                weight_right_raw = data[12] + (data[13] << 8)
                if weight_right_raw != 0x7FFF:
                    result.weight_right_lbs = (weight_right_raw - 32767) / 100

            if result.weight_left_lbs is not None and result.weight_right_lbs is not None:
                result.total_weight_lbs = (result.weight_left_lbs + result.weight_right_lbs) / 2 * SCALE_FACTOR
            elif result.weight_left_lbs is not None:
                result.total_weight_lbs = result.weight_left_lbs * SCALE_FACTOR
            elif result.weight_right_lbs is not None:
                result.total_weight_lbs = result.weight_right_lbs * SCALE_FACTOR

        # Parse weight for scale models
        if model_number in (43, 47, 49, 56, 57, 58) and len(data) > 19:
            # Weight left (bytes 19-20)
            total_weight_raw = data[19] + (data[20] << 8)
            if total_weight_raw != 0x7FFF:  # 0x7FFF indicates no reading
                result.total_weight_lbs = (total_weight_raw - 32767) / 100 * SCALE_FACTOR

    return result


def format_broodminder_data(data: BroodminderData) -> str:
    """Format Broodminder data for display"""
    result = [
        f"Device: {data.model_name} ({data.address})",
        f"Name: {data.friendly_name} ({data.name})",
        f"RSSI: {data.rssi} dBm",
        f"Firmware: v{data.firmware_version}",
    ]

    if data.battery is not None:
        result.append(f"Battery: {data.battery}%")

    if data.elapsed_time is not None:
        result.append(f"Elapsed Time: {data.elapsed_time} minutes")

    if data.temperature_f is not None:
        result.append(f"Temperature: {data.temperature_c:.1f}°C / {data.temperature_f:.1f}°F")

    if data.humidity is not None:
        result.append(f"Humidity: {data.humidity}%")

    if data.total_weight_lbs is not None:
        result.append(f"Total Weight: {data.total_weight_lbs:.2f} lbs")
        if data.weight_left_lbs is not None and data.weight_right_lbs is not None:
            result.append(f"  Left: {data.weight_left_lbs:.2f} lbs")
            result.append(f"  Right: {data.weight_right_lbs:.2f} lbs")

    return "\n".join(result)


def create_rich_table(devices: List[BroodminderData]) -> Table:
    """Create a rich table for displaying device data"""
    table = Table(title="Broodminder Devices")

    # Add columns
    table.add_column("Address")
    table.add_column("Name")
    table.add_column("Model")
    table.add_column("RSSI (dBm)")
    table.add_column("Firmware")
    table.add_column("Battery")
    table.add_column("Temperature")
    table.add_column("Humidity")
    table.add_column("Weight (lbs)")

    # Add rows
    for device in devices:
        temp_str = f"{device.temperature_f:.1f}°F" if device.temperature_f is not None else "-"
        humidity_str = f"{device.humidity}%" if device.humidity is not None else "-"
        battery_str = f"{device.battery}%" if device.battery is not None else "-"
        weight_str = f"{device.total_weight_lbs:.2f}" if device.total_weight_lbs is not None else "-"

        table.add_row(
            device.address,
            device.friendly_name or device.name,
            device.model_name,
            str(device.rssi),
            f"v{device.firmware_version}",
            battery_str,
            temp_str,
            humidity_str,
            weight_str,
        )

    return table


async def scan_for_broodminder_devices(
    duration: float = 5.0, show_raw: bool = False, output_format: OutputFormat = OutputFormat.TEXT
) -> List[BroodminderData]:
    """
    Scan for Broodminder devices and return discovered device data.

    Args:
        duration: Duration in seconds to scan for devices
        show_raw: Whether to show raw data bytes
        output_format: Output format

    Returns:
        List of discovered Broodminder devices
    """
    devices_found = []

    # Load existing devices
    saved_devices = load_saved_devices()

    def callback(device: BLEDevice, adv_data: AdvertisementData):
        saved_device = saved_devices.get(device.address)
        if saved_device is None:
            saved_device = BroodminderDevice(address=device.address, name=adv_data.local_name)

        broodminder_data = parse_broodminder_data(device, saved_device, adv_data)

        if broodminder_data:
            # Check if we've already seen this device
            for existing in devices_found:
                if existing.address == broodminder_data.address:
                    # Update with latest data
                    devices_found.remove(existing)
                    break

            devices_found.append(broodminder_data)

            if output_format == OutputFormat.TEXT:
                console.print("\nFound Broodminder device:")
                console.print(format_broodminder_data(broodminder_data))
                if show_raw and broodminder_data.raw_data:
                    console.print(f"Raw data: {broodminder_data.raw_data.hex()}")

    scanner = BleakScanner(detection_callback=callback)

    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()

    # Save the updated devices
    save_devices(saved_devices, devices_found)

    return devices_found


def output_json(devices: List[BroodminderData]) -> None:
    """Output device data in JSON format"""
    import json

    data = []
    for device in devices:
        device_data: dict[str, Any] = {
            "address": device.address,
            "rssi": device.rssi,
            "model_number": device.model_number,
            "model_name": device.model_name,
            "firmware_version": device.firmware_version,
            "timestamp": datetime.now().isoformat(),
        }

        if device.battery is not None:
            device_data["battery"] = device.battery

        if device.elapsed_time is not None:
            device_data["elapsed_time"] = device.elapsed_time

        if device.temperature_c is not None:
            device_data["temperature_c"] = device.temperature_c
            device_data["temperature_f"] = device.temperature_f

        if device.humidity is not None:
            device_data["humidity"] = device.humidity

        if device.total_weight_lbs is not None:
            device_data["total_weight_lbs"] = device.total_weight_lbs

            if device.weight_left_lbs is not None:
                device_data["weight_left_lbs"] = device.weight_left_lbs

            if device.weight_right_lbs is not None:
                device_data["weight_right_lbs"] = device.weight_right_lbs

        data.append(device_data)

    console.print_json(json.dumps(data))


def output_csv(devices: List[BroodminderData]) -> None:
    """Output device data in CSV format"""
    import csv
    import io

    output = io.StringIO()
    fieldnames = [
        "address",
        "name",
        "rssi",
        "model_name",
        "firmware_version",
        "battery",
        "temperature_c",
        "temperature_f",
        "humidity",
        "total_weight_lbs",
        "weight_left_lbs",
        "weight_right_lbs",
        "timestamp",
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for device in devices:
        row = {
            "address": device.address,
            "name": device.name,
            "rssi": device.rssi,
            "model_name": device.model_name,
            "firmware_version": device.firmware_version,
            "battery": device.battery if device.battery is not None else "",
            "temperature_c": f"{device.temperature_c:.1f}" if device.temperature_c is not None else "",
            "temperature_f": f"{device.temperature_f:.1f}" if device.temperature_f is not None else "",
            "humidity": device.humidity if device.humidity is not None else "",
            "total_weight_lbs": f"{device.total_weight_lbs:.2f}" if device.total_weight_lbs is not None else "",
            "weight_left_lbs": f"{device.weight_left_lbs:.2f}" if device.weight_left_lbs is not None else "",
            "weight_right_lbs": f"{device.weight_right_lbs:.2f}" if device.weight_right_lbs is not None else "",
            "timestamp": datetime.now().isoformat(),
        }
        writer.writerow(row)

    console.print(output.getvalue())


@app.command()
def scan(
    duration: float = typer.Option(10.0, "--duration", "-d", help="Duration in seconds to scan for devices"),
    output_format: OutputFormat = typer.Option(OutputFormat.TABLE, "--format", "-f", help="Output format"),
    raw: bool = typer.Option(False, "--raw", "-r", help="Show raw data bytes"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    output_file: Optional[str] = typer.Option(None, "--output", "-o", help="Output file (default is stdout)"),
):
    """Scan for Broodminder BLE devices"""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    try:
        # Run the async scan function
        with console.status(f"Scanning for Broodminder devices for {duration} seconds..."):
            devices = asyncio.run(scan_for_broodminder_devices(duration=duration, show_raw=raw, output_format=output_format))

        # If no devices found
        if not devices:
            console.print("No Broodminder devices found.", style="yellow")
            return

        # Handle different output formats
        if output_format == OutputFormat.JSON:
            output_json(devices)
        elif output_format == OutputFormat.CSV:
            output_csv(devices)
        elif output_format == OutputFormat.TABLE:
            table = create_rich_table(devices)
            console.print(table)

            if raw:
                console.print("\nRaw Data:")
                for device in devices:
                    if device.raw_data:
                        console.print(f"{device.name}: {device.raw_data.hex()}")

        # Save to file if specified
        if output_file:
            with open(output_file, "w") as f:
                if output_format == OutputFormat.JSON:
                    import json

                    json.dump([device.__dict__ for device in devices], f, default=str, indent=2)
                elif output_format == OutputFormat.CSV:
                    import csv

                    fieldnames = [
                        "address",
                        "name",
                        "rssi",
                        "model_name",
                        "firmware_version",
                        "battery",
                        "temperature_c",
                        "temperature_f",
                        "humidity",
                        "total_weight_lbs",
                        "weight_left_lbs",
                        "weight_right_lbs",
                        "timestamp",
                    ]
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for device in devices:
                        writer.writerow(
                            {
                                "address": device.address,
                                "name": device.name,
                                "rssi": device.rssi,
                                "model_name": device.model_name,
                                "firmware_version": device.firmware_version,
                                "battery": device.battery if device.battery is not None else "",
                                "temperature_c": f"{device.temperature_c:.1f}" if device.temperature_c is not None else "",
                                "temperature_f": f"{device.temperature_f:.1f}" if device.temperature_f is not None else "",
                                "humidity": device.humidity if device.humidity is not None else "",
                                "total_weight_lbs": f"{device.total_weight_lbs:.2f}"
                                if device.total_weight_lbs is not None
                                else "",
                                "weight_left_lbs": f"{device.weight_left_lbs:.2f}"
                                if device.weight_left_lbs is not None
                                else "",
                                "weight_right_lbs": f"{device.weight_right_lbs:.2f}"
                                if device.weight_right_lbs is not None
                                else "",
                                "timestamp": datetime.now().isoformat(),
                            }
                        )
                else:
                    with console.capture() as capture:
                        if output_format == OutputFormat.TABLE:
                            console.print(create_rich_table(devices))
                        else:
                            for device in devices:
                                console.print(format_broodminder_data(device))
                                console.print("")
                    f.write(capture.get())

                console.print(f"Results saved to {output_file}", style="green")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        if verbose:
            import traceback

            console.print(traceback.format_exc())
        raise typer.Exit(code=1)


@app.command()
def monitor(
    duration: float = typer.Option(-1, "--duration", "-d", help="Duration in seconds to monitor devices (-1 for continuous)"),
    interval: float = typer.Option(1.0, "--interval", "-i", help="Update interval in seconds"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
):
    """
    Continuously monitor Broodminder devices

    This will continuously scan and update the display with found devices.
    Press Ctrl+C to stop monitoring.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    try:
        # Use a dictionary to store devices by address
        devices = {}
        start_time = datetime.now()

        console.print("Starting Broodminder monitor. Press Ctrl+C to stop.", style="bold green")

        # Create a single status that we'll reuse
        with console.status("Monitoring devices...") as status:
            # Main monitoring loop
            while True:
                # Check if we've exceeded the duration
                if duration > 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= duration:
                        break

                # Update status message
                status.update("Scanning for devices...")

                # Scan for devices
                found_devices = asyncio.run(
                    scan_for_broodminder_devices(duration=interval, show_raw=False, output_format=OutputFormat.TEXT)
                )

                # Update our device dictionary
                for device in found_devices:
                    devices[device.address] = device

                # Clear the screen and display the current devices
                console.clear()
                console.print(f"Broodminder Monitor - Last update: {datetime.now()}", style="bold blue")
                console.print(f"Found {len(devices)} devices", style="green")

                if devices:
                    table = create_rich_table(list(devices.values()))
                    console.print(table)

                # Update status message
                status.update("Waiting for next scan...")

                # Sleep for a short time
                sleep(5)

    except KeyboardInterrupt:
        console.print("\nMonitoring stopped by user.", style="yellow")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        if verbose:
            import traceback

            console.print(traceback.format_exc())
        raise typer.Exit(code=1)


@app.command()
def influx_push(
    duration: float = typer.Option(-1, "--duration", "-d", help="Duration in seconds to monitor devices (-1 for continuous)"),
    interval: float = typer.Option(1.0, "--interval", "-i", help="Update interval in seconds"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    url: str = typer.Option(
        None, "--url", help="InfluxDB server URL (defaults to INFLUXDB_URL env var or http://localhost:8086)"
    ),
    token: str = typer.Option(None, "--token", help="InfluxDB authentication token (defaults to INFLUXDB_TOKEN env var)"),
    org: str = typer.Option(None, "--org", help="InfluxDB organization (defaults to INFLUXDB_ORG env var or 'my-org')"),
    bucket: str = typer.Option(None, "--bucket", help="InfluxDB bucket (defaults to INFLUXDB_BUCKET env var or 'broodminder')"),
    display: bool = typer.Option(True, "--display/--no-display", help="Display device data in the console"),
):
    """
    Continuously monitor Broodminder devices and push data to InfluxDB

    This will scan for devices at the specified interval and push the data
    to an InfluxDB server. Press Ctrl+C to stop.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    try:
        # Get InfluxDB configuration for display
        config = InfluxDBConfig(url=url, token=token, org=org, bucket=bucket)
        console.print(f"Starting Broodminder InfluxDB push to {config.bucket} at {config.url}", style="bold green")
        console.print("Press Ctrl+C to stop.", style="bold green")

        # Use a dictionary to store devices by address
        devices = {}
        start_time = datetime.now()

        # Create a single status that we'll reuse
        with console.status("Monitoring devices...") as status:
            # Main monitoring loop
            while True:
                # Check if we've exceeded the duration
                if duration > 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed >= duration:
                        break

                # Update status message
                status.update("Scanning for devices...")

                # Scan for devices
                found_devices = asyncio.run(
                    scan_for_broodminder_devices(duration=interval, show_raw=False, output_format=OutputFormat.TEXT)
                )

                # Update our device dictionary
                for device in found_devices:
                    devices[device.address] = device

                # Push data to InfluxDB
                if devices:
                    device_list = list(devices.values())
                    try:
                        send_batch_to_influxdb(data_list=device_list, url=url, token=token, org=org, bucket=bucket)
                        status.update(f"Pushed data for {len(device_list)} devices to InfluxDB")
                    except Exception as e:
                        console.print(f"[bold red]Error writing to InfluxDB:[/bold red] {e}")

                # Display the current devices if requested
                if display:
                    console.clear()
                    console.print(f"Broodminder InfluxDB Push - Last update: {datetime.now()}", style="bold blue")
                    console.print(f"Found {len(devices)} devices", style="green")

                    if devices:
                        table = create_rich_table(list(devices.values()))
                        console.print(table)

                # Update status message
                status.update(f"Waiting {interval} seconds for next scan...")

                # Sleep for the interval
                time.sleep(interval)

    except KeyboardInterrupt:
        console.print("\nInfluxDB push stopped by user.", style="yellow")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        if verbose:
            import traceback

            console.print(traceback.format_exc())
        raise typer.Exit(code=1)


def main():
    app()
