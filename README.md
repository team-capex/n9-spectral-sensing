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

## Introduction to AS3741 Spectral Sensor #####

| Channel | Approx. Wavelength |
|------|------|
| F1 - Violet | ~405 nm |
| F2 - Indigo | ~425 nm |
| F3 - Blue | ~450 nm |
| F4 - Cyan | ~475 nm |
| F5 - Green | ~515 nm |
| F6 - Yellow | ~555 nm |
| F7 - Orange | ~590 nm |
| F8 - Red | ~630–680 nm |
| CLR | All visible |
| NIR | ~850–900 nm |

### Raw photodiode counts (ADC output after integration).
They are not color-corrected or normalized and are extremely sensitive to:
- Illumination spectrum
- LED aging
- Distance / angle
- Surface texture

### CLR = broadband photodiode with no color filter
It sees almost the entire visible spectrum (and a bit beyond).
Think of it as: “Total visible light intensity” or a reference / normalization channel

Why it exists: 
- Normalize spectral channels: Fn / CLR
- Detect illumination changes.
- Improve stability across time.
- If your light source dims by 10%, all F channels drop, but CLR drops too → ratios stay meaningful.

### NIR = Near-Infrared photodiode (~850–900 nm)
Why this matters:
- Many white LEDs leak IR.
- Organic materials often change IR reflectance before visible color shifts.
- Ambient sunlight has a lot of IR.

Use cases:
- Detect ambient contamination (sunlight vs LED).
- Correct visible channels (if NIR spikes, your visible data is probably compromised).
- Feature extraction (especially for fermentation / bio / chemical systems).

If you’re doing controlled illumination, NIR should be:
- Stable
- Low
- Boring

### Why there are two CLR and two NIR readings
The AS7341 has two ADC paths / measurement groups, internally multiplexed.

They are not different sensors, just:
- Different integration cycles
- Different gain paths

 In most applications, just pick one CLR and one NIR and be consistent.

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
