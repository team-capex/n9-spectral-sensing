import logging
import inspect
import socket
import struct
import mmap
import os
import json
import numpy as np
import cv2 as cv

from typing import Callable
from PIL import Image, ImageTk
from pathlib import Path
from time import sleep

from north.north_project import Project
from north_c9.north_util import VideoUtils, get_current_timestamp

class NorthCamera:
    def __init__(self, source=None, pane=None):
        """
        :param int source:
        :param int pane:
        """
        if not isinstance(source, int) and not isinstance(pane, int):
            raise ValueError("Must specify either a source or pane (int) to initialize a camera.")

        # TODO get project path when not in IDE
        self._proj_path = Path(os.getcwd())
        self._settings = None

        cfg = None
        if isinstance(pane, int):
            proj = Project(self._proj_path)
            source = proj.get_visionpane(pane)['src']
            cfg = proj.get_visionpane(pane)['cfg']
        self._source_id = source
        self._config_id = cfg
        self._pane_id = pane

        # register the camera feed with video provider
        from north_c9 import launch_north_server
        launch_north_server() # creates data broker iff it doesn't exist
        cmd = struct.pack('4si', b'VREG', source)
        with socket.socket() as sock:
            sock.connect(('localhost', 42435))
            sock.send(cmd)
            ret = sock.recv(4)
            if ret == b'FAIL':
                raise ValueError(f'Desired camera feed ({source}) does not exist, or is in use.')

    def __del__(self):
        # unregister the camera feed
        cmd = struct.pack('4si', b'VUNR', self._source_id)
        with socket.socket() as sock:
            sock.connect(('localhost', 42435))
            sock.send(cmd)
            _ = sock.recv(4)

    def capture(self):
        """
        :return: The captured image (numpy.ndarray).
        """
        try:
            imgsize = 0
            # while camera is booting up the image size will be zero
            while imgsize == 0:
                headsize = struct.calcsize('ii')
                head = mmap.mmap(-1, headsize, f"CAMERAFEED-{self._source_id}")
                head.seek(0)
                w, h = struct.unpack('ii', head.read(headsize))
                head.close()
                shape = (h, w, 3)
                imgsize = np.prod(shape)
                if imgsize == 0: # don't poll too often..
                    sleep(0.01)
            # we have ensured camera is up, now..
            # get the current image from mmap
            mm = mmap.mmap(-1, headsize+imgsize, f"CAMERAFEED-{self._source_id}")
            mm.seek(headsize)
            buf = mm.read(imgsize)
            src_frame = np.frombuffer(buf, dtype=np.uint8).reshape(shape)
            mm.close()

            # apply any crop if necessary
            settings = Project(self._proj_path).get_visioncfg(self._config_id)['settings']
            if settings is not None and settings['crop']['enabled']:
                crop_set = settings['crop']
                # numpy arrays are height-first and width-second
                cropped = src_frame[
                            crop_set['start_y']:crop_set['end_y'],
                            crop_set['start_x']:crop_set['end_x']
                          ]
                if cropped.shape[0] < 1 or cropped.shape[1] < 1: # empty crop
                    logging.warning("Cropping settings resulted in empty crop. Capturing full image.")
                    return src_frame
                else:
                    return cropped
            else: # no cropping
                return src_frame
        except Exception as e:
            logging.error("Error in NorthCamera.capture():")
            logging.exception(e)

    def filter(self, image=None, func=None, pane=None):
        """
        :param np.ndarray image:
        :param Callable func:
        :param int pane:
        :return: The filtered image.
        """
        if not isinstance(image, np.ndarray):
            image = self.capture()
        if isinstance(func, Callable):
            output = func(image)
            if isinstance(output, np.ndarray):
                return output
            else:
                logging.error(f'filter(): Supplied function must return numpy ndarray')
                logging.error( 'filter(): Returning unprocessed image...')
                return image
        else:
            if not isinstance(pane, int):
                if self._pane_id is not None:
                    pane = self._pane_id
                else:
                    logging.error(f'filter(): Cannot filter without supplied func, cfg_id parameter, or a preset pane.')
                    logging.error( 'filter(): Returning unprocessed image...')
                    return image
            proj = Project(self._proj_path)
            cfg = proj.get_visioncfg(pane)
            filter = cfg['filter']
            settings = cfg['settings']
            try:
                output = VideoUtils.get_output_frame(filter, image, settings)
                return output
            except Exception as e:
                logging.error('filter(): Encountered exception during filtering:')
                logging.exception(e)
                logging.error('filter(): Returning unprocessed image...')
                return image

    def show(self, image):
        """
        :param np.ndarray image:
        """
        # TODO switch to pyplot
        #from matplotlib import pyplot as plt
        #plt.imshow(image)
        cv.namedWindow("Captured Image", cv.WINDOW_AUTOSIZE)
        cv.imshow("Captured Image", image)
        cv.waitKey(0)

    def save(self, image, filename=None):
        """
        :param np.ndarray image: Image to save.
        :return: Filepath of the saved image.
        """
        if not filename:
            filename = f'capture_{get_current_timestamp()}'
        return save_capture(image, filename, proj_path=self._proj_path)

    def display(self):
        raise NotImplementedError()

# functions
def get_captures_path(proj_path=None) -> Path:
    """
    :param Path proj_path: If None, will assume the script is being called in project directory.
    :return: The path where captures are saved.
    """
    if proj_path == None:
        # TODO: default to user_data/captures on None proj_path, in case no project open...
        raise NotImplementedError()
    return proj_path.joinpath('captures')

def save_capture(image, filename,
                 proj_path = None,
                 no_duplicates = True,
                 format='png') -> Path:
    """
    :param image:
    :param str filename:
    :param Path proj_path:
    :param bool no_duplicates:
    :param str format:
    :return: Filepath of the saved capture, or None if not successfully saved
    """
    assert type(image) in [np.ndarray, ImageTk.PhotoImage]
    # ensure captures directory exists
    if not Path.exists(get_captures_path(proj_path)):
        Path.mkdir(get_captures_path(proj_path))

    filepath = get_captures_path(proj_path).joinpath(f'{filename}.{format}')

    if no_duplicates:
        i = 2
        while Path.exists(filepath):
            filepath = get_captures_path(proj_path).joinpath(f'{filename}_{i}.{format}')
            i += 1
    else:
        logging.warning("TODO: save_capture when no_duplicates = False")

    # save the capture
    if isinstance(image, np.ndarray):
        # cv images are BGR, PIL images are RGB
        img_pil = Image.fromarray(cv.cvtColor(image, cv.COLOR_BGR2RGB))
    elif isinstance(image, ImageTk.PhotoImage):
        img_pil = ImageTk.getimage(image)
    img_pil.save(filepath, format=format)

    print(f'Saved capture: {filepath}')
    logging.info(f'Saved capture: {filepath}')
    return filepath
