import comtypes


class GamryCOMError(Exception):
    """Generic COM Gamry Error"""


def gamry_error_decoder(e):

    if isinstance(e, comtypes.COMError):
        hresult = 2**32 + e.args[0]
        if hresult & 0x20000000:
            return GamryCOMError("0x{0:08x}: {1}".format(2**32 + e.args[0], e.args[1]))
    return e
