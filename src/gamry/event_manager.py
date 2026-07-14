from typing import List, Dict, Any
import time
from math import log10
import numpy as np
import pandas as pd


class EventHandler:
    def __init__(self, verbose=False):
        self.active = True
        self.verbose = verbose

    def done(self) -> None:
        """Indicate that the event handler is finished measuring."""
        self.active = False

    def activate(self) -> None:
        """Indicate the event handler is active."""
        self.active = True

    def get_data(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_num_datapoints(self) -> int:
        raise NotImplementedError("Subclass needs to implement this.")

    def log(self, *args, **kwargs) -> None:
        if self.verbose:
            print(*args, **kwargs)


class GamryReadZEvents(EventHandler):
    def __init__(
        self,
        readz,
        maxpoints: int,
        ac: float,
        initial_freq: float,
        loginc: float,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.readz = readz
        self.maxpoints = maxpoints
        self.ac = ac
        self.loginc = loginc
        self.initial_freq = initial_freq
        self.acquired_points = []
        self.starttime = time.perf_counter()

        self.point = 0
        self.passes = 0
        # Container for measurements
        self.datapoints: List[Dict[str, Any]] = []

    def get_num_datapoints(self) -> int:
        return len(self.datapoints)

    def cook(self):
        # unlike other experiments, cook gets the lissajous data points.
        # Zmod, Zphz, etc must be collected after DataDone is fired
        count = 1
        while count > 0:
            count, points = self.readz.Cook(1024)
            self.log(f"Count: {count}, points: {points}")
            # TODO: Do these points need to be integrated with "datapoints"?
            # Unclear what data is available here.
            self.acquired_points.extend(zip(*points))

    def _IGamryReadZEvents_OnDataAvailable(self, this):
        """Cooks lissajous data points when DataAvalible event is fired"""
        self.log("Called OnDataAvailable")
        self.cook()

    @property
    def freq(self):
        return 10 ** (log10(self.initial_freq) + (self.point * self.loginc))

    def _IGamryReadZEvents_OnDataDone(self, this, status1):
        """The bread and butter of ReadZ.
        All readz.measure() is called from here after the very first frequency point"""
        self.log("In data done...")
        status = self.readz.StatusMessage()  # string based message about data point

        self.log(str(np.around(self.freq, 3)), "Hz:", status)

        datatime = time.perf_counter() - self.starttime

        if status1 == 0:
            # data acceptable, ie an impedance value was able to be obtained.
            # Does not indicate quality
            data = {
                "Point": self.point,
                "Time": datatime,
                "Freq": self.readz.Zfreq(),
                "Zreal": self.readz.Zreal(),
                "Zimag": self.readz.Zimag(),
                "Zsig": self.readz.Zsig(),
                "Zmod": self.readz.Zmod(),
                "Zphz": self.readz.Zphz(),
                "Idc": self.readz.Idc(),
                "Vdc": self.readz.Vdc(),
                "IERange": self.readz.IERange(),
            }
            self.datapoints.append(data)

            self.point += 1
            freq = 10 ** (log10(self.initial_freq) + (self.point * self.loginc))
            if self.point > self.maxpoints:
                # we have acquired all data points over specified freq range.
                # Connection manager & recipe will ensure things are properly shut down.
                self.done()
                return
            else:  # still more data points to be collected. Measure impednace at next point
                self.measure(freq)
                return

        if status1 == 1:  # impedance value could not be determined.
            if self.passes > 10:
                # Move on to next point
                self.passes = 0
                self.point += 1
                self.measure_current()
            else:
                # Retry current
                self.passes += 1
                self.measure_current()

        else:
            # impedance value could not be determined. Catch all
            # move to next frequency point
            self.point += 1
            self.measure_current()

    def measure(self, freq: float) -> None:
        self.readz.Measure(freq, self.ac)

    def measure_current(self) -> None:
        self.measure(self.freq)

    def measure_first(self) -> None:
        self.measure(self.initial_freq)

    def reset(self) -> None:
        """Reset internal variables, prepare for a new experiment."""
        self.datapoints.clear()
        self.point = 0
        self.passes = 0
        self.starttime = time.perf_counter()

    def get_data(self) -> pd.DataFrame:
        points = self.datapoints
        if not points:
            # No data
            return pd.DataFrame()
        # Ensure the order of the columns is retained as specified in the event manager.
        columns = list(points[0].keys())
        return pd.DataFrame(points, columns=columns)


class GamryDtaqEvents(EventHandler):
    def __init__(self, dtaq, **kwargs):
        super().__init__(**kwargs)
        self.dtaq = dtaq
        self.acquired_points = []
        self.log("Made GamryDtaqEvents", dtaq)

    def get_num_datapoints(self) -> int:
        return len(self.acquired_points)

    def cook(self):
        if self.dtaq is None:
            raise RuntimeError("No dtaq has been set.")

        count = 1
        while count > 0:
            count, points = self.dtaq.Cook(1024)
            # The columns exposed by GamryDtaq.Cook vary by dtaq and are
            # documented in the Toolkit Reference Manual.
            self.acquired_points.extend(zip(*points))

    def _IGamryDtaqEvents_OnDataAvailable(self, this):
        self.log("Called OnDataAvailable")
        self.cook()

    def _IGamryDtaqEvents_OnDataDone(self, this):
        self.log("made it to data done")
        self.cook()  # a final cook
        self.done()
        time.sleep(1.0)

    def get_data(self) -> pd.DataFrame:
        return pd.DataFrame(self.acquired_points)
