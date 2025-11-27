"""
InfluxDB integration for Broodminder devices

This module provides functionality to send data from Broodminder devices
to an InfluxDB instance for storage and visualization.
"""

import os
from datetime import datetime
from datetime import timezone
from typing import Optional, List

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from broodminder_cli.types import BroodminderData


class InfluxDBConfig:
    """Configuration for InfluxDB connection"""

    def __init__(
        self, url: str = None, token: str = None, org: str = None, bucket: str = None, measurement: str = "broodminder"
    ):
        """
        Initialize InfluxDB configuration

        Args:
            url: InfluxDB server URL (default: from INFLUXDB_URL env var or http://localhost:8086)
            token: InfluxDB authentication token (default: from INFLUXDB_TOKEN env var)
            org: InfluxDB organization (default: from INFLUXDB_ORG env var or 'my-org')
            bucket: InfluxDB bucket (default: from INFLUXDB_BUCKET env var or 'broodminder')
            measurement: Measurement name for data points (default: 'broodminder')
        """
        self.url = url or os.environ.get("INFLUXDB_URL", "http://localhost:8086")
        self.token = token or os.environ.get("INFLUXDB_TOKEN")
        self.org = org or os.environ.get("INFLUXDB_ORG", "my-org")
        self.bucket = bucket or os.environ.get("INFLUXDB_BUCKET", "broodminder")
        self.measurement = measurement


class InfluxDBWriter:
    """Class for writing Broodminder data to InfluxDB"""

    def __init__(self, config: InfluxDBConfig = None):
        """
        Initialize InfluxDB writer

        Args:
            config: InfluxDB configuration (optional)
        """
        self.config = config or InfluxDBConfig()

        if not self.config.token:
            raise ValueError("InfluxDB token is required. Set INFLUXDB_TOKEN environment variable or provide token in config.")

        self.client = InfluxDBClient(url=self.config.url, token=self.config.token, org=self.config.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def broodminder_to_point(self, data: BroodminderData, timestamp: Optional[datetime] = None) -> Point:
        """
        Convert Broodminder data to InfluxDB data point

        Args:
            data: Broodminder device data
            timestamp: Optional timestamp (default: current time)

        Returns:
            InfluxDB data point
        """
        # Use provided timestamp or current time
        ts = timestamp or datetime.now(timezone.utc)

        # Create base point with device info as tags
        point = (
            Point(self.config.measurement)
            .tag("device_address", data.address)
            .tag("device_name", data.name or data.address)
            .tag("model_name", data.model_name)
            .tag("model_number", str(data.model_number))
            .tag("friendly_name", data.friendly_name or "")
            .time(ts)
        )

        # Add fields based on what data is available
        if data.temperature_c is not None:
            point = point.field("temperature_c", data.temperature_c)
            point = point.field("temperature_f", data.temperature_f)

        if data.humidity is not None:
            point = point.field("humidity", data.humidity)

        if data.total_weight_lbs is not None and data.total_weight_lbs > 0:
            point = point.field("total_weight_lbs", data.total_weight_lbs)

        if data.weight_left_lbs is not None and data.total_weight_lbs > 0:
            point = point.field("weight_left_lbs", data.weight_left_lbs)

        if data.weight_right_lbs is not None and data.total_weight_lbs > 0:
            point = point.field("weight_right_lbs", data.weight_right_lbs)

        if data.battery is not None:
            point = point.field("battery", data.battery)

        if data.rssi is not None:
            point = point.field("rssi", data.rssi)

        return point

    def write_data(self, data: BroodminderData, timestamp: Optional[datetime] = None) -> None:
        """
        Write Broodminder data to InfluxDB

        Args:
            data: Broodminder device data
            timestamp: Optional timestamp (default: current time)
        """
        point = self.broodminder_to_point(data, timestamp)
        self.write_api.write(bucket=self.config.bucket, record=point)

    def write_batch(self, data_list: List[BroodminderData], timestamp: Optional[datetime] = None) -> None:
        """
        Write multiple Broodminder data points to InfluxDB

        Args:
            data_list: List of Broodminder device data
            timestamp: Optional timestamp (default: current time)
        """
        points = [self.broodminder_to_point(data, timestamp) for data in data_list]
        self.write_api.write(bucket=self.config.bucket, record=points)

    def close(self) -> None:
        """Close InfluxDB client connection"""
        self.write_api.close()
        self.client.close()


def send_to_influxdb(data: BroodminderData, url: str = None, token: str = None, org: str = None, bucket: str = None) -> None:
    """
    Send Broodminder data to InfluxDB (convenience function)

    Args:
        data: Broodminder device data
        url: InfluxDB server URL
        token: InfluxDB authentication token
        org: InfluxDB organization
        bucket: InfluxDB bucket
    """
    config = InfluxDBConfig(url=url, token=token, org=org, bucket=bucket)
    writer = InfluxDBWriter(config)
    try:
        writer.write_data(data)
    finally:
        writer.close()


def send_batch_to_influxdb(
    data_list: List[BroodminderData], url: str = None, token: str = None, org: str = None, bucket: str = None
) -> None:
    """
    Send multiple Broodminder data points to InfluxDB (convenience function)

    Args:
        data_list: List of Broodminder device data
        url: InfluxDB server URL
        token: InfluxDB authentication token
        org: InfluxDB organization
        bucket: InfluxDB bucket
    """
    config = InfluxDBConfig(url=url, token=token, org=org, bucket=bucket)
    writer = InfluxDBWriter(config)
    try:
        writer.write_batch(data_list)
    finally:
        writer.close()
