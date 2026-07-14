from typing import Union
import time
from contextlib import contextmanager
from .gamry_objects import GamryObjects, GamryCOMObject, create_object, get_gamry_module


class PstatManager:
    def __init__(self, pstat_com: Union[str, GamryCOMObject] = GamryObjects.PC5Pstat):
        self._has_objects = False
        self.pstat = None
        self.pstat_name = pstat_com
        self.GamryCOM = get_gamry_module()

    def has_pstat(self) -> bool:
        return self.pstat is not None

    def make_pstat(self) -> None:
        if self.pstat is None:
            # Guard clause that we don't accidentally delete
            # an old pstat which isn't closed.
            self.pstat = create_object(self.pstat_name)

    @contextmanager
    def with_device(self, device):
        """Context manager, which constructs the pstat object,
        and ensures it is initialized onto a device and opened.
        Will close the pstat connection once the context is exited."""
        self.make_pstat()
        self._initialize(device)
        try:
            yield self.pstat
        finally:
            self._teardown()

    def _initialize(self, device):
        self.pstat.Init(device)
        self.pstat.Open()

    def _teardown(self) -> None:
        """Ensure the potentiostat is turned off and the connection is
        terminated."""
        # TODO: Check if pstat is opened, and if it is, close it.
        # XXX: Do we always turn off the cell?
        self.pstat.SetCell(self.GamryCOM.CellOff)
        time.sleep(1)
        self.pstat.Close()
        self.pstat = None
