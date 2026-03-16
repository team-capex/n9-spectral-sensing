import logging
import struct
import math
import random  # for simulated response data
import threading
import sys
import os
import json
import keyboard

from sys import platform
from abc import ABC, abstractmethod, abstractproperty
from pathlib import Path
from typing import Callable
from time import sleep, time, perf_counter
from datetime import datetime
from inputs import get_gamepad, UnpluggedError  # the keyboard interface from 'inputs' module interferes with Thonny
from inspect import getframeinfo, stack, isgeneratorfunction

if platform == "win32":
    try:
        from ftdi_serial import Serial, SerialReadTimeoutException
    except Exception:
        logging.warning('north_c9: Could not initialize FTDI Serial package. Robot integration may be affected.')
import serial

from north.north_project import Project  # this is here to avoid import loops from other modules that reference the API
import north_c9.n9_kinematics as n9

class AxisState:
    OFF = 0
    HOMING = 1
    HOME_COMPLETE = 2
    VELOCITY = 3
    VELOCITY_TARGET_REACHED = 4
    MOVE_ABS = 5
    MOVE_REL = 6
    MOVE_COMPLETE = 7
    STEP_DIR = 8
    ERROR = 9


class CmdToken:

    def __init__(self, status_func, value, axis=None, delay=0.0, sim=False):
        self.wait_func = status_func
        self.wait_value = value
        self.wait_axis = axis
        self.return_value = None
        self.delay = delay
        self.sim = sim

    def is_done(self):
        if self.wait_axis is not None:
            result = self.wait_func(self.wait_axis)
        else:
            result = self.wait_func()

        if type(result) == tuple:  # this only handles the case for 2. todo: generalize
            self.return_value = result[1:]
            return result[0] == self.wait_value  # result[0]

        return result == self.wait_value

    def wait(self):
        sleep(self.delay)
        while not self.is_done():
            sleep(self.delay)
        sleep(self.delay)


# TODO: consider simplifying cmdtokens with something similar to below: current problem was
# that NorthC9.get_axis_status doesn't have a "self", isn't tied to an instance of NorthC9
# class AxisCmdToken (CmdToken):
#     def __init__(self, axis, wait=True):
#         super().__init__(NorthC9.get_axis_status, AxisState.MOVE_COMPLETE, axis=axis, wait=wait)
#
# class RobotCmdToken (CmdToken):  # consider renaming to N9CmdToken
#     def __init__(self, wait=True):
#         super().__init__(NorthC9.get_robot_status, NorthC9.FREE, wait=wait)
#
# class SequenceCmdToken (CmdToken):  # consider renaming to N9CmdToken
#     def __init__(self, wait=True):
#         super().__init__(NorthC9.get_sequence_status, NorthC9.FREE, wait=wait)

class ADS1115:  # todo: refactor so as not to have to include this in main script
    # Values from ADS115 datasheet here: http://www.ti.com/lit/ds/symlink/ads1115.pdf

    # start/stop
    STOP_READ = 0
    START_READ = 1

    # mux
    AIN0_AIN1 = 0
    AIN0_AIN3 = 1
    AIN1_AIN3 = 2
    AIN2_AIN3 = 3
    AIN0_GND = 4
    AIN1_GND = 5
    AIN2_GND = 6
    AIN3_GND = 7

    # range
    V6_144 = 0
    V4_096 = 1
    V2_048 = 2
    V1_024 = 3
    V0_512 = 4
    V0_256 = 5

    # mode
    CONTINUOUS = 0
    ONE_SHOT = 1

    # data rates
    SPS8 = 0
    SPS16 = 1
    SPS32 = 2
    SPS64 = 3
    SPS128 = 4
    SPS250 = 5
    SPS475 = 6
    SPS860 = 7


class NorthC9:
    # TODO: Right now, this assumes all C9's are on the same network. Should be made more flexible
    # TODO: Change how serial is set up.. i.e. more configurable, from constructor, etc

    FREE = 0
    BUSY = 1

    GRIPPER = 0
    ELBOW = 1
    SHOULDER = 2
    Z_AXIS = 3
    CAROUSEL_ROT = 4
    CAROUSEL_Z = 5

    X = 0
    Y = 1
    Z = 2

    GRIPPER_DELAY = 0.2  # time it takes to open/close grippers
    CLAMP_DELAY = 0.3  # time it takes to open/close clamp

    DEFAULT_VEL = 5000
    DEFAULT_ACCEL = 50000

    # should these reference something external?
    GRIPPER_COUNTS_PER_REV = n9.GRIPPER_COUNTS_PER_REV
    ELBOW_COUNTS_PER_REV = n9.ELBOW_COUNTS_PER_REV
    SHOULDER_COUNTS_PER_REV = n9.SHOULDER_COUNTS_PER_REV
    Z_AXIS_COUNTS_PER_MM = n9.Z_AXIS_COUNTS_PER_MM

    ELBOW_OFFSET = n9.ELBOW_OFFSET
    SHOULDER_OFFSET = n9.SHOULDER_OFFSET
    Z_AXIS_OFFSET = n9.Z_AXIS_OFFSET  # test grippers - TODO: MAKE THIS GENERIC, TOOL IK ETC.

    ELBOW_MAX_COUNTS = n9.ELBOW_MAX_COUNTS
    SHOULDER_MAX_COUNTS = n9.SHOULDER_MAX_COUNTS
    Z_AXIS_MAX_COUNTS = n9.Z_AXIS_MAX_COUNTS

    SHOULDER_CENTER = n9.SHOULDER_CENTER
    SHOULDER_OUT = n9.SHOULDER_OUT

    POS_X = 0
    POS_Y = math.pi / 2
    NEG_X = math.pi
    NEG_Y = -math.pi / 2

    DEFAULT_TOOL_ORIENTATION = POS_X

    PUMP_VALVE_LEFT = 0
    PUMP_VALVE_RIGHT = 1
    PUMP_VALVE_CENTER = 2

    TEMP_HEAT = 0
    TEMP_COOL = 1
    TEMP_HEAT_COOL = 2
    TEMP_COOL_HEAT = 3

    SERIAL_PUMP_DELAY = 0.03  # small delay between requests to pumps because they operate at 9600 baud

    maximum_pos = [63000, 63000, 63000, 63000]  # TODO: set these accurately and intelligently

    def __init__(self, addr, network=None, network_serial=None, experiment_log=False, verbose=False):
        parent_path = Path(os.getcwd())

        self.verbose = verbose
        self.exp_log_file = None

        self._sim = bool((type(addr) == str and addr.lower() == 'sim')
                         or '-c9_sim' in sys.argv)

        self.proj = None
        try:
            # try to load first project file from project directory of calling script
            proj_file = open(parent_path.joinpath(parent_path.stem + '.nproj'))
            self.proj = json.load(proj_file)
        except (FileNotFoundError, IndexError):
            self.log("Warning: Failed to load project settings, project specific commands may not function as expected")

        self.exp_logging = experiment_log
        if self.proj is not None and self.exp_logging:
            self.exp_log_file = open(parent_path.joinpath('experiment_log.txt'), 'w')

        if not self.exp_log_file:
            pass
            # logging.warning('NorthC9: Did not initialize self.ledger')
            # logging.warning(F'self.proj: {self.proj} self.sim: {self.sim} self.exp_log: {self.exp_logging} parent_path: {parent_path}')

        # config pump settings from project data
        if self.proj is None:
            self.pumps = {i: {'pos': 0, 'volume': 1.0} for i in range(15)}
        else:
            self.pumps = {i: {'pos': 0,
                              'volume': float(self.proj['pumps']['Pump ' + str(i)]['volume'])
                              } for i in range(len(self.proj['pumps']))}
            if len(self.proj['pumps']) != 15:
                # print('[INFO] Non-default number of pumps ({}) in project "{}"'
                #       .format(len(self.proj.pumps), self.proj.name))
                pass

        # config sim inputs from project data
        self.sim_inputs = {}
        if self.proj is not None and self.sim:
            try:
                self.sim_inputs = self.proj['sim_inputs']
            except KeyError:
                pass

        if self.sim:
            from north.simulator import Simulator
            network = VirtualControllerNetwork(self)
            self._simulator = Simulator(0.01, sim_inputs=self.sim_inputs) # TODO set this programmatically, not by constant (see simview.dt)
        elif platform == "win32": # NOT self.sim
            if isinstance(network, Serial):
                network = FTDISerialControllerNetwork(network=network)
            elif network is None:
                network = FTDISerialControllerNetwork(network_serial=network_serial)
            assert isinstance(network, FTDISerialControllerNetwork)
            self._simulator = None
        else: #not sim, not windows:
            if isinstance(network, serial.Serial):
                network = GenericSerialControllerNetwork(network=network)
            elif network is None:
                network = GenericSerialControllerNetwork(network_serial=network_serial)
            assert isinstance(network, GenericSerialControllerNetwork)
            self._simulator = None
        self.network = network
        assert isinstance(self.network, BaseControllerNetwork) # interface enforcement

        if not self.sim:
            if 'quickstop_enabled' not in self.network.__dict__:
                self.network.__dict__['quickstop_enabled'] = True
                keyboard.add_hotkey('ctrl+alt+=', self.quick_stop)

        self._sending = False
        self._stop_requested = False

        try:
            self.c9_addr = int(addr)
        except ValueError:
            try:
                self.c9_addr = ord(addr)
            except TypeError: # addr = 'sim'
                logging.error(f'north_c9: c9_addr could not be set to {addr} ({type(addr)})')
                self.c9_addr = ord('A')

        self.default_vel = self.DEFAULT_VEL
        self.default_accel = self.DEFAULT_ACCEL
        self.safe_height = 0

        self.prev_cmd_token = None

        self.js_vel = [0, 0, 0, 0]
        self.key_speed = 1000  # counts/sec when key depressed

        self.err_cnt = 0

        self.version = 0.05 #june_9_2021

        self._scheduler = None

        # benchmarking stuff #
        self._benchmarks = {
            "num_send": 0,
            "first_send": -1.0,
            "last_send": -1.0,
            # time aggregates
            "agg_time": 0.0,
            "agg_c9": 0.0,
            "agg_comm": 0.0,
            "agg_calc": 0.0,
            "agg_stat": 0.0
        }

        from north_c9 import launch_north_server
        launch_north_server()

    def __del__(self):
        # TODO this never really executes except at IDE shutdown
        if self.sim and self.exp_log_file: # todo: remove 'and self.ledger'
            self.exp_log_file.close()

    @property
    def current_time(self):
        if isinstance(self.network, BaseControllerNetwork):
            return self.network.time
        else:
            logging.error(f'NorthC9: current_time accessed before network initialization.')
            return 0.0

    @property
    def sim(self):
        return self._sim
    
    @property
    def has_scheduler(self):
        return self._scheduler is not None

    @property
    def scheduler(self):
        return self._scheduler

    @property
    def has_simulator(self):
        return self._simulator is not None

    @property
    def simulator(self):
        return self._simulator

    def delay(self, sec):
        if self.sim:
            self.send_packet('DLAY', [int(sec*1000)])
            return
        sleep(sec)

    def log(self, *args):
        if self.verbose:
            print(*args)

    """ # TODO this may be giving some out-dated metrics (need to revisit where benchmarks are aggregated)
    def bench(self): # TODO should this stay public, become private, or be (re)moved?
        send_time = float(self._benchmarks["agg_comm"]+self._benchmarks["agg_calc"])
        print(f'C9 runtime:               {"%.5f"%(self._benchmarks["last_send"]-self._benchmarks["first_send"])}s')
        print(f'packets sent:             {self._benchmarks["num_send"]} packets')
        print(f'send_packet time:         {"%.5f"%send_time}s')
        if send_time > 0.0: # zero send time doesn't really need listed sub-categories anyhow!
            print(f'  communication time:     {"%.5f"%(self._benchmarks["agg_comm"])}s ({"%.2f"%(self._benchmarks["agg_comm"]/send_time)}%)')
            print(f'  calculations time:      {"%.5f"%(self._benchmarks["agg_calc"])}s ({"%.2f"%(self._benchmarks["agg_calc"]/send_time)}%)')
            print(f'- - - - - - - - - - - - - - ')
            print(f'  status time:            {"%.5f" % (self._benchmarks["agg_stat"])}s ({"%.2f"%(self._benchmarks["agg_stat"]/send_time)}%)')
        print(f'time outside send_packet: {"%.5f" % (self._benchmarks["agg_c9"])}s')
        if self.has_simulator:
            self._simulator.bench()
    """

    def send_packet(self, command, args_list =[], broadcast=False, stop_request=False, wait=True) -> [int]:
        self._benchmarks["num_send"] += 1

        if self._benchmarks["last_send"] >= 0.0: # -1.0 on first runthrough
            self._benchmarks["agg_c9"] += perf_counter()-self._benchmarks["last_send"]
        else:
            self._benchmarks["first_send"] = perf_counter()

        # assemble packet:
        assemb_start = perf_counter()
        request_buffer = [command]
        for arg in args_list:
            request_buffer += [str(arg)]
        self.exp_log(chr(self.c9_addr) + ' ' + ' '.join(request_buffer), send=True)

        if broadcast:
            addr = b'\x00'
        else:
            addr = bytes([self.c9_addr])
        expect_response = addr != b'\x00'
        request_bytes = addr \
                        + b'\x20' \
                        + ' '.join(request_buffer).encode(encoding='charmap')
        request_bytes += b'\x20'
        if self.sim: # insert wait bool at head of request iff simming
            request_bytes = (b'1' if wait else b'0') + request_bytes
        self._benchmarks["agg_calc"] += perf_counter()-assemb_start

        if self._stop_requested and not stop_request:
            sleep(1.0)
            sys.exit()

        # send packet and get response
        self._sending = True
        self.log("Sent", request_bytes)

        try:
            comm_start = perf_counter()
            response_bytes = self.network.send(request_bytes, expect_response=expect_response)
            self._benchmarks["agg_comm"] += perf_counter()-comm_start
        # except SerialReadTimeoutException as e: # doesn't work when can't import Serial
        except Exception as e:
            self._sending = False
            logging.exception(e)
            raise TimeoutError ("Communication with the controller timed out...")
        self._sending = False

        calc_start = perf_counter()
        self.log("Received", response_bytes)
        self.exp_log(response_bytes.decode('charmap'), send=False)

        response_args = None
        if expect_response:
            response_terms = response_bytes.split(b' ')
            response_cmd = response_terms[1]
            response_args = response_terms[2:-1]
            if response_cmd == b'BUFF':
                response_data = response_bytes[6:-1]
                response_args = [response_data]
                # for i in range(0, len(response_data), 2):
                #     data_point = response_data[i:i+2]
                #     response_args += [int.from_bytes(data_point, byteorder='big')]
            else:
                response_args = [int(arg.decode()) for arg in response_args]

            if response_cmd == b'ERR!':
                print("Received", response_bytes)
                raise RuntimeError(C9Errors(response_args[0], response_args[1]))
            self._benchmarks["agg_calc"] += perf_counter()-calc_start

        self._benchmarks["last_send"] = perf_counter()
        return response_args

    def exp_log(self, msg, send=False):
        if not self.exp_logging:
            return

        if send:
            send_char = 'S'
        else:
            send_char = 'R'

        self.exp_log_file.write(send_char + ' ' + str(time()) + ' ' + msg + "\n")
        self.exp_log_file.flush()

    def tag(self, *args):
        self.exp_log('Z TAG ' + ' '.join([str(i) for i in args]))

    def get_info(self):
        # TODO: handle floating point FW version
        args = self.send_packet('INFO')
        print("Connected to C9 at address", self.c9_addr)
        self.log("Firmware Version:", args[0])

    def get_axis_status(self, axis):
        bench = perf_counter()
        args = self.send_packet('AXST', [axis])
        self._benchmarks["agg_stat"] += perf_counter() - bench
        return args[0]

    def get_sequence_status(self):
        bench = perf_counter()
        args = self.send_packet('SQST')
        self._benchmarks["agg_stat"] += perf_counter() - bench
        return args[0]

    def get_robot_status(self):
        bench = perf_counter()
        args = self.send_packet('ROST')
        self._benchmarks["agg_stat"] += perf_counter() - bench
        return args[0]

    def _dry_run_func_est_time(self, func):
        """
        :param func: Function which (presumably) has axis simulation calls.
        :return: Floating-pt time estimate.
        """
        assert isinstance(func, Callable)
        assert self.has_simulator
        self.simulator.start_dryrun()
        # run the function and calculate the added time
        time_pre = self.current_time
        try:
            if isgeneratorfunction(func):
                next(func())
            else:
                func()  # TODO: support args
        except Exception as e:
            logging.error('NorthC9: exception while estimating function time (below):')
            logging.exception(e)
        time_post = self.current_time
        # end the dry run (restore the simulation)
        self.simulator.end_dryrun()
        return time_post - time_pre

    def get_time_est(self, task):
        """
        :param task: Task or Function which (presumably) has axis simulation calls.
        :return: Floating-pt time estimate.
        """
        from north_c9.north_tasks import Task
        assert isinstance(task, Task) or isinstance(task, Callable)
        name = task.name if isinstance(task, Task) else task.__name__
        func = task.func if isinstance(task, Task) else task
        estimate = self._dry_run_func_est_time(func)
        print(f"Estimated time for '{name}' is {estimate}s")
        return estimate

    def quick_stop(self):
        self._stop_requested = True
        print('waiting to send stop request')
        while self._sending:
            pass
        print('sending stop request')
        self.send_packet('QSTP', broadcast=True, stop_request=True)
        print('Quick stop active, home robot before continuing, exiting...')
        self._stop_requested = False

    ######################################
    ##                                  ##
    ##             HOMING               ##
    ##                                  ##
    ######################################

    def home_axis(self, axis, wait=True):
        self.log("Homing axis", axis)
        self.send_packet('HOAX', [axis], wait=wait)
        return self.new_cmd_token(self.get_axis_status, AxisState.HOME_COMPLETE, axis, wait)

    def home_robot(self, wait=True):
        self.log("Homing robot")
        self.send_packet('HORO', wait=wait)
        return self.new_cmd_token(self.get_sequence_status, self.FREE, wait=wait)

    def get_home_offset(self, axis):
        args = self.send_packet('GHOO', [axis])
        self.log("Home offset for axis", axis, "is", args[0])
        return args[0]

    def set_home_offset(self, axis, offset):
        self.send_packet('SHOO', [axis, offset])
        self.log("Set home offset for axis", axis, "to", offset)

    def home_OL_stepper(self, axis, home_length):
        # TODO: support wait=False
        pos = self.get_axis_position(axis)
        self.move_axis(axis, pos - home_length, vel=1000, accel=50000)
        self.home_axis(axis)
        self.delay(1)

    def home_CL_stepper(self, axis):
        # TODO: support wait=False
        timeout = 3
        pos = self.get_axis_position(axis)
        time_start = time()
        move = self.move_axis(axis, pos + 1100, vel=1000, accel=50000, wait=False)
        while time() - time_start < timeout:
            if move.is_done():
                break
        self.home_axis(axis)

    def home_carousel(self):
        # TODO: wait logic
        self.log("Homing carousel")
        self.home_axis(self.CAROUSEL_Z)
        self.home_axis(self.CAROUSEL_ROT)

    ######################################
    ##                                  ##
    ##             MOVING               ##
    ##                                  ##
    ######################################

    def move_axis(self, axis, cts, vel=None, accel=None, wait=True):
        pos = int(cts)
        if vel is None:
            vel = self.default_vel
        if accel is None:
            accel = self.default_accel
        # if 0 <= axis <= 3 and pos > self.maximum_pos[axis]:
        # pos = self.maximum_pos[axis]
        self.log("Moving axis", axis, "to", pos)
        self.send_packet('MOAX', [axis, pos, vel, accel], wait=wait)
        return self.new_cmd_token(self.get_axis_status, AxisState.MOVE_COMPLETE, axis, wait)

    def move_robot_cts(self, gripper_cts, elbow_cts, shoulder_cts, z_cts, vel=None, accel=None, wait=True):
        gripper_cts = int(gripper_cts)
        elbow_cts = int(elbow_cts)
        shoulder_cts = int(shoulder_cts)
        z_cts = int(z_cts)
        if vel is None:
            vel = self.default_vel
        if accel is None:
            accel = self.default_accel
        pos = [gripper_cts, elbow_cts, shoulder_cts, z_cts]
        for axis in range(4):
            if axis > 0 and pos[axis] > self.maximum_pos[axis]:
                pos[axis] = self.maximum_pos[axis]
        self.log("Moving robot to", pos)
        self.send_packet('MORO', [gripper_cts, elbow_cts, shoulder_cts, z_cts, vel, accel], wait=wait)
        return self.new_cmd_token(self.get_robot_status, self.FREE, wait=wait)

    def move_sync(self, axis0, axis1, cts0, cts1, vel=None, accel=None, wait=True):
        if vel is None:
            vel = self.default_vel
        if accel is None:
            accel = self.default_accel
        self.log("Synchronous move started")
        self.send_packet('SYNC', [axis0, axis1, cts0, cts1, vel, accel], wait=wait)
        return self.new_cmd_token(self.get_robot_status, self.FREE, wait=wait)

    def move_axis_mm(self, axis, mm, vel=None, accel=None, wait=True):
        return self.move_axis(axis, self.mm_to_counts(axis, mm), vel=vel, accel=accel, wait=wait)

    def move_z(self, z, vel=None, accel=None, wait=True):
        # int(self.Z_AXIS_MAX_COUNTS - self.Z_AXIS_COUNTS_PER_MM * (z - self.Z_AXIS_OFFSET) + 0.5)
        return self.move_axis_mm(self.Z_AXIS, z, vel=vel, accel=accel, wait=wait)

    def move_xy(self, x, y, pipette_tip_offset=False, shoulder_preference=n9.SHOULDER_CENTER,
                vel=None, accel=None, wait=True):
        # TODO: need move_sync_n in fw to move n axes synchronously (have to add gripper w/out z to this axis for tool
        #       support)
        _, theta_elbow, theta_shoulder = self.n9_ik(x=x,
                                                    y=y,
                                                    tool_length=0,
                                                    tool_orientation=None,
                                                    pipette_tip_offset=pipette_tip_offset,
                                                    shoulder_preference=shoulder_preference)
        elbow_cts = self.rad_to_counts(self.ELBOW, theta_elbow)
        shoulder_cts = self.rad_to_counts(self.SHOULDER, theta_shoulder)
        self.log(elbow_cts, shoulder_cts)
        return self.move_sync(self.ELBOW, self.SHOULDER, elbow_cts, shoulder_cts, vel, accel, wait)

    def move_xyz(self, x, y, z, tool_offset=[0, 0, 0], tool_orientation=None,
                 pipette_tip_offset=False, shoulder_preference = n9.SHOULDER_CENTER, vel=None, accel=None, wait=True):
        if tool_orientation is not None:
            tool_orientation = math.radians(tool_orientation)

        theta_gripper, theta_elbow, theta_shoulder = self.n9_ik(x=x,
                                                                y=y,
                                                                tool_length=tool_offset[self.X],
                                                                tool_orientation=tool_orientation,
                                                                pipette_tip_offset=pipette_tip_offset,
                                                                shoulder_preference=shoulder_preference)
        gripper_cts = self.rad_to_counts(self.GRIPPER, theta_gripper)
        elbow_cts = self.rad_to_counts(self.ELBOW, theta_elbow)
        shoulder_cts = self.rad_to_counts(self.SHOULDER, theta_shoulder)
        z_axis_cts = self.mm_to_counts(self.Z_AXIS, z+tool_offset[self.Z])
        self.log(elbow_cts, shoulder_cts, z_axis_cts)
        return self.move_robot_cts(gripper_cts, elbow_cts, shoulder_cts, z_axis_cts, vel=vel, accel=accel, wait=wait)

    def move_axis_rad(self, axis, rad, vel=None, accel=None, wait=True):
        return self.move_axis(axis, self.rad_to_counts(axis, rad), vel=vel, accel=accel, wait=wait)

    def move_robot(self, gripper_rad, elbow_rad, shoulder_rad, z_mm, vel=None, accel=None, wait=True):
        gripper_cts = self.rad_to_counts(self.GRIPPER, gripper_rad)
        elbow_cts = self.rad_to_counts(self.ELBOW, elbow_rad)
        shoulder_cts = self.rad_to_counts(self.SHOULDER, shoulder_rad)
        z_cts = self.mm_to_counts(self.Z_AXIS, z_mm)
        if vel is None:
            vel = self.default_vel
        if accel is None:
            accel = self.default_accel
        pos = [gripper_cts, elbow_cts, shoulder_cts, z_cts]
        for axis in range(4):
            if axis > 0 and pos[axis] > self.maximum_pos[axis]:
                pos[axis] = self.maximum_pos[axis]
        self.log("Moving robot to", pos)
        self.send_packet('MORO', [gripper_cts, elbow_cts, shoulder_cts, z_cts, vel, accel], wait=wait)
        return self.new_cmd_token(self.get_robot_status, self.FREE, wait=wait)

    def goto(self, loc_list, vel=None, accel=None, wait=True):
        return self.move_robot_cts(loc_list[0], loc_list[1], loc_list[2], loc_list[3], vel, accel, wait=wait)

    def goto_xy_safe(self, loc_list, vel=None, accel=None, wait=True):
        self.move_axis(self.Z_AXIS, self.safe_height, vel=vel, accel=accel, wait=True)
        self.move_robot_cts(loc_list[self.GRIPPER], loc_list[self.ELBOW], loc_list[self.SHOULDER], self.safe_height,
                            vel=vel, accel=accel, wait=True)

    def goto_z(self, loc_list, vel=None, accel=None, wait=True):
        return self.move_axis(self.Z_AXIS, loc_list[self.Z_AXIS], vel=vel, accel=accel, wait=wait)

    # TODO: add wait fcnality here - software sequence?
    def goto_safe(self, loc_list, vel=None, accel=None):
        self.goto_xy_safe(loc_list, vel=vel, accel=accel, wait=True)
        self.goto_z(loc_list, vel=vel, accel=accel, wait=True)

    def move_carousel(self, rot_deg, z_mm, vel=None, accel=None):
        if rot_deg < 0:
            rot_deg = 0
        elif rot_deg > 330:
            rot_deg = 330
        if z_mm < 0:
            z_mm = 0
        elif z_mm > 100:
            z_mm = 100

        self.move_axis(self.CAROUSEL_Z, 0, vel=vel, accel=accel)
        self.move_axis(self.CAROUSEL_ROT, int(rot_deg * (51000 / 360)), vel=vel, accel=accel)
        self.move_axis(self.CAROUSEL_Z, int(z_mm * (40000 / 100)), vel=vel, accel=accel)

    def spin_axis(self, axis, speed, accel=None, wait=True):
        self.log("Spinning axis", axis, "at", speed)
        if accel is None:
            accel = self.default_accel
        self.send_packet('SPAX', [axis, speed, accel], wait=wait)
        return self.new_cmd_token(self.get_axis_status, AxisState.VELOCITY_TARGET_REACHED, axis, wait)

    def axis_servo(self, axis, servo: bool):
        self.send_packet('SRVO', [axis, int(servo)])
        self.log("Axis", axis, "servo", servo)

    def amc_pwm(self, f, ms, amp, wait=True):
        self.send_packet('APWM', [f, ms, amp])
        return self.new_cmd_token(self.get_sequence_status, self.FREE, wait=wait)

    def get_axis_position(self, axis):
        args = self.send_packet('AXPS', [axis])
        print("Axis", axis, "at position", args[0])
        return args[0]

    def get_axis_target(self, axis):
        args = self.send_packet('GTGT', [axis])
        self.log("Axis", axis, "has position target", args[0])
        return args[0]

    def set_output(self, output_num, val: bool):
        self.send_packet('SETO', [output_num, int(val)])
        self.log("Set", output_num, "to state", val)

    def set_output_time(self, output_num, time):
        time_ms = int(time*1000)
        self.send_packet('STOT', [output_num, time_ms])
        print(f'Delaying while output {output_num} is on for {time*1.1} seconds')
        self.delay(time*1.1)

    def get_input(self, input_num):
        args = self.send_packet('GETI', [input_num])
        self.log("Input", input_num, "is in state", args[0])
        return args[0]

    def get_analog(self, analog_num):
        args = self.send_packet('GETA', [analog_num])
        self.log("Analog", analog_num, "has value:", args[0])
        return args[0]

    def config_analog(self,
                      analog_num,
                      start=ADS1115.START_READ,
                      pins=ADS1115.AIN0_GND,
                      v_range=ADS1115.V4_096,
                      mode=ADS1115.CONTINUOUS,
                      rate=ADS1115.SPS64):
        self.send_packet('CFGA', [analog_num, start, pins, v_range, mode, rate])
        self.log("Configured analog", analog_num)

    ######################################
    ##                                  ##
    ##           PNEUMATICS             ##
    ##                                  ##
    ######################################

    def open_gripper(self):
        self.send_packet('GRPR', [0])
        self.delay(self.GRIPPER_DELAY)
        self.log("Grippers open")

    def close_gripper(self):
        self.send_packet("GRPR", [1])
        self.delay(self.GRIPPER_DELAY)
        self.log("Grippers closed")

    def open_clamp(self, clamp_num=0):
        if self.sim:
            self.send_packet('CLMP', [clamp_num, 0])
        else:
            self.send_packet('CLMP', [0])

        self.delay(self.CLAMP_DELAY)
        self.log("Clamp open")

    def close_clamp(self, clamp_num=0):
        if self.sim:
            self.send_packet('CLMP', [clamp_num, 1])
        else:
            self.send_packet('CLMP', [1])

        self.delay(self.CLAMP_DELAY)
        self.log("Clamp closed")

    def bernoulli_on(self):
        self.send_packet('BRNL', [1])
        self.log("Bernoulli gripper on")

    def bernoulli_off(self):
        self.send_packet('BRNL', [0])
        self.log("Bernoulli gripper off")

    def vac_gripper_on(self):
        if self.sim:
            self.send_packet('VACU', [1])
        else:
            self.send_packet('BRNL', [1])
        self.log("Vacuum gripper on")

    def vac_gripper_off(self):
        if self.sim:
            self.send_packet('VACU', [0])
        else:
            self.send_packet('BRNL', [0])
        self.log("Vacuum gripper off")

    def robot_servo(self, servo: bool):
        for i in range(4):
            self.axis_servo(i, servo)

    def get_robot_positions(self):
        return [self.get_axis_position(i) for i in range(4)]

    ######################################
    ##                                  ##
    ##       UNITS AND KINEMATICS       ##
    ##                                  ##
    ######################################

    @staticmethod
    def counts_to_rad(axis, counts):
        return n9.counts_to_rad(axis, counts)

    @staticmethod
    def rad_to_counts(axis, rad):
        return n9.rad_to_counts(axis, rad)

    @staticmethod
    def counts_to_mm(axis, counts):
        return n9.counts_to_mm(axis, counts)

    @staticmethod
    def mm_to_counts(axis, mm):
        return n9.mm_to_counts(axis, mm)

    @staticmethod
    def n9_fk(gripper_cts, elbow_cts, shoulder_cts, tool_length=0, pipette_tip_offset=False):  # TODO, include gripper, z-axis tool, etc
        return n9.fk(gripper_cts, elbow_cts, shoulder_cts, tool_length, pipette_tip_offset)

    @staticmethod
    def n9_ik(x, y, tool_length=0, tool_orientation=None, pipette_tip_offset=False, shoulder_preference=None):
        return n9.ik(x, y, tool_length, tool_orientation, pipette_tip_offset, shoulder_preference)

    ######################################
    ##                                  ##
    ##           CMD_TOKENS             ##
    ##                                  ##
    ######################################

    # This architecture is in place to allow the class to store the previous cmd token, so c9.wait_for() would
    # obviate the need to manually store the previous cmd

    def new_cmd_token(self, func, value, axis=None, wait=True, delay=0):
        tkn = CmdToken(func, value, axis, delay, self.sim)
        self.prev_cmd_token = tkn
        if wait:
            tkn.wait()
        return tkn

    def wait_for(self, tkn: CmdToken = None):
        if tkn is None:
            tkn = self.prev_cmd_token
        tkn.wait()

    def cmd_done(self, token: CmdToken = None):
        if token is None:
            token = self.prev_cmd_token
        return token.is_done()

    ######################################
    ##                                  ##
    ##              PUMPS               ##
    ##                                  ##
    ######################################
    def _get_pump_delay(self):
        """
        :return: Delay in seconds for pump command tokens.
        """
        # enforces that 0.0 won't be sent to a *SerialControllerNetwork
        assert (self.sim and isinstance(self.network, VirtualControllerNetwork)) \
            or (not self.sim and not isinstance(self.network, VirtualControllerNetwork))
        return 0.0 if self.sim else self.SERIAL_PUMP_DELAY

    def is_pump_free(self, pump_num):
        args = self.send_packet('PMST', [pump_num])
        # return args[0]
        return args[0] == self.FREE

    def home_pump(self, pump_num, wait=True):
        def internal(pump_num, wait):
            self.pumps[pump_num]['pos'] = 0
            self.send_packet('HOPM', [pump_num], wait=wait)
            self.log("Homing pump", pump_num)
            return self.new_cmd_token(self.is_pump_free, True, pump_num, wait, delay=self._get_pump_delay())

        try:
            return internal(pump_num, wait)
        except RuntimeError:
            self.delay(1.5)
            return internal(pump_num, wait)

    def move_pump(self, pump_num, pos, wait=True):
        def internal(pump_num, pos, wait):
            self.pumps[pump_num]['pos'] = pos
            self.send_packet('MOPM', [pump_num, pos], wait=wait)
            self.log("Moving pump", pump_num, "to position", pos)
            return self.new_cmd_token(self.is_pump_free, True, pump_num, wait, delay=self._get_pump_delay())
        
        try:
            return internal(pump_num, pos, wait)
        except RuntimeError:
            self.delay(1.5)
            # return internal(pump_num, pos, wait) ### XXX Nis trying to fix pump error


    def aspirate_ml(self, pump_num, ml, wait=True):
        def internal(pump_num, ml, wait):
            new_pos = int(self.pumps[pump_num]['pos'] + ml * (n9.PUMP_MAX_COUNTS / self.pumps[pump_num]['volume']))
            if new_pos > n9.PUMP_MAX_COUNTS:
                print('Pump volume too full to aspirate', ml, 'ml')
                return
            return self.move_pump(pump_num, new_pos, wait)

        try:
            return internal(pump_num, ml, wait)
        except RuntimeError:
            self.delay(1.5)
            # return internal(pump_num, ml, wait) ### XXX Nis trying to fix pump error

    def dispense_ml(self, pump_num, ml, wait=True):
        def internal(pump_num, ml, wait):
            new_pos = int(self.pumps[pump_num]['pos'] - ml * (n9.PUMP_MAX_COUNTS / self.pumps[pump_num]['volume']))
            if new_pos < 0:
                print('Cannot move pump to', new_pos, '...')
                print('Pump volume too empty to dispense', ml, 'ml')
                return
            return self.move_pump(pump_num, new_pos, wait)
        
        try:
            return internal(pump_num, ml, wait)
        except RuntimeError:
            self.delay(1.5)
            # return internal(pump_num, ml, wait)  # XXX Nis trying to fix pump error 

    # Todo: sanitize pump inputs (e.g. valve_pos)
    def set_pump_valve(self, pump_num, valve_pos, wait=True):
        self.send_packet('SPMV', [pump_num, valve_pos], wait=wait)
        self.log("Setting pump valve", pump_num, "to position", valve_pos)
        return self.new_cmd_token(self.is_pump_free, True, pump_num, wait, delay=self._get_pump_delay())

    def set_pump_speed(self, pump_num, speed):
        self.send_packet('SPMS', [pump_num, speed])
        self.log("Setting speed of pump", pump_num, "to ", speed)

    ######################################
    ##                                  ##
    ##              SCALE               ##
    ##                                  ##
    ######################################
    def dbg_scale_property(self, prop_num):
        self.send_packet('SCDP', [int(prop_num)])

    def set_scale_property(self, prop_num, value):
        self.send_packet('SCSP', [int(prop_num), int(value)])
    def clear_scale(self):
        self.send_packet('CLSC')
        self.log("Scale cleared")

    def read_scale(self):
        args = self.send_packet('RDSC')
        steady = bool(args[0])
        weight = self._weight_from_args(args[1:5])
        try:
            units = args[5]
        except IndexError:
            units = 0

        self.log("Scale read:", weight, self._scale_unit_str(units), ", steady:", steady)
        return steady, weight

    # Methods that wait to get a specific value from the controller return a value when wait is True
    # and return a CmdToken object when wait is False.
    def read_steady_scale(self, wait=True):

        # Behaviour of steady scale reading is slightly different in current iteration of sim:
        # Since steady scale reading reading relies on a cmd token calling its wait fcn (read_scale) to get the
        # actual update and the simulator ignores all cmd tokens (to be imporved with the "line-by-line" sim in the
        # future) the read_steady_scale() cmd simply calls read_scale() itself, outside the cmd_tkn framework.
        if self.sim:
            return self.read_scale()[1]  # return the second element of tuple

        tkn = self.new_cmd_token(self.read_scale, True, wait=wait)
        if wait:
            return tkn.return_value[0]
        return tkn

    def zero_scale(self):
        self.send_packet('ZRSC')
        self.log("Scale zeroed")

    def _weight_from_args(self, args):
        # read_scale returns 6 args from FW:
        # args[0]: steady flag
        # args[1]: negative flag
        # args[2]: pre-dec integer
        # args[3]: post-dec integer
        # args[4]: number of digits post-dec
        # args[5]: units code
        # given args 1:5 or 1:, this function returns the weight as a float]

        neg = bool(args[0])
        pre_dec = int(args[1])
        post_dec = float(args[2])
        post_dec_len = int(args[3])

        for i in range(post_dec_len):
            post_dec /= 10

        weight = pre_dec + post_dec
        if neg:
            weight *= -1
        return weight

    def _scale_unit_str(self, unit_num):
        if unit_num == 1:
            return "g"
        elif unit_num == 2:
            return 'kg'
        elif unit_num == 3:
            return 'mg'
        elif unit_num == 4:
            return 'ct'
        elif unit_num == 5:
            return 'dwt'
        elif unit_num == 6:
            return 'ozt'
        elif unit_num == 7:
            return 'oz'
        elif unit_num == 8:
            return 'lb'
        else:
            return "UNKNOWN"

    # ######################################
    # ##                                  ##
    # ##              BARCODE             ##
    # ##                                  ##
    # ######################################

    # TODO: HANDLE BARCODE FAILURES/TIMEOUTS

    def barcode_status(self):
        args = self.send_packet('GTBC')
        if len(args) == 0:
            return False
        else:
            return True, args[0]

    def cancel_barcode(self):
        args = self.send_packet('NOBC')
        self.log("Barcode read cancelled")

    # Methods that wait to get a specific value from the controller return a value when wait is True
    # and return a CmdToken object when wait is False.
    def get_barcode(self, wait=True):

        # Behaviour of barcode reading is slightly different in current iteration of sim:
        # Since barcode reading relies on a cmd token calling its wait fcn (barcode_status) to get the actual
        # update and the simulator ignores all cmd tokens (to be imporved with the "line-by-line" sim in the future)
        # the get_barcode() cmd simply calls barcode_status() itself, outside the cmd_tkn framework.
        if self.sim:
            return self.barcode_status()[1]  # return the second element of tuple

        tkn = self.new_cmd_token(self.barcode_status, True, wait=wait)
        if wait:
            return tkn.return_value[0]
        return tkn

    ######################################
    ##                                  ##
    ##              TEMP                ##
    ##                                  ##
    ######################################

    def get_temp(self, channel):
        args = self.send_packet('GTPV', [int(channel)])
        self.log("Channel", channel, "temp is", args[0])
        return args[0] / 10.0

    def set_temp(self, channel, temp):
        value = int(temp * 10)
        self.send_packet('STSV', [int(channel), value])
        self.log("Channel", channel, "temp set to", temp)

    def temp_autotune(self, channel, enable: bool):
        self.send_packet('STAT', [int(channel), int(enable)])
        self.log("Autotune on channel", channel, "set to", str(enable))

    def temp_heatcool(self, channel, val):
        self.send_packet('STHC', [int(channel), int(val)])
        self.log("Heal/cool IO on channel", channel, "set to", val)

    def temp_offset(self, channel, offset):
        value = int(offset * 10)
        self.send_packet('STTR', [int(channel), value])
        self.log("Temp offset on channel", channel, "set to", offset)

    ######################################
    ##                                  ##
    ##             CONFIG               ##
    ##                                  ##
    ######################################
    def get_c9_addr(self):
        # this method is primarily a test of EEPROM - you must know the addr to send the packet
        args = self.send_packet('GADR')
        self.log("Controller's address is", args[0])
        return args[0]

    def set_c9_addr(self, new_addr, broadcast=False):
        try:
            new_addr = int(new_addr)
        except ValueError:
            new_addr = ord(new_addr)
        if new_addr > 255 or new_addr < 1:
            raise ValueError("New address must be in the range [1, 255]")

        self.send_packet('SADR', [new_addr], broadcast=broadcast)
        self.log("Controller's address set to", new_addr)
        if not self.verbose:
            print("Controller's address set to", new_addr)
            print("The controller must be restarted for this to take effect")
    # ######################################
    # ##                                  ##
    # ##             CAPPING              ##
    # ##                                  ##
    # ######################################

    # TODO: change default vial properties?
    def uncap(self, pitch=2, revs=2.5, vel=5000, accel=40000, wait=True):
        gripper_counts = int(-revs * self.GRIPPER_COUNTS_PER_REV)
        pitch_cts = int(self.GRIPPER_COUNTS_PER_REV / (pitch * self.Z_AXIS_COUNTS_PER_MM))
        # z_axis_counts = int(-revs*pitch*self.Z_AXIS_COUNTS_PER_MM)
        self.send_packet('UCAP', [gripper_counts, pitch_cts, vel, accel], wait=wait)
        self.log("Uncapping")
        return self.new_cmd_token(self.get_sequence_status, self.FREE, wait=wait)

    # TODO: change default vial properties?
    def cap(self, pitch=2, revs=2.5, torque_thresh=1500, vel=5000, accel=40000, wait=True):
        gripper_counts = int(revs * self.GRIPPER_COUNTS_PER_REV)
        pitch_cts = int(self.GRIPPER_COUNTS_PER_REV / (pitch * self.Z_AXIS_COUNTS_PER_MM))
        # z_axis_counts = int(revs*pitch*self.Z_AXIS_COUNTS_PER_MM)
        self.send_packet('CAPV', [gripper_counts, pitch_cts, torque_thresh, vel, accel], wait=wait)
        self.log("Capping")
        return self.new_cmd_token(self.get_sequence_status, self.FREE, wait=wait)

    # ######################################
    # ##                                  ##
    # ##            JOYSTICK              ##
    # ##                                  ##
    # ######################################

    def start_joystick(self):
        self.send_packet('JSBG')
        self.log("Starting joystick")

    def update_joystick(self, vel):
        vel = [int(v) for v in vel]
        self.send_packet('JSUP', vel)
        # self.log("Update joystick to new velocity:", vel)

    def stop_joystick(self):
        self.send_packet('JSSP')
        self.log("Stopping joystick")

    def joystick_mode(self):
        self.start_joystick()
        js_thread = threading.Thread(target=self._joystick_reader)
        js_thread.start()

        while js_thread.is_alive():
            self.update_joystick(self.js_vel)

        self.stop_joystick()

    def _joystick_reader(self):
        gamepad = True
        while (1):
            if gamepad:
                try:
                    events = get_gamepad()
                except UnpluggedError:
                    gamepad = False
                    print('No gamepad connected... using keyboard inputs')
                    continue

                for event in events:
                    if event.code == 'BTN_SOUTH':
                        if event.state:
                            return
                    elif event.code == 'ABS_RX':
                        self.js_vel[n9.SHOULDER] = self._joy_analog2speed(event.state)
                    elif event.code == 'ABS_RY':
                        self.js_vel[n9.Z_AXIS] = self._joy_analog2speed(-event.state)
                    elif event.code == 'ABS_X':
                        self.js_vel[n9.ELBOW] = self._joy_analog2speed(-event.state)
                    elif event.code == 'ABS_Y':
                        self.js_vel[n9.GRIPPER] = self._joy_analog2speed(event.state)
            else:
                while (1):
                    if keyboard.is_pressed('left'):
                        self.js_vel[n9.SHOULDER] = -self.key_speed
                    elif keyboard.is_pressed('right'):
                        self.js_vel[n9.SHOULDER] = self.key_speed
                    else:
                        self.js_vel[n9.SHOULDER] = 0

                    if keyboard.is_pressed('up'):
                        self.js_vel[n9.Z_AXIS] = -self.key_speed
                    elif keyboard.is_pressed('down'):
                        self.js_vel[n9.Z_AXIS] = self.key_speed
                    else:
                        self.js_vel[n9.Z_AXIS] = 0

                    if keyboard.is_pressed('w'):
                        self.js_vel[n9.GRIPPER] = self.key_speed
                    elif keyboard.is_pressed('s'):
                        self.js_vel[n9.GRIPPER] = -self.key_speed
                    else:
                        self.js_vel[n9.GRIPPER] = 0

                    if keyboard.is_pressed('a'):
                        self.js_vel[n9.ELBOW] = self.key_speed
                    elif keyboard.is_pressed('d'):
                        self.js_vel[n9.ELBOW] = -self.key_speed
                    else:
                        self.js_vel[n9.ELBOW] = 0

                    sleep(0.01)  # have some poll time in there so its not hogging cpu

    @staticmethod
    def _joy_analog2speed(val):
        MAX_JOY_VAL = 32768
        MAX_JOINT_SPEED = 7500
        MIN_JOINT_SPEED = 100
        DEADZONE_PERCENT = 0.2
        # deadzone
        if abs(val) < MAX_JOY_VAL * DEADZONE_PERCENT:
            return 0

        return int(math.copysign((MAX_JOINT_SPEED - MIN_JOINT_SPEED) / (MAX_JOY_VAL * (1 - DEADZONE_PERCENT)) * \
                                 (abs(val) - MAX_JOY_VAL * DEADZONE_PERCENT) + MIN_JOINT_SPEED, val))

class BaseControllerNetwork(ABC): # interface for network classes
    @abstractmethod
    def disconnect(self):
        raise NotImplementedError()
    @abstractproperty
    def time(self): raise NotImplementedError()
    @abstractmethod
    def send(self, data, expect_response=True):
        """
        :param bytes data: Message to controller.
        :param bool expect_response: will listen for a response if true
        :return: Response from controller.
        """
        raise NotImplementedError()

class FTDISerialControllerNetwork(BaseControllerNetwork):

    MAX_RESP_LEN = 1024
    TIMEOUT = 0.6 # pumps need ~500ms timeout in FW, so this should be larger

    def __init__(self, network=None, network_serial:str=None):
        if network_serial == '':
            network_serial = None

        self.network = network
        if self.network is None:
            try:
                self.network = Serial(device_serial=network_serial)
            except NameError:
                logging.error('NorthC9: Tried to initialize network without FTDI support.')

    def disconnect(self):
        self.network.disconnect()

    @property
    def time(self):
        return time() # real time

    def send(self, data, expect_response=True) -> bytes:
        """
        :param bytes data:
        :param bool expect_response: will listen for a response if true
        :return: response
        """
        data += build_crc(data)

        self.network.flush()
        sleep(0.1)
        self.network.write(data)

        if not expect_response:
            return b''

        packet_len = self.network.read(1, self.TIMEOUT)
        response_bytes = packet_len + self.network.read(int.from_bytes(packet_len, 'big') - 1, 0.2)

        if not response_bytes:
            print("No response...")
            raise IOError

        if len(response_bytes) >= self.MAX_RESP_LEN:
            print("Response overflow")
            raise IOError

        resp_crc = response_bytes[-2:]
        calc_crc = build_crc(response_bytes[:-2])  # CRC check excludes only CRC bytes

        if calc_crc != resp_crc:
            print("CRC Error...")
            print(response_bytes)
            raise IOError

        #print(response_bytes[1:-2])

        return response_bytes[1:-2] # response excludes leading packet len byte and trailing CRC

class GenericSerialControllerNetwork(BaseControllerNetwork):

    MAX_RESP_LEN = 1024
    TIMEOUT = 0.6 # pumps need ~500ms timeout in FW, so this should be larger

    def __init__(self, network=None, network_serial: str = None):
        if network_serial is None:
            raise RuntimeError ('Network serial parameter required for Generic Serial connections')

        self.network = network
        if self.network is None:
            self.network = serial.Serial(network_serial, 115200, timeout=0, parity=serial.PARITY_NONE)

    def disconnect(self):
        pass # TODO?

    @property
    def time(self):
        return time() # real time

    def send(self, data, expect_response=True) -> bytes:
        """
        :param bytes data:
        :return: response
        """
        data += build_crc(data)

        self.network.write(data)

        self.network.timeout = self.TIMEOUT
        packet_len = self.network.read(1)
        self.network.timeout = 0.2
        response_bytes = packet_len + self.network.read(int.from_bytes(packet_len, 'big') - 1)

        if not response_bytes:
            print("No response...")
            raise IOError

        if len(response_bytes) >= self.MAX_RESP_LEN:
            print("Response overflow")
            raise IOError

        resp_crc = response_bytes[-2:]
        calc_crc = build_crc(response_bytes[:-2])  # CRC check excludes only CRC bytes

        if calc_crc != resp_crc:
            print("CRC Error...")
            print(response_bytes)
            raise IOError

        return response_bytes[1:-2] # response excludes leading packet len byte and trailing CRC

class VirtualControllerNetwork(BaseControllerNetwork):
    def __init__(self, c9):
        """
        :param NorthC9 c9:
        """
        assert isinstance(c9, NorthC9)
        self.c9 = c9
        self._sim_time = 0.0

        # TODO line below is needed in line numbering code
        # self._stack_offset = len(stack()) - 2 # note: 2 is a magic number...

    def disconnect(self):
        pass # TODO?

    @property
    def time(self):
        return self._sim_time

    def send(self, data, expect_response=True) -> bytes:
        """
        Send command to virtual controller.

        :param bytes data:
        :return: Response from simulator (through VC).
        """
        assert isinstance(self.c9, NorthC9)
        assert self.c9.has_simulator

        # get 'wait' bool from data head then rebuild it without that
        decoded = data.decode("charmap")
        wait = decoded[0] == '1'
        data = bytes(decoded[1:], "charmap")

        # get a line number to send sim
        line = 0 # this would be replaced by the code below
        """
        cmd = data.split(b' ')[1].decode('ascii')
        start = perf_counter()
        if not cmd.endswith('ST'):
            # get current line from frame
            line = stack()[-self._stack_offset].lineno # TODO this still takes pretty long.
        else:
            line = 0
        end = perf_counter()
        print(f'line {line}')
        print(f'line time: {"%.5f"%(end-start)}s')
        """

        # get a task id to send sim
        if self.c9.has_scheduler:
            task = self.c9.scheduler.get_task()
        else:
            task = -1

        # send cmd line to simulator and get response and the time added by cmd
        response, time = self.c9.simulator.handle_cmd(data, line=line, task=task, wait=wait)
        self._sim_time += time
        return response

def build_crc16_table():
    result = []
    for byte in range(256):
        crc = 0x0000
        for _ in range(8):
            if (byte ^ crc) & 0x0001:
                crc = (crc >> 1) ^ 0xa001
            else:
                crc >>= 1
            byte >>= 1
        result.append(crc)
    return result


crc16_table = build_crc16_table()


def build_crc(data: bytes) -> bytes:
    crc = 0xffff
    for a in data:
        idx = crc16_table[(crc ^ a) & 0xff]
        crc = ((crc >> 8) & 0xff) ^ idx

    return crc.to_bytes(2, 'little')


class C9Errors:
    # Error sources:
    MAIN_COG = 0
    IO_COG = 1
    AXIS_NETWORK_COG = 2
    C9_NETWORK_COG = 3
    MOTION_COG = 4
    AUX_COM_COG = 5
    SEQUENCE_COG = 6
    DEBUG_COG = 7

    # Error types:
    SUCCESS = 0
    ERROR_AXIS_NO_RESPONSE = 1
    ERROR_AXIS_BUFFER_OVERFLOW = 2
    ERROR_AXIS_BAD_CRC = 3
    ERROR_C9_BUFFER_OVERFLOW = 4
    ERROR_C9_BAD_CRC = 5
    ERROR_C9_BAD_PARSE = 6
    ERROR_NO_COG = 7
    ERROR_HARD_STOP = 8
    ERROR_SOFT_STOP = 9
    ERROR_PUMP_NO_RESPONSE = 10
    ERROR_PUMP_BAD_RESPONSE = 11
    ERROR_PUMP_BUFFER_OVERFLOW = 12
    ERROR_SCALE_NO_RESPONSE = 13
    ERROR_SCALE_BUFFER_OVERFLOW = 14
    ERROR_SCALE_MESSAGE_FAILED = 15
    ERROR_SCALE_BAD_PARSE = 16
    ERROR_SCALE_OVERLOAD = 17
    ERROR_BARCODE_NO_RESPONSE = 18
    ERROR_BARCODE_BUFFER_OVERFLOW = 19
    ERROR_AXIS_TYPE = 20
    ERROR_MOTOR_FAULT = 21
    ERROR_CAPPING_UNDER_TORQUE = 22
    ERROR_HOME_REQUIRED = 23

    def __init__(self, src, e):
        self.source = src
        self.error = e

    def __str__(self):

        if self.source == self.MAIN_COG:
            e_str = "Main: "
        elif self.source == self.IO_COG:
            e_str = "IO: "
        elif self.source == self.AXIS_NETWORK_COG:
            e_str = "Axis Network: "
        elif self.source == self.C9_NETWORK_COG:
            e_str = "C9 Network: "
        elif self.source == self.MOTION_COG:
            e_str = "Motion: "
        elif self.source == self.AUX_COM_COG:
            e_str = "Aux COM: "
        elif self.source == self.SEQUENCE_COG:
            e_str = "Sequence: "
        else:
            e_str = "Unknown Source: "

        if self.error == self.SUCCESS:
            e_str += "Success"
        elif self.error == self.ERROR_AXIS_NO_RESPONSE:
            e_str += "AXIS ERROR: Response timeout"
        elif self.error == self.ERROR_AXIS_BUFFER_OVERFLOW:
            e_str += "AXIS ERROR: Response buffer overflow"
        elif self.error == self.ERROR_AXIS_BAD_CRC:
            e_str += "AXIS ERROR: Bad CRC"
        elif self.error == self.ERROR_C9_BUFFER_OVERFLOW:
            e_str += "C9 ERROR: Request buffer overflow"
        elif self.error == self.ERROR_C9_BAD_CRC:
            e_str += "C9 ERROR: Bad CRC"
        elif self.error == self.ERROR_C9_BAD_PARSE:
            e_str += "C9 ERROR: Failed to parse request"
        elif self.error == self.ERROR_NO_COG:
            e_str += "PROPELLER ERROR: No cog available to start process"
        elif self.error == self.ERROR_HARD_STOP:
            e_str += "SYSTEM ERROR: Hard E-Stop triggered, restart the system when it is safe to do so"
        elif self.error == self.ERROR_SOFT_STOP:
            e_str += "SYSTEM ERROR: Soft E-Stop triggered, clear the fault to resume operation"
        elif self.error == self.ERROR_PUMP_NO_RESPONSE:
            e_str += "PUMP ERROR: Response timeout"
        elif self.error == self.ERROR_PUMP_BAD_RESPONSE:
            e_str += "PUMP ERROR: Failed to parse response"
        elif self.error == self.ERROR_PUMP_BUFFER_OVERFLOW:
            e_str += "PUMP ERROR: Response buffer overflow"
        elif self.error == self.ERROR_SCALE_NO_RESPONSE:
            e_str += "SCALE ERROR: Response timeout"
        elif self.error == self.ERROR_SCALE_BUFFER_OVERFLOW:
            e_str += "SCALE ERROR: Response buffer overflow"
        elif self.error == self.ERROR_SCALE_MESSAGE_FAILED:
            e_str += "SCALE ERROR: Scale received invalid message"
        elif self.error == self.ERROR_SCALE_BAD_PARSE:
            e_str += "SCALE ERROR: Failed to parse response"
        elif self.error == self.ERROR_SCALE_OVERLOAD:
            e_str += "SCALE ERROR: Overload condition"
        elif self.error == self.ERROR_BARCODE_NO_RESPONSE:
            e_str += "BARCODE ERROR: Response timeout"
        elif self.error == self.ERROR_BARCODE_BUFFER_OVERFLOW:
            e_str += "BARCODE ERROR: Response buffer overflow"
        elif self.error == self.ERROR_AXIS_TYPE:
            e_str += "AXIS TYPE ERROR: At least one of the specified axes do not support the requested command"
        elif self.error == self.ERROR_MOTOR_FAULT:
            e_str += "MOTOR FAULT: A critical error has occured on a motor driver, restart the controller"
        elif self.error == self.ERROR_CAPPING_UNDER_TORQUE:
            e_str += "CAPPING FAULT: Torque threshold not reached"
        elif self.error == self.ERROR_HOME_REQUIRED:
            e_str += "HOME REQUIRED: Home the robot or aux axis before moving"
        else:
            e_str += "UNKNOWN ERROR"

        return e_str