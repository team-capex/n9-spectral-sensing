GRIPPER = 0
ELBOW = 1
SHOULDER = 2
Z_AXIS = 3

N_MOTORS = HVO_CHANNELS = GRIPPER_FINGERS_HVO = 8  # Start of digital outputs, relays, pneumatics (high voltage outputs)
CLAMP_HVO = 9

N_OUTPUTS = 16
PUMPS = N_OUTPUTS + N_MOTORS
N_PUMPS = 6
LAST_PUMP_AXIS = PUMPS + 2 * N_PUMPS - 1
# LINE_NUM = LAST_PUMP_AXIS + 1
# N_AXES = LINE_NUM + 1
N_AXES = LAST_PUMP_AXIS + 1

# graspers
GRIPPER_FINGERS = 0
PIPETTE_PROBE = 1
CURRENT_TOOL = 2

CLAMP = 7 # TODO this shouldn't exist

GRASP_TOL = 0.001  # m

# ?: bool
# i: int
# B: unsigned byte
# f: float
STEP_FMT = '?iBB?' + 'f'*N_AXES # kf(?), task(i), mv_event(B), tool(B), check pipe(?), axis positions (f*)

GRASP_TOL = 0.001 # m

import logging

def dist (p, q):
    import math
    return math.sqrt(sum((px - qx) ** 2.0 for px, qx in zip(p, q)))

def launch_north_server():
    try:
        import socket
        import struct
        with socket.socket() as sock:
            sock.connect(('localhost', 42435)) # check data server exists?
            # sock.send(struct.pack('4si', b'TEST', 0))
        logging.info('tried to launch NorthServer but it already exists.')
    except ConnectionRefusedError: # data server does not exist; initialize it
        from north_c9.n9_server import NorthServer
        NorthServer()
        logging.info('launched NorthServer.')

# imports last to avoid cyclical importing (some of the below files depend on the constants above)
import north_c9.n9_kinematics
from north_c9.north_c9 import NorthC9, ADS1115
from north_c9.north_tasks import Scheduler
from north_c9.n9_cam import NorthCamera
from north_c9.n9_data import NorthData