from typing import Optional
from abc import ABC, abstractmethod
from math import log10
import time
from datetime import datetime
import comtypes.client as client
import pandas as pd

from .pstat_manager import PstatManager
from .gamry_objects import get_gamry_module, GamryObjects
from .event_manager import GamryReadZEvents, EventHandler, GamryDtaqEvents
from .errors import gamry_error_decoder

__all__ = ["EIS", "CV", "CP", "CA", "OCP"]


class UninitializedRecipeError(Exception):
    """A Recipe has not been properly initialized yet."""


class Recipe(ABC):
    # The default pstat type for a recipe
    DEFAULT_PSTAT = GamryObjects.PC5Pstat

    def __init__(self, pstat_manager: PstatManager = None, verbose=False,
                 ie_range_a: Optional[float] = None):
        self.GamryCOM = get_gamry_module()
        self.pstat_manager = pstat_manager or PstatManager(pstat_com=self.DEFAULT_PSTAT)
        self.event_handler: EventHandler = None
        self.terminate = False
        self.verbose = verbose
        self._managed_connections = []
        self.signal = None
        self.dtaq = None
        # VENDORED ADDITION (n9): optional fixed current range, expressed as
        # the maximum expected current in A. 0/None keeps the driver default
        # (autorange). Applied via apply_current_range() during initialize.
        self.ie_range_a = ie_range_a or None

    def apply_current_range(self) -> None:
        """VENDORED ADDITION (n9): pin the current range to the smallest range
        that accommodates ie_range_a amperes; no-op when unset (autorange)."""
        if not self.ie_range_a:
            return
        self.pstat.SetIERangeMode(False)
        self.pstat.SetIERange(self.pstat.TestIERange(abs(self.ie_range_a)))

    def set_vch_range(self, volts) -> None:
        """VENDORED ADDITION (n9): apply the voltage-channel range for a
        full-scale voltage given in VOLTS; None/0 enables autorange.

        The COM API is INDEX-based (typelib: TestVchRange(volts) -> index,
        SetVchRange(index) -> index_set, out-of-range indices clamp to the
        instrument's top range). Verified on the Reference 600 2026-07-14:
        indices 0..3 = 30 mV / 300 mV / 3 V / 12 V. The pre-modification
        code passed volts where an index was expected, which silently
        clamped to the top (12 V) range."""
        pstat = self.pstat
        if not volts or volts <= 0:
            pstat.SetVchRangeMode(True)      # autorange
            return
        index = pstat.TestVchRange(volts)
        if index < 0:
            index = 99   # above the top range — clamps to the largest
        pstat.SetVchRangeMode(False)         # fixed, as explicitly requested
        pstat.SetVchRange(index)

    def manage_connection(self, connection) -> None:
        """Register an event connection which should be automatically managed."""
        self._managed_connections.append(connection)

    def close_connections(self) -> None:
        """Disconenct all of the managed connections."""
        for ii, connection in enumerate(self._managed_connections):
            self.log(f"Closing connection: {ii}")
            connection.disconnect()
        self._managed_connections.clear()

    def make_event_connection(self, dtaq, event_handler: EventHandler) -> None:
        """Establish a connection to a dtaq with its event handler.
        Ensure the connection is disconnected automatically once finalization
        is called."""
        connection = client.GetEvents(dtaq, event_handler)
        # Ensure the connection is managed and properly closed at the end.
        self.manage_connection(connection)

    def _run(self) -> None:
        self.devices = GamryObjects.DeviceList.create()
        self.device = self.devices.EnumSections()[0]  # First device. XXX: Is this always the case?
        # Construct and open the potentiostat.
        with self.pstat_manager.with_device(self.device):
            self.log("Initializing...")
            self.initialize()
            try:
                self.log("Running measurement.")
                self.measure()
            finally:
                # Ensure teardown is always called, as we may need to manage
                # opened event connections.
                self.log("Finalizing")
                self.finalize()

    @property
    def pstat(self):
        """Access the pstat object from the pstat manager.
        Will only be different from None while the pstat is connected."""
        return self.pstat_manager.pstat

    def run(self) -> None:
        """Execute the recipe."""
        try:
            self._run()
        except Exception as e:
            raise gamry_error_decoder(e)

    @property
    def active(self) -> bool:
        if self.event_handler is None:
            raise UninitializedRecipeError("No event handler has been constructed yet!")
        return self.event_handler.active

    @abstractmethod
    def initialize(self):
        """Initialize the instruments according to the recipe specifications."""

    def measure(self):
        # Keep the measurement alive, until the event handler
        # is no longer active, or we decide that to manually trigger a terminate.
        while self.active and not self.terminate:
            client.PumpEvents(1)
            time.sleep(0.1)
            n = self.event_handler.get_num_datapoints()
            now = datetime.now()
            self.log(f"{now}   Num Datapoints: {n}")

    def finalize(self) -> None:
        """The recipe may perform some final tasks after measurements have concluded.
        The recipe should not be manually closing the pstat."""
        self.close_connections()
        self.signal = None
        self.dtaq = None

    def get_data(self) -> pd.DataFrame:
        """Return all relevant data in a DataFrame"""
        if self.event_handler is None:
            raise UninitializedRecipeError("No event handler has been constructed yet!")
        return self.event_handler.get_data()

    def log(self, *args, **kwargs) -> None:
        if self.verbose:
            print(*args, **kwargs)


class EIS(Recipe):
    def __init__(
        self,
        init_freq: float = 100_000.0,
        final_freq: float = 1.0,
        pts_per_dec: int = 10,  # Points per decade
        dc: float = 0.0,
        ac: float = 0.01,
        VchRange: Optional[float] = None,  # VENDORED ADDITION (n9); None = default
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.init_freq = init_freq
        self.final_freq = final_freq
        self.pts_per_dec = pts_per_dec
        self.dc = dc  # DC voltages
        self.ac = ac  # AC voltages
        self.VchRange = VchRange or None  # 0 → default

    def initialize_pstat(self):
        pstat = self.pstat  # Alias
        pstat.SetCtrlMode(self.GamryCOM.PstatMode)
        pstat.SetCell(self.GamryCOM.CellOff)
        pstat.SetIEStability(self.GamryCOM.StabilityNorm)
        # VENDORED ADDITION (n9): optional explicit ranges
        if self.VchRange:
            self.set_vch_range(self.VchRange)
        self.apply_current_range()
        pstat.SetVoltage(self.dc)
        pstat.SetCell(self.GamryCOM.CellOn)

    @property
    def maxpoints(self) -> int:
        return round(0.5 + (abs(log10(self.final_freq) - log10(self.init_freq)) * self.pts_per_dec))

    @property
    def loginc(self):
        inc = 1 / self.pts_per_dec
        if self.init_freq > self.final_freq:
            inc = -inc
        return inc

    def initialize(self) -> None:
        self.initialize_pstat()
        self.dtaq = GamryObjects.ReadZ.create()
        self.dtaq.Init(self.pstat)
        self.event_handler = GamryReadZEvents(
            self.dtaq,
            self.maxpoints,
            self.ac,
            self.init_freq,
            self.loginc,
            verbose=self.verbose,
        )

        self.make_event_connection(self.dtaq, self.event_handler)

        # run the first EIS point after grabing and initializing a pstat from device list.
        # All other frequency points are triggered to run
        # once the DataDone event is fired from GamryCom
        self.event_handler.measure_first()
        self.log("Initialized EIS")


class CV(Recipe):
    def __init__(
        self,
        init_voltage: float = 0.0,
        final_voltage: float = 0.0,
        apex1: float = 0.5,
        apex2: float = -0.5,
        scanrate1: float = 0.1,
        scanrate2: Optional[float] = None,
        scanrate3: Optional[float] = None,
        stepsize: float = 0.01,
        cycles: int = 2,
        VchRange: Optional[float] = None,   # volts; None/0 = autorange (n9)
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.init_voltage = init_voltage
        self.final_voltage = final_voltage
        self.apex1 = apex1
        self.apex2 = apex2
        self.scanrate1 = scanrate1
        # Unclear what these are. Bookkeeping variables?
        self.scanrate2 = scanrate2 if scanrate2 is not None else scanrate1
        self.scanrate3 = scanrate3 if scanrate3 is not None else scanrate1
        self.stepsize = stepsize
        self.cycles = cycles
        self.VchRange = VchRange

    @property
    def samplerate(self):
        # TODO: Is this samplerate the same if scanrate2 and scanrate3
        # are not equal to scanrate1?
        return self.stepsize / self.scanrate1

    def initialize(self):
        self.dtaq = GamryObjects.DtaqRcv.create()

        self.event_handler = GamryDtaqEvents(self.dtaq, verbose=self.verbose)
        self.make_event_connection(self.dtaq, self.event_handler)

        self.signal = GamryObjects.SignalRupdn.create()

        self.signal.Init(
            self.pstat,
            self.init_voltage,
            self.apex1,
            self.apex2,
            self.final_voltage,
            self.scanrate1,
            self.scanrate2,
            self.scanrate3,
            0.0,
            0.0,
            0.0,
            self.samplerate,
            self.cycles,
            self.GamryCOM.PstatMode,
        )

        self.pstat.SetCtrlMode(self.GamryCOM.PstatMode)
        self.pstat.SetCell(self.GamryCOM.CellOff)
        self.pstat.SetIEStability(self.GamryCOM.StabilityNorm)
        self.set_vch_range(self.VchRange)   # VENDORED ADDITION (n9)
        self.apply_current_range()          # VENDORED ADDITION (n9)

        self.dtaq.Init(self.pstat)
        self.pstat.SetSignal(self.signal)
        self.pstat.SetCell(self.GamryCOM.CellOn)
        time.sleep(1)

        self.dtaq.Run(True)
        self.log("Initialized CV")

    def get_data(self) -> pd.DataFrame:
        df = super().get_data()
        return _adjust_column_names(
            df,
            {
                "0": "Time (s)",
                "1": "Vf (V vs Ref)",
                "2": "Vu (V)",
                "3": "Im (A)",
                "4": "Vsig",
                "5": "Ach (V)",
                "6": "IERange",
                "7": "Overbit1",
                "8": "Stop Test",
                "9": "Cycle",
                "10": "Temperature (C)",
            },
        )


class CP(Recipe):
    def __init__(
        self,
        init_voltage: float = 0.001,
        tinit=10,
        vstep1=0.05,
        tstep1=20,
        vstep2=0.1,
        tstep2=20,
        sample=0.01,
        VchRange: Optional[float] = None,   # volts; None/0 = autorange (n9)
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.init_voltage = init_voltage
        self.tinit = tinit
        self.vstep1 = vstep1
        self.tstep1 = tstep1
        self.vstep2 = vstep2
        self.tstep2 = tstep2
        self.sample = sample
        self.VchRange = VchRange

    def initialize_pstat(self):
        pstat = self.pstat
        pstat.SetCtrlMode(self.GamryCOM.GstatMode)
        pstat.SetCell(self.GamryCOM.CellOff)
        pstat.SetIEStability(self.GamryCOM.StabilityFast)
        self.set_vch_range(self.VchRange)   # VENDORED ADDITION (n9)
        self.apply_current_range()          # VENDORED ADDITION (n9)

    def initialize(self):
        self.signal = GamryObjects.SignalDstep.create()
        self.dtaq = GamryObjects.DtaqChrono.create()

        self.event_handler = GamryDtaqEvents(dtaq=self.dtaq, verbose=self.verbose)
        self.make_event_connection(self.dtaq, self.event_handler)

        self.signal.Init(
            self.pstat,
            self.init_voltage,
            self.tinit,
            self.vstep1,
            self.tstep1,
            self.vstep2,
            self.tstep2,
            self.sample,
            self.GamryCOM.GstatMode,
        )
        self.initialize_pstat()

        self.dtaq.Init(self.pstat, self.GamryCOM.ChronoPot)
        self.pstat.SetSignal(self.signal)
        self.pstat.SetCell(self.GamryCOM.CellOn)

        self.dtaq.Run(True)
        self.log("Initialized CP")

    def get_data(self) -> pd.DataFrame:
        df = super().get_data()
        return _adjust_column_names(
            df,
            {
                "0": "Time (s)",
                "1": "Vf (V vs Ref)",
                "2": "Vu (V)",
                "3": "Im (A)",
                "4": "Charge Q",
                "5": "Vsig",
                "6": "Ach (V)",
                "7": "IERange",
                "8": "Overbit1",
                "9": "Stop Test",
            },
        )


class CA(Recipe):
    # Note: this looks a lot like CP, but uses PstatMode instead of GstatMode.
    # Also the dtaq is a bit different.

    def __init__(
        self,
        init_voltage: float = 0.5,
        tinit=10,
        vstep1=0.5,
        tstep1=20,
        vstep2=6.6,
        tstep2=20,
        sample=0.01,
        VchRange: Optional[float] = None,   # volts; None/0 = autorange (n9)
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.init_voltage = init_voltage
        self.tinit = tinit
        self.vstep1 = vstep1
        self.tstep1 = tstep1
        self.vstep2 = vstep2
        self.tstep2 = tstep2
        self.sample = sample
        self.VchRange = VchRange

    def initialize_pstat(self):
        pstat = self.pstat  # Alias
        pstat.SetCtrlMode(self.GamryCOM.PstatMode)
        pstat.SetCell(self.GamryCOM.CellOff)
        pstat.SetIEStability(self.GamryCOM.StabilityNorm)
        self.set_vch_range(self.VchRange)   # VENDORED ADDITION (n9)
        self.apply_current_range()          # VENDORED ADDITION (n9)

    def initialize(self):
        self.signal = GamryObjects.SignalDstep.create()
        self.dtaq = GamryObjects.DtaqChrono.create()

        self.event_handler = GamryDtaqEvents(dtaq=self.dtaq, verbose=self.verbose)
        self.make_event_connection(self.dtaq, self.event_handler)

        self.signal.Init(
            self.pstat,
            self.init_voltage,
            self.tinit,
            self.vstep1,
            self.tstep1,
            self.vstep2,
            self.tstep2,
            self.sample,
            self.GamryCOM.PstatMode,
        )
        self.initialize_pstat()

        self.dtaq.Init(self.pstat, self.GamryCOM.ChronoAmp)
        self.pstat.SetSignal(self.signal)
        self.pstat.SetCell(self.GamryCOM.CellOn)

        self.dtaq.Run(True)
        self.log("Initialized CA")


class OCP(Recipe):
    def __init__(
        self,
        init_voltage: float = 0.0,
        tinit=10,
        samplerate=0.1,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.init_voltage = init_voltage
        self.tinit = tinit
        self.samplerate = samplerate

    def initialize_pstat(self) -> None:
        pstat = self.pstat  # Alias
        pstat.SetCtrlMode(self.GamryCOM.PstatMode)
        pstat.SetCell(self.GamryCOM.CellOff)
        pstat.SetIEStability(self.GamryCOM.StabilityNorm)

    def initialize(self) -> None:
        self.signal = GamryObjects.SignalConst.create()
        self.dtaq = GamryObjects.DtaqOcv.create()

        self.event_handler = GamryDtaqEvents(self.dtaq, verbose=self.verbose)
        self.make_event_connection(self.dtaq, self.event_handler)

        self.signal.Init(
            self.pstat,
            self.init_voltage,
            self.tinit,
            self.samplerate,
            self.GamryCOM.PstatMode,
        )

        self.initialize_pstat()

        self.dtaq.Init(self.pstat)
        self.pstat.SetSignal(self.signal)
        # Unlike most other experiemnts, we keep CellOff.
        # This prevents current flow. We are making the OCP measurement with no applied signal
        self.pstat.SetCell(self.GamryCOM.CellOff)

        self.dtaq.Run(True)
        self.log("Initialized OCP")


def _adjust_column_names(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Helper function to adjust the DF names. Will first reset the indices,
    such that the first column corresponds to the "Point" column."""
    df = df.reset_index()  # point column
    # Construct a mapping such that we also rename index->Point.
    new_map = dict({"index": "Point"}, **mapping)
    return df.rename(columns=new_map)
