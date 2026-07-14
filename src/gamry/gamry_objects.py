from typing import Union
from dataclasses import dataclass
import comtypes.client as client


class GamryCOMObject:
    def __init__(self, name: str):
        self.name = self._as_full_name(name)

    def create(self):
        """Create the COM object."""
        return client.CreateObject(self.name)

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def _as_full_name(name: str):
        """Ensure the GamryCOM name is the full name, including
        the 'GamryCOM.' prefix."""
        if name.startswith("GamryCOM."):
            return name
        return f"GamryCOM.{name}"


@dataclass
class GamryObjects:
    """Dataclass containing a list of the available Gamry COM objects which can be
    created. Each entry is a GamryCOMObject object."""

    DtaqChrono = GamryCOMObject("GamryDtaqChrono")
    DtaqRcv = GamryCOMObject("GamryDtaqRcv")
    DtaqOcv = GamryCOMObject("GamryDtaqOcv")
    PC5Pstat = GamryCOMObject("GamryPC5Pstat")
    # PC6Pstat = GamryCOMObject("GamryPC6Pstat")
    DeviceList = GamryCOMObject("GamryDeviceList")
    SignalDstep = GamryCOMObject("GamrySignalDstep")
    SignalRupdn = GamryCOMObject("GamrySignalRupdn")
    SignalConst = GamryCOMObject("GamrySignalConst")
    ReadZ = GamryCOMObject("GamryReadZ")


def create_object(obj: Union[str, GamryCOMObject]):
    """Instantiate a GamryCOM object, either from the name as a string or a
    GamryCOMObject type."""
    if isinstance(obj, GamryCOMObject):
        return obj.create()
    return client.CreateObject(obj)


_GAMRY_MODULE = None


def get_gamry_module():
    global _GAMRY_MODULE
    if _GAMRY_MODULE is None:
        # TODO: Make this thing more stable...
        # Alternatively this can be pointed to
        # 'C:\Program Files (x86)\Gamry Instruments\Framework\GamryCom.exe'
        _GAMRY_MODULE = client.GetModule(["{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}", 1, 0])
    return _GAMRY_MODULE
