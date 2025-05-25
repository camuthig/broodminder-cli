BLE Advertising Information

Note: If you have suggestions for improving the explanation, then us the details.

For those brave souls with the gumption to create their own data harvesting equipment, we provide information on the BLE advertising protocol that BroodMinder uses. Indeed our own BroodMinder-CELL, WiFi, and -SubHub uses the advertising to eavesdrop on the devices and then forward the data directly to MyBroodMinder.com.

There are several nice BLE Explorer programs available. Our favorites are:

    Android & iOS – nrfConnect by Nordic Semiconductor. The Android version is best, but we use both all of the time. It has a nice signal level graphing feature.
    PC – Bluetooth LE Explorer by Microsoft. Unfortunately, this program doesn’t show the advertising data.
    Mac – BlueSee – This app seems to work nicely and it does show the manufacturers data in the advertising packet.

You will likely notice that the first 3 bytes of the device ID are always 06:09:16 then follows the particular device ID which is always Model:ID:ID. Some devices (iOS & Mac) hide the true ID, so we also include that in the name field in the extended advertising packet.

Advertising Packet Makeup for BroodMinder

When you read advertising packets from BLE, you can identify BroodMinder products by looking at the following.

The data will look something like this. – this example is from device 43:30:07

GAP Scan Response Event ------------------------------------------------------------------------------------

ble_evt_gap_scan_response: rssi=-77, packet_type=0, sender=[ 07 30 43 80 07 00 ], address_type=0, bond=255, data=[ 02 01 06 02 0a 03 18 ff 8d 02 2b 15 02 00 02 21 00 d0 62 00 ff 7f 05 80 37 07 30 43 00 00 00 ]

Note: Values are in decimal unless preceded with 0x

1) Check for "Manufacturer Specific Data" flag Bytes 6,7 = 0x18, 0xff

2) Check for IF, LLC as the manufacturer Bytes 8,9 = 0x8d, 0x02

Bytes 10-29 are the data from the BroodMinder as outlined below.
DeviceModelIFllc_1 = 0x2b (43d = scale)
DeviceVersionMinor_1 = 0x15 (21d) DeviceVersionMajor_1 = 0x02 (FW 2.21) Elapsed_2V2 = 0x21 (33d) Temperature_2V2 = 0x62d0 WeightL_2V2 = 0x7FFF WeightR_2V2 = 0x8005

The mapping for all models is on the next page
PRIMARY 				
Byte 	Type 	Value 	Parameter 	
0 	Ad field Length 	02 		
1 	Field Type 	01 	Connectible 	
2 	Value 	06 	LE General Discovery, Connectible, Single Mode Device 	
3 	Ad field Length 	02 		
4 	Field Type 	0A 	Xmit Power 	
5 	Value 	03 	Power in DB 	
6 	Ad field Length 	24 		
7 	Field Type 	FF 	Manufacturer data 	
8 	Value 	8d 	IF, LLC = 0x028d, 653 	
9 	Value 	02 	IF, LLC = 0x028d, 653 	
10 	Value 		Model 	
11 	Value 		Version Minor 	
12 	Value 		Version Major 	
13 	Value 		Realtime Temp1 	47/49/56/57/58 (SM&XLR)
14 	Value 		Battery 	
15 	Value 		Elapsed 	
16 	Value 		Elapsed 	
17 	Value 		Temperature 	47& above is centicenigrade + 5000
18 	Value 		Temperature 	
19 	Value 		Realtime Temp2 	47/49/56/57/58 (SM&XLR)
20 	Value 		WeightL 	
21 	Value 		WeightL 	
22 	Value 		WeightR 	
23 	Value 		WeightR 	
24 	Value 		Humidity 	will be 0 for 41/47/49/52
25 	Value 		WeightL2/SM_Time0 	49/57/58 (XLR)
26 	Value 		WeightL2/SM_Time1 	49/57/58 (XLR)
27 	Value 		WeightR2/SM_Time2 	49/57/58 (XLR)
28 	Value 		WeightR2/SM_Time3 	49/57/58 (XLR)
29 	Value 		Realtime total weight / Swarm State 	47/49/56/57/58 (SM&XLR)
30 	Value 		Realtime total weight 	47/49/56/57/58 (SM&XLR)
				
SECONDARY 			Extended Advertising Packet 	
Byte 	Type 	Value 	Parameter 	
0 	Ad field Length 	09 		
1 	Type 	09 	Complete Local Name 	
2 		4' 	ascii name 	
3 		2' 		
4 		:' 		
5 		0' 		
6 		0' 		
7 		:' 		
8 		0' 		
9 		0' 		

Note: BRM52 BroodMinder-SubHub is different as explained below.

Here are the equations

if (ModelNumber == 41 | ModelNumber == 42 | ModelNumber == 43)
{
    temperatureDegreesF = e.data[byteNumAdvTemperature_2V2] +       (e.data[byteNumAdvTemperature_2V2 + 1] << 8);
    temperatureDegreesF = (temperatureDegreesF / Math.Pow(2, 16) * 165 - 40) * 9 / 5 + 32;
}
else
{
    double temperatureDegreesC = e.data[byteNumAdvTemperature_2V2] + (e.data[byteNumAdvTemperature_2V2 + 1] << 8);
    temperatureDegreesC = (temperatureDegreesC - 5000) / 100;
    temperatureDegreesF = temperatureDegreesC * 9 / 5 + 32;
}
    humidityPercent = e.data[byteNumAdvHumidity_1V2];
if (ModelNumber == 43)
{
    weightL = e.data[byteNumAdvWeightL_2V2 + 1] * 256 + e.data[byteNumAdvWeightL_2V2 + 0] - 32767;
    weightScaledL = weightL / 100;
    weightR = e.data[byteNumAdvWeightR_2V2 + 1] * 256 + e.data[byteNumAdvWeightR_2V2 + 0] - 32767;
    weightScaledR = weightR / 100;
} 
else if (ModelNumber == 49 | ModelNumber == 57 | ModelNumber == 58)
{
    weightR = e.data[byteNumAdvWeightL_2V2 + 1] * 256 + e.data[byteNumAdvWeightL_2V2 + 0] - 32767;
    weightScaledR = weightR / 100;
    weightL = e.data[byteNumAdvWeightR_2V2 + 1] * 256 + e.data[byteNumAdvWeightR_2V2 + 0] - 32767;
    weightScaledL = weightL / 100;
    weightR2 = e.data[byteNumAdvWeightL2_2V2 + 1] * 256 + e.data[byteNumAdvWeightL2_2V2 + 0] - 32767;
    weightScaledR2 = weightR2 / 100;
    weightL2 = e.data[byteNumAdvWeightR2_2V2 + 1] * 256 + e.data[byteNumAdvWeightR2_2V2 + 0] - 32767;
    weightScaledL2 = weightL2 / 100;
}
realTimeTemperature = ((float)(e.data[byteNumAdvRealTimeTemperature2] * 256 + e.data[byteNumAdvRealTimeTemperature1] - 5000) / 100) * 9 / 5 + 32;

realTimeWeight = (float)(e.data[byteNumAdvRealTimeWeight2] * 256 + e.data[byteNumAdvRealTimeWeight1] - 32767 ) / 100 ;

SM_Time is the unix time of last temperature event. Time0 = LSB, Time3 = MSB, it will be time since boot if time has not been set in the device by a device sync.

BRM-52 BroodMinder-SubHub

The -SubHub does some tricky advertising. The advertising changes every 5 seconds to send out a different device. It will roll through all devices (including itself) and then repeat.

We call these Mock Advertisements. Depending on what operating system is being used, you may or may not (e.g. iOS) be able to see the true device ID (e.g. 06:09:16:52:01:23). That is why we place the device ID in the extended advertising byte. Also note that it is difficult to read the extended advertising for some devices, however for those, you typically can read the true device ID.

The Mock ID resides in byte 13, 19, and 30. That makes the process as follows:

    Establish if this is a -SubHub by the ID (either the true ID or the ID in the extended advertising). It will always be 52:xx:xx.
    If it is a “52” device, then parse bytes 13/19/30. E.g. 43/01/23 will be 43:01:23
    Parse the rest of the advertising packet according to the device type based on the model byte (byte 10)

Easy Peasy 😉 