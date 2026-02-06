# N9 Spectral Sensing Expansion (Topsoe)
Firmware, software and PCB files for N9 expansion with spectral colour sensing of well plates.

## Install Dependencies from PyProject

Build venv in root directory:

```
python -m venv .venv
```

Upgrade pip:

```
.venv/bin/pip install --upgrade pip
```

Install dependencies into new venv:

```
.venv/bin/pip install -e .
```

Activate venv:

```
source .venv/bin/activate
```

Note: Replace *bin* with *Scripts* if using windows.

## Other Requirements

- Platformio vscode extension to flash firmware to PCBs
- RS485 converter for MFC

## Flashing Firmware to PCBs (Platformio)

Install the [PlatformIO VSCode Extension](https://docs.platformio.org/en/latest/integration/ide/vscode.html) and open a new Pio terminal (found in *Quick Access/Miscellaneous*). Connect the the target PCB via USB and run the following commands:

```
cd firmware/loadcell_board
```

```
pio run -t upload
```

## Hardware References

See [BOM](part_files/BOM.pdf) for complete list.

1. [AS7341 Spectral Sensors](https://ams-osram.com/products/sensor-solutions/ambient-light-color-spectral-proximity-sensors/ams-as7341-11-channel-spectral-color-sensor)
