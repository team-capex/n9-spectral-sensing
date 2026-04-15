"""
coordinate_map.py
=================
Pure coordinate math: converts grid (col, row) indices for PCB sensor wells,
sample holder slots, and the test cell into absolute robot workspace XYZ (mm).

No hardware calls, no side effects — safe to unit-test in isolation.

PCB sensor grid layout (2 cols × 8 rows = 16 sensors):
    Odd sensors  (1, 3, 5, ..., 15) → col 0
    Even sensors (2, 4, 6, ..., 16) → col 1
    Row index increases with sensor number.
    Formula: col = (sensor_no - 1) % 2,  row = (sensor_no - 1) // 2

Sample holder grid layout (5 cols × 18 rows = 90 slots, 1-indexed):
    Formula: col = (slot_no - 1) % n_cols,  row = (slot_no - 1) // n_cols

Test cell:
    Robot position is stored as XYZ (mm). The arm travels to this point using
    standard move_xy / move_z calls. Insert sequence: move to xyz → engage piston
    → open gripper → home → fill (fill_pump) → drain (drain_pump).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

XYZ = Tuple[float, float, float]


# ── Layout dataclasses (populated from config.yaml) ───────────────────────────

@dataclass(frozen=True)
class PCBBoardLayout:
    pcb_id: str
    board_id: str               # cross-reference to spectral boards[] in config
    origin_xyz: XYZ             # robot coords (mm) of well (col=0, row=0) = sensor 1
    col_spacing_mm: float       # 30.0 mm between the 2 columns
    row_spacing_mm: float       # 15.0 mm between the 8 rows
    pick_z_mm: float            # Z to descend to for pick/place (gripper)
    pipette_dispense_z_mm: float  # Z for pipette tip during liquid dispensing


@dataclass(frozen=True)
class SampleHolderLayout:
    holder_id: str
    origin_xyz: XYZ             # robot coords (mm) of slot (col=0, row=0)
    col_spacing_mm: float       # 11.5 mm
    row_spacing_mm: float       # 5.75 mm
    n_cols: int                 # 5
    n_rows: int                 # 18
    pick_z_mm: float


@dataclass(frozen=True)
class TestCellLayout:
    """
    Test cell configuration.

    The robot arm travels to xyz using standard XYZ moves.
    Insert sequence: move to xyz → engage piston → open gripper → home
                     → fill (fill_pump) → drain (drain_pump).
    """
    xyz: XYZ                    # robot XYZ (mm) for sample insertion/test position
    safe_travel_z_mm: float     # Z (mm) to raise to before/after test cell moves
    piston_output_index: int    # digital output index for hydraulic piston
    fill_pump: str              # peristaltic pump name for filling (e.g. "H2O_ECELL")
    drain_pump: str             # peristaltic pump name for draining (e.g. "Drain")
    fill_volume_ml: float       # volume to fill the test cell (mL)
    # extra gripper rotation (degrees) for test cell XY moves only
    gripper_angle_deg: float = 0.0


# ── CoordinateMap ─────────────────────────────────────────────────────────────

class CoordinateMap:
    """
    Translates logical grid positions to absolute robot XYZ coordinates.

    All coordinates are in millimetres (mm), matching the north API units.
    Z values in returned tuples are set to the appropriate travel/pick/dispense
    height depending on the method called.
    """

    def __init__(
        self,
        pcb_layouts: list[PCBBoardLayout],
        holder_layouts: list[SampleHolderLayout],
        test_cell: TestCellLayout,
    ) -> None:
        self._pcbs: dict[str, PCBBoardLayout] = {
            p.pcb_id: p for p in pcb_layouts
        }
        self._holders: dict[str, SampleHolderLayout] = {
            h.holder_id: h for h in holder_layouts
        }
        self._test_cell = test_cell

    # ── PCB ───────────────────────────────────────────────────────────────────

    def pcb_sensor_xyz(self, pcb_id: str, col: int, row: int) -> XYZ:
        """XYZ at the sensor well, z = pick_z_mm (for pick/place)."""
        layout = self._get_pcb(pcb_id)
        ox, oy, _ = layout.origin_xyz
        return (
            ox + col * layout.col_spacing_mm,
            oy + row * layout.row_spacing_mm,
            layout.pick_z_mm,
        )

    def pcb_pipette_xyz(self, pcb_id: str, col: int, row: int) -> XYZ:
        """XYZ at the sensor well, z = pipette_dispense_z_mm (for pipette liquid dispensing)."""
        layout = self._get_pcb(pcb_id)
        ox, oy, _ = layout.origin_xyz
        return (
            ox + col * layout.col_spacing_mm,
            oy + row * layout.row_spacing_mm,
            layout.pipette_dispense_z_mm,
        )

    # ── Sample holder ─────────────────────────────────────────────────────────

    def holder_slot_xyz(self, holder_id: str, col: int, row: int) -> XYZ:
        """XYZ at the holder slot, z = pick_z_mm."""
        layout = self._get_holder(holder_id)
        ox, oy, _ = layout.origin_xyz
        return (
            ox + col * layout.col_spacing_mm,
            oy + row * layout.row_spacing_mm,
            layout.pick_z_mm,
        )

    # ── Test cell ─────────────────────────────────────────────────────────────

    @property
    def test_cell(self) -> TestCellLayout:
        """Direct access to the TestCellLayout."""
        return self._test_cell

    def test_cell_xyz(self) -> XYZ:
        """XYZ (mm) of the test cell insertion/test position."""
        return self._test_cell.xyz

    # ── Index helpers (static) ────────────────────────────────────────────────

    @staticmethod
    def pcb_sensor_to_col_row(sensor_no: int) -> tuple[int, int]:
        """
        Convert 1-indexed sensor number to (col, row) in the 2×8 PCB grid.

        Physical layout:
            Odd sensors  (1, 3, ..., 15) → col 0
            Even sensors (2, 4, ..., 16) → col 1

        Returns (col, row).
        """
        if not (1 <= sensor_no <= 16):
            raise ValueError(f"sensor_no must be 1..16, got {sensor_no}")
        col = (sensor_no - 1) % 2
        row = (sensor_no - 1) // 2
        return col, row

    @staticmethod
    def col_row_to_pcb_sensor(col: int, row: int) -> int:
        """Inverse of pcb_sensor_to_col_row. Returns 1-indexed sensor number."""
        if col not in (0, 1) or not (0 <= row <= 7):
            raise ValueError(f"PCB col must be 0-1, row must be 0-7; got col={col}, row={row}")
        return row * 2 + col + 1

    @staticmethod
    def holder_slot_to_col_row(slot_no: int, n_cols: int = 5) -> tuple[int, int]:
        """
        Convert 1-indexed slot number to (col, row) in the sample holder grid.

        Returns (col, row).
        """
        if slot_no < 1:
            raise ValueError(f"slot_no must be >= 1, got {slot_no}")
        col = (slot_no - 1) % n_cols
        row = (slot_no - 1) // n_cols
        return col, row

    @staticmethod
    def col_row_to_holder_slot(col: int, row: int, n_cols: int = 5) -> int:
        """Inverse of holder_slot_to_col_row. Returns 1-indexed slot number."""
        return row * n_cols + col + 1

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_pcb(self, pcb_id: str) -> PCBBoardLayout:
        try:
            return self._pcbs[pcb_id]
        except KeyError:
            raise KeyError(f"PCB '{pcb_id}' not found in coordinate map. "
                           f"Available: {list(self._pcbs)}")

    def _get_holder(self, holder_id: str) -> SampleHolderLayout:
        try:
            return self._holders[holder_id]
        except KeyError:
            raise KeyError(f"Sample holder '{holder_id}' not found. "
                           f"Available: {list(self._holders)}")

    # ── Factory from config dict ──────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: dict) -> "CoordinateMap":
        """
        Build a CoordinateMap from the parsed config.yaml dict.

        Expected top-level keys: sensing_stations, sample_holders, test_cell.
        """
        pcb_layouts = [
            PCBBoardLayout(
                pcb_id=p["id"],
                board_id=p["board_id"],
                origin_xyz=tuple(p["origin_xyz"]),       # type: ignore[arg-type]
                col_spacing_mm=float(p["col_spacing_mm"]),
                row_spacing_mm=float(p["row_spacing_mm"]),
                pick_z_mm=float(p["pick_z_mm"]),
                pipette_dispense_z_mm=float(p.get("pipette_dispense_z_mm", 35.0)),
            )
            for p in cfg.get("sensing_stations", [])
        ]

        holder_layouts = [
            SampleHolderLayout(
                holder_id=h["holder_id"],
                origin_xyz=tuple(h["origin_xyz"]),        # type: ignore[arg-type]
                col_spacing_mm=float(h["col_spacing_mm"]),
                row_spacing_mm=float(h["row_spacing_mm"]),
                n_cols=int(h["n_cols"]),
                n_rows=int(h["n_rows"]),
                pick_z_mm=float(h["pick_z_mm"]),
            )
            for h in cfg.get("sample_holders", [])
        ]

        tc = cfg["test_cell"]
        test_cell = TestCellLayout(
            xyz=tuple(tc["xyz"]),                                       # type: ignore[arg-type]
            safe_travel_z_mm=float(tc.get("safe_travel_z_mm", 200.0)),
            piston_output_index=int(tc.get("piston_output_index", 2)),
            fill_pump=str(tc.get("fill_pump", "H2O_ECELL")),
            drain_pump=str(tc.get("drain_pump", "Drain")),
            fill_volume_ml=float(tc.get("fill_volume_ml", 11.5)),
            gripper_angle_deg=float(tc.get("gripper_angle", 0.0)),
        )

        return cls(pcb_layouts, holder_layouts, test_cell)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def pcb_ids(self) -> list[str]:
        return list(self._pcbs)

    @property
    def holder_ids(self) -> list[str]:
        return list(self._holders)

    def pcb_layout(self, pcb_id: str) -> PCBBoardLayout:
        return self._get_pcb(pcb_id)

    def holder_layout(self, holder_id: str) -> SampleHolderLayout:
        return self._get_holder(holder_id)

