# CLAUDE.md — N9 Spectral Sensing System

This file provides context for Claude Code development sessions. The system is operated by scientists who may not be able to provide technical context themselves, so read this file carefully before making any changes.

---

## Claude Instructions for each session

- Use project as a human user would: experiment-run CLI to run experiments with real hardware.
- Do not generate unnecessary, one-off python files for new experiments - use available code where possible.
- Only define new steps for experiment_runner.py when absolutely necessary.
- Edit config / json files to perform requested experiments: config.yaml, holder_state.json etc. See example_experiment.yaml for a typical experimental setup.
- Once experiment plan is confirmed and changes made, run the experiment-run command yourself.

### Experiment file naming and storage

- **Never write experiments directly to `experiment.yaml` in the repo root.** That file is the active experiment slot used by the CLI — it gets overwritten each run and is not a permanent record.
- **Save every new experiment as a named file inside `experiment-database/`**, using a descriptive name that reflects the experiment purpose and date. Example: `experiment-database/pc-scan-holder3-20260410.yaml`.
- After saving to `experiment-database/`, copy (or symlink) the file to `experiment.yaml` at the repo root so the CLI can run it. Do this by writing `experiment.yaml` as a copy of the database file — not in place of it.
- Naming convention: `<sample-type>-<brief-purpose>-<YYYYMMDD>.yaml`, e.g. `ni-ecell-dye-mixture-20260415.yaml`.
- Before creating a new experiment file, check `experiment-database/` for an existing experiment that can be reused or adapted.

## System Purpose

Automated high-throughput spectral colour characterisation of material samples using:
- An **N9 robot arm** (4-axis SCARA, north_c9 library)
- Up to **5 custom spectral sensor PCBs**, each with 16 AS7341 colour sensors
- A **fluidic pump controller PCB** for stepper-driven dye mixing and dispensing
- **Peristaltic pumps** for filling/draining an electrochemical test cell
- An **electrochemical test cell** for Ni sample testing

The Python software orchestrates the full workflow: pick samples → dispense liquids → scan colours → run test cell → return samples.

---

## Repository Layout

```
n9-spectral-sensing/
├── config.yaml                  # Hardware configuration (boards, robot, pumps, holders)
├── experiment.yaml              # Experiment workflow definition
├── holder_state.json            # Initial sample holder contents
├── legacy_rack_state.json       # Initial legacy rack contents
├── pyproject.toml               # Package metadata and CLI entry points
│
├── src/
│   ├── spectral_board_manager/  # Standalone spectral sensing package
│   │   ├── board_manager.py     # Main parallel board orchestration (BoardManager)
│   │   ├── spectral_sensor.py   # ESP32 serial communication (SpectralSensor)
│   │   ├── data_parser.py       # Data parsing, CSV logging, plotting (SpectralAnalysis)
│   │   ├── cli.py               # spectral-run entry point
│   │   └── plotter.py           # spectral-plotter entry point
│   │
│   ├── n9_controller/           # Full robot experiment orchestration package
│   │   ├── experiment_runner.py # Top-level orchestrator (ExperimentRunner)
│   │   ├── experiment_config.py # Loads/validates experiment.yaml
│   │   ├── state_machine.py     # Experiment state + JSON persistence (ExperimentState)
│   │   ├── coordinate_map.py    # Pure grid→XYZ math (CoordinateMap)
│   │   ├── robot.py             # N9 robot abstraction (N9RobotController)
│   │   └── pump_controller.py   # Peristaltic pumps + digital outputs (PumpController)
│   │
│   └── fluidic_hardware/        # Stepper pump serial control
│       └── pump_controller.py   # PumpController for stepper pump board
│
├── firmware/
│   ├── spectral-sensor-board/   # ESP32-S3 firmware for black spectral PCB
│   │   ├── platformio.ini
│   │   └── src/
│   │       ├── main.cpp
│   │       ├── AS7341Array.h/.cpp   # 16-sensor array via TCA9548 I2C mux
│   │       └── analog_out.h/.cpp    # 0–10V DAC for LED driver
│   │
│   └── pump-controller-n9/      # ESP32-S3 firmware for blue pump PCB
│       ├── platformio.ini
│       └── src/
│           ├── main.cpp
│           ├── ble.h/.cpp           # Bluetooth LE communication
│           └── led_animations.h/.cpp
│
├── data/
│   ├── spectral_log.csv         # All spectral measurements
│   ├── state/
│   │   └── experiment_state.json  # Persisted experiment state (for resume)
│   └── cleaning_report.txt
│
└── plots/                       # Output from spectral-plotter
```

---

## Python Packages

### `spectral_board_manager` — Standalone Spectral Sensing

**CLI entry points:**
- `spectral-run` → `spectral_board_manager.cli:main` — run a spectral scan
- `spectral-plotter` → `spectral_board_manager.plotter:main` — plot CSV results

**Key classes:**

| Class | File | Purpose |
|-------|------|---------|
| `BoardManager` | `board_manager.py` | Orchestrates up to 5 boards in parallel via `ThreadPoolExecutor`; manages config loading, validation, and voltage safety |
| `SpectralSensor` | `spectral_sensor.py` | Serial comms to one ESP32 board; text protocol; `@skip_if_sim` decorator for simulation |
| `SpectralAnalysis` | `data_parser.py` | Parses sensor responses; writes `spectral_log.csv`; estimates hex colour |

**BoardManager config loading:** reads `config.yaml`, validates gain (1–256), control_voltage (0–10V), sensors_in_use (1–16). Boards that fail validation raise on init.

**Voltage safety:** all boards are guaranteed to return to 0V in `finally` blocks, including on error or KeyboardInterrupt.

---

### `n9_controller` — Robot Experiment Orchestration

**CLI entry point:**
- `experiment-run` → `n9_controller.experiment_runner:main`

**Key classes:**

#### `ExperimentRunner` (`experiment_runner.py`)
Top-level orchestrator. Loads `config.yaml` and `experiment.yaml`, constructs all hardware objects, and executes the ordered step list. Each step is a method (e.g., `_step_home_robot`, `_step_load_from_sample_holders_to_pcb`). Supports `--resume` flag.

#### `N9RobotController` (`robot.py`)
Wraps the `north` (north_c9) API. Key methods:
- `home()` — home the arm
- `pick_from(xyz, z_pick)` — pick a sample at XYZ
- `place_at(xyz, z_place)` — place a sample at XYZ
- `transfer(from_xyz, to_xyz, ...)` — combined pick+place

Test cell workflow uses encoder counts directly (`insert_counts`, `test_counts` in `config.yaml`) rather than XYZ.

Simulation mode (`simulate: true`) logs moves and does not call hardware. `device_serial` in config.yaml selects a specific FTDI device (null = first found).

#### `PumpController` (`pump_controller.py` in n9_controller)
Controls peristaltic pumps and digital outputs via N9 robot controller outputs (legacy wiring). Volume model:
```
volume_ml = flow_rate_ml_per_s × time_s + offset_ml
```
Digital output indices: 2 = piston, 3 = drain.

#### `CoordinateMap` (`coordinate_map.py`)
Pure math, no hardware. Converts (col, row) grid positions to robot XYZ (mm). Layout classes:
- `PCBBoardLayout` — 2 cols × 8 rows; sensor numbering: odd sensors → col 0, even → col 1; formula: `col = (sensor_no-1) % 2`, `row = (sensor_no-1) // 2`
- `SampleHolderLayout` — 5 cols × 18 rows
- `LegacySampleRackLayout` — configurable; legacy default 11×8; col_spacing is negative (X decreases with col)
- `TestCellLocation` — single XYZ point

#### `ExperimentState` (`state_machine.py`)
Tracks all sample lifecycles. Three parallel state machines:
- `PCBSensorState` — EMPTY_CLEAN → SAMPLE_LOADED → MEASURED → EMPTY_DIRTY
- `HolderSlotState` — FRESH / EMPTY / USED / CLEAN
- `LegacyRackSlotState` — FRESH / EMPTY / USED

Persisted atomically (write temp file → rename) to `data/state/experiment_state.json`. Loaded on `--resume`. Delete this file to start fresh.

#### `ExperimentConfig` (`experiment_config.py`)
Parses `experiment.yaml`. Key data classes: `SampleSpec`, `ScanningConfig`, `TestCellConfig`, `MixtureConfig`. Valid step names are defined in a `frozenset` — add new steps there when extending.

---

### `fluidic_hardware` — Stepper Pump Controller

Controls the blue pump controller PCB over serial. Text-based protocol; responses are checked for `#` acknowledgement character. Same `@skip_if_sim` simulation pattern as spectral sensors.

Manages 4 stepper pumps:
- Pump 1: dose pump (dispenses into wells)
- Pump 2: water
- Pump 3: dye 1
- Pump 4: dye 2

---

## Configuration System

### `config.yaml` Sections

| Section | Description |
|---------|-------------|
| `data_dir` | Output directory (default: `"data"`) |
| `boards` | List of spectral PCBs (board_id, com_port, sensor_settings, control_voltage) |
| `robot` | N9 arm settings (simulate, safe_travel_z_mm, device_serial) |
| `sensing_stations` | Maps board_ids to robot XYZ positions and grid spacings |
| `sample_holders` | Sample holder rack positions and grid dimensions |
| `legacy_sample_racks` | Older rack format; col_spacing is negative (-25.5 mm) |
| `peristaltic_pumps` | Dict of pump_name → {index, flow_rate_ml_per_s, offset_ml} |
| `test_cell` | Robot position (XYZ), piston/drain output indices, fill pump/volume |
| `fluidic_pump_controller` | COM port, baud, pipette offsets, mixture pump indices |

### `experiment.yaml` Structure

```yaml
experiment_id: str
steps: [list of step names]
sensing_stations: [list of station IDs from config.yaml]
sample_holders: [list of holder IDs]
legacy_sample_racks: [list of rack IDs]
samples:
  - sample_type: str
    count: int
    source: holder | legacy_rack
    destination: pcb | test_cell
scanning:
  interval_minutes: float
  total_duration_hours: float
test_cell_config:
  fill_pump: str
  fill_volume_ml: float
  drain_volume_ml: float
  wait_time_s: float
mixture_config:
  water_ml: float
  dye1_ml: float
  dye2_ml: float
```

---

## Firmware

Both PCBs use **PlatformIO** (not Arduino IDE). Platform: `espressif32`, board: `esp32-s3-devkitc-1`, baud: 115200.

### Spectral Sensor Board (black PCB) — `firmware/spectral-sensor-board/`

- 16× AS7341 spectral sensors on TCA9548A I2C multiplexer
- DAC for 0–10 V LED driver control
- Optional NTC thermistor probes + heater cartridges (PID firmware)
- Bluetooth not used on this board

**Serial protocol (text-based):**

| Command | Response |
|---------|---------|
| `readSensor(n)` | `[DATA] F1=...,F2=...,F3=...,F4=...,F5=...,F6=...,F7=...,F8=...,CLR=...,NIR=...,SENSOR=n` |
| `changeSettings(gain,atime,astep)` | ack |
| `changeLedMode(0\|1)` | ack (1 = solid sample mode) |
| `setVoltage(v)` | ack (0–10 V) |
| `setTemperatureTarget(c)` | ack (enables PID) |
| `clearTemperatureTarget()` | ack |
| `setHeaterPower(n,power)` | ack |
| `getTemperature(probe)` | temperature float (probe 1 or 2) |

Python side waits for `[DATA]` prefix in `SpectralSensor.readSensor()`.

### Pump Controller Board (blue PCB) — `firmware/pump-controller-n9/`

- 4 AccelStepper stepper pumps
- Adafruit SHT4x temperature/humidity sensor
- Adafruit SSD1306 OLED display
- NimBLE Bluetooth LE
- NeoPixel status LEDs

**Serial protocol:** text commands; `#` in response = acknowledgement.

---

## Serial Protocol Notes

**SpectralSensor** (`spectral_sensor.py`):
- DTR/RTS toggled on connect to auto-reset ESP32
- `@skip_if_sim` decorator skips all hardware calls in simulate mode
- Reads until `[DATA]` prefix; timeout configurable (default 60 s)

**Fluidic PumpController** (`fluidic_hardware/pump_controller.py`):
- Same DTR/RTS pattern
- Checks response for `#` ack character

---

## Key Design Patterns

### Simulation mode
- Robot: set `robot.simulate: true` in config.yaml → `N9RobotController` logs moves, no hardware
- Spectral boards: `SpectralSensor(sim=True)` → all sensor reads return dummy data
- Fluidic pumps: `PumpController(sim=True)` → commands are no-ops
- Dispenser: raises `NotImplementedError` unless `simulate=True`

### Parallel board scanning
`BoardManager.run()` uses `ThreadPoolExecutor` to scan all boards concurrently. Boards are I/O-bound (serial), so threading is effective.

### Robot homing
`N9RobotController` automatically re-homes every `home_interval` calls to `place_at()` (configurable, default 6). This compensates for encoder drift.

### Volume model
```python
volume_ml = flow_rate_ml_per_s * time_s + offset_ml
```
Offset accounts for pump dead-band. Calibrated per pump in `config.yaml`.

### Atomic state writes
`ExperimentState.save()` writes to a temp file then renames, preventing partial writes on crash.

---

## Data Schema

### `data/spectral_log.csv`

| Column | Description |
|--------|-------------|
| `timestamp` | ISO8601 datetime |
| `board_id` | e.g. `board-1` |
| `experiment_id` | From `mgr.experiment_id` or experiment.yaml |
| `sensor` | Sensor number 1–16 |
| `sample_id` | Unique sample identifier |
| `sample_type` | e.g. `PC`, `Ni` |
| `dye_type` | Dye name if applicable |
| `temp_c` | Temperature at time of read (if available) |
| `F1`–`F8` | Raw photodiode counts per spectral channel |
| `CLR` | Broadband visible count |
| `NIR` | Near-infrared count |
| `hex_color` | Estimated hex colour string |

---

## Development Notes

- **Python version:** ≥3.10 required (uses `match` syntax in places; type hints throughout)
- **Virtual environment:** `.venv/` at repo root; activate before running anything
- **Install:** `pip install -e .` (editable install from `src/`)
- **Type checking:** mypy strict mode configured in `pyproject.toml` (`disallow_untyped_defs = true`)
- **Linting:** ruff (configured in `pyproject.toml`)
- **Quick import test:**
  ```bash
  source .venv/bin/activate && python3 -c "from n9_controller.coordinate_map import CoordinateMap; print('OK')"
  ```

### Adding a new experiment step

1. Add the step name string to the `VALID_STEPS` frozenset in `experiment_config.py`
2. Add a method `_step_<name>(self)` to `ExperimentRunner` in `experiment_runner.py`
3. Add the step name to `steps:` list in `experiment.yaml`

### Adding a new board type

The `spectral_board_manager` package is self-contained and can be used independently of the robot. `BoardManager` instantiates `SpectralSensor` and `SpectralAnalysis` per board. To add a new sensor type, extend `SpectralSensor` or create a parallel class following the same interface.

### Config loading pattern

Both packages load YAML config files into dataclasses using `pyyaml`. The config is validated eagerly on `__init__` — bad values raise `ValueError` before any hardware is touched. When adding new config fields, add validation in the same init block.
