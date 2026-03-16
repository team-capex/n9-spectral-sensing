import logging
import cv2 as cv
import mmap
import struct
import numpy as np
import socket
import threading

from time import sleep

# https://github.com/off99555/python-mmap-ipc
# TODO check this https://numpy.org/doc/stable/reference/generated/numpy.memmap.html

# older socket server code https://github.com/mfrzr/north_ide/commit/ee414e24c5a8d8e300b564f9833aaf77400d21c8

"""
This should act as an independent server process.
Accepted requests should be register/unregister, shutdown, and maybe some 'alive?' request.
Registered feeds should be constantly polled and placed directly in memory-mapped files.
No image manipulation should occur in this class. Therefore, the mmaps must have a header,
which should include image width, height, and possibly # of channels.
Need some 'ping' test which simply indicates if the server is alive or not... since
we will want to check on north_c9 initialization whether the IDE has already created one.
"""

def send_cmd(cmd, data=None):
    """
    :param bytes cmd:
    :param bytes data:
    :return: A response from the data broker.
    """
    assert len(cmd) == 4
    data = data if data else b''
    assembled_cmd = cmd + data
    assert NorthServer.BUF_LEN >= len(assembled_cmd) >= 4

    try:
        with socket.socket() as sock:
            # connect to NorthServer
            sock.connect(('localhost', 42435))
            sock.send(assembled_cmd)
            ret = sock.recv(4)
        if ret != b'OKAY':
            logging.error(f'Something went wrong communicating with data broker (cmd: {assembled_cmd}, ret: {ret}')
        return ret
    except Exception as e:
        logging.error(f'Error sending cmd {cmd} with data {data} to NorthServer')
        logging.exception(e)
        return b'FAIL'

def try_import_views():
    try:
        import north.views as views
        return True
    except Exception as e:
        logging.error(f'try_import_views EXCEPTION')
        logging.exception(e)
        return False

class NorthServer:
    BUF_LEN = 64
    """
    North Server
    """
    def __init__(self, host="localhost", port=42435, verbose=False):
        assert isinstance(host, str)
        assert isinstance(port, int)
        assert isinstance(verbose, bool)

        self._host = host
        self._port = port
        self._verbose = verbose
        self._server_thread = None
        self._terminate = False

        ### Initialize Exchange Objects ###
        # if we have an IDE:
        # - initialize DataBroker
        # - initialize JoystickBroker
        # no matter what:
        # - initialize VideoProvider
        # - begin serving
        if try_import_views():
            self._has_IDE = True
            self._data_broker = DataBroker(verbose=verbose)
            self._js_broker = JoystickBroker(verbose=verbose)
            if self._verbose:
                logging.info(f'NorthServer: IDE exists. Running all exchanges.')
        else:
            self._has_IDE = False
            logging.warning(f'NorthServer: No IDE exists. Running VideoProvider only.')
        self._vid_provider = VideoProvider(verbose=verbose)
        # with exchange objects initialized we can begin serving
        self._start()

    def __del__(self):
        if self._verbose:
            logging.info(f'shutting down NorthServer')
        self._terminate = True

    def _start(self):
        assert self._server_thread is None
        if self._verbose:
            logging.info(f'booting up NorthServer')
        self._server_thread = threading.Thread(target=self._serve, daemon=True)
        self._server_thread.start()
        self._vid_provider.start()

    def _serve(self):
        ### initialize socket ###
        try:
            self._sock = socket.socket()
            self._sock.bind(("", self._port))
            if self._verbose:
                logging.info(f'NorthServer: bound socket to port {self._port}')
            self._sock.listen(5)
            if self._verbose:
                logging.info('NorthServer: listening for connections...')
        except Exception as e:
            logging.error('NorthServer: Failed to initialize socket (exception below)')
            logging.exception(e)
            raise e
        ### accept connections loop ###
        while not self._terminate:
            conn, addr = self._sock.accept()
            if self._verbose:
                logging.info(f'NorthServer: received connection from {addr}')
            ### server loop ###
            # while True:
            try:
                # receive a command
                buffer = conn.recv(self.BUF_LEN)
                if buffer == b'':
                    continue
                # get cmd arguments from data
                cmd = buffer[:4].decode('ascii')
                data = buffer[4:]
                if self._verbose:
                    logging.info(f'NorthServer: received cmd {cmd} with data {data}')

                # perform some action based on command #
                # simple ping
                if cmd == 'TEST':
                    ret = b'OKAY'

                # video provider commands #
                elif cmd.startswith('V'):
                    ret = self._vid_provider.handle_cmd(cmd, data)

                # data table commands
                elif cmd.startswith('D'):
                    if self._has_IDE:
                        ret = self._data_broker.handle_cmd(cmd, data)
                    else: # We have no attached IDE and cannot handle Data command
                        logging.warning(f'NorthServer: Received data command when no IDE exists.')

                # joystick commands
                elif cmd.startswith('J'):
                    if self._has_IDE:
                        ret = self._js_broker.handle_cmd(cmd, data)
                    elif self._verbose:
                        logging.warning(f'NorthServer: Received joystick command when no IDE exists.')
                else:
                    logging.error(f'NorthServer: Unrecognized command type {cmd[0]} in {cmd}')
                    ret = b'UCMD'

                # send a reply
                conn.send(ret)
            except Exception as e:
                logging.error(f'DataBroker: Error while receiving data (exception below)')
                logging.exception(e)
                conn.send(b'FAIL')
                raise e
            ### end of server loop ###
            conn.close()
            if self._verbose:
                logging.info(f'data broker disconnected from {addr}')
            ### end of subscription cleanup ###
        ### end of connections loop ###

class DataBroker:
    """
    Data Broker
    """
    def __init__(self, verbose=False):
        assert isinstance(verbose, bool)

    def handle_cmd(self, cmd, data=None):
        filename = data.decode('ascii')
        if cmd == 'DOPE':
            ret = self._open_file(filename)
        elif cmd == 'DREF':
            ret = self._refresh(filename)
        else:
            logging.error(f'NorthServer: Unrecognized data command {cmd}')
            ret = b'UCMD'
        return ret

    def _open_file(self, filename):
        import north.views as views
        filepath = views.project().current_proj.path.joinpath(filename)
        if not views.data().open(filepath):
            return b'FAIL'
        else:
            views.refresh_file_view() # might be a new file
            return b'OKAY'

    def _refresh(self, filename):
        import north.views as views
        views.data().refresh(filename)
        return b'OKAY'

class JoystickBroker:
    def __init__(self, verbose=False):
        assert isinstance(verbose, bool)

    def handle_cmd(self, cmd, data=None):
        if cmd == 'JBEG':
            ret = self._begin()
        elif cmd == 'JMOV':
            assert isinstance(data, bytes)
            from north.simulator import Simulator
            js_pos = struct.unpack(f'{len(Simulator.ROBOT_AXES)}i', data)
            ret = self._move(js_pos)
        elif cmd == 'JEND':
            ret = self._end()
        else:
            logging.error(f'JoystickBroker: Unrecognized command {cmd} with data {data}')
            ret = b'UCMD'
        return ret

    def _begin(self):
        import north.views as views
        views.simulator().js_begin()
        return b'OKAY'

    def _move(self, data):
        import north.views as views
        views.simulator().js_move(data)
        return b'OKAY'

    def _end(self):
        import north.views as views
        views.simulator().js_end()
        return b'OKAY'

class VideoProvider:
    """
    Video Provider
    """
    VIDEO_LOOP_DELAY = 0.01
    # CAMERA_START_DELAY = 1.5

    def __init__(self, verbose=False):
        assert isinstance(verbose, bool)

        self._verbose = verbose
        self._cam_thread = None

        self._lock = threading.Lock()
        self._terminate = False
        self._registrations = {}
        self._sources = {}  # [src_id] : VideoCapture
        self._mmaps = {}

    def __del__(self):
        if self._verbose:
            logging.info(f'shutting down VideoProvider')
        # TODO not sure this actually ever executes..
        self._terminate = True
        for src_id in self._sources.keys():
            self._remove_src(src_id)
        del self._sources
        del self._mmaps

    ##################
    # Public methods #
    def start(self):
        assert self._cam_thread is None
        if self._verbose:
            logging.info(f'booting up VideoProvider')
        self._cam_thread = threading.Thread(target=self._poll_cams, daemon=True)
        self._cam_thread.start()

    def handle_cmd(self, cmd, data):
        """
        :param str cmd:
        :param bytes data:
        :return: bytes return code
        """
        assert isinstance(data, bytes)
        assert len(data) == 4
        src_id = struct.unpack('i', data)[0]
        if cmd == 'VREG':
            return self.register(src_id)
        elif cmd == 'VUNR':
            return self.unregister(src_id)
        else:
            logging.error(f'VideoProvider: Unrecognized vision command {cmd}')
            return b'UCMD'

    def register(self, src_id):
        """
        :param int src_id:
        """
        self._lock.acquire()
        if src_id not in self._sources:
            self._sources[src_id] = cv.VideoCapture(src_id)
            try:
                self._refresh_src(src_id)
            except Exception as e:
                logging.error(f'Video Provider encountered exception while registering source {src_id}:')
                # logging.exception(e)
                return b'FAIL'
            self._registrations[src_id] = 1
        else:
            self._registrations[src_id] += 1
        self._lock.release()
        return b'OKAY'

    def unregister(self, src_id):
        """
        :param int src_id:
        """
        self._lock.acquire()
        if src_id not in self._sources:
            logging.error("Tried to unregister pane from unopened source")
            ret = b'FAIL'
        else:
            self._registrations[src_id] -= 1
            if self._registrations[src_id] == 0:
                self._remove_src(src_id)
            ret = b'OKAY'
        self._lock.release()
        return ret

    ###################
    # Private methods #
    def _poll_cams(self):
        while not self._terminate:
            self._lock.acquire()
            for src_id in self._sources.keys():
                self._refresh_src(src_id)
            self._lock.release()
            sleep(self.VIDEO_LOOP_DELAY)
        if self._verbose:
            logging.info(f'video provider terminated polling loop')

    def _refresh_src(self, src_id):
        """
        :param int src_id:
        """
        ret, img = self._sources[src_id].read()
        if not ret:
            Exception(f'No return value for camera feed {src_id} in VideoProvider._refresh_src().')

        head = struct.pack('ii', img.shape[1], img.shape[0])
        if src_id not in self._mmaps:
            channels = 3
            mmap_size = len(head) + (img.size * channels)
            self._mmaps[src_id] = mmap.mmap(-1, mmap_size, f"CAMERAFEED-{src_id}")
            if self._verbose:
                logging.info(f'video provider initialized mmap CAMERAFEED-{src_id}')

        assert src_id in self._mmaps
        self._mmaps[src_id].seek(0)
        self._mmaps[src_id].write(head)
        self._mmaps[src_id].write(img.tobytes())
        self._mmaps[src_id].flush()

    def _remove_src(self, src_id):
        """
        :param int src_id:
        """
        self._sources[src_id].release()
        self._mmaps[src_id].close()
        del self._sources[src_id]
        del self._mmaps[src_id]
        if self._registrations[src_id] > 0:
            logging.error(f'Removed a registered source ({src_id})')
        del self._registrations[src_id]
        if self._verbose:
            logging.info(f'video provider removed source {src_id}')
