import math
from north_c9 import GRIPPER, ELBOW, SHOULDER, Z_AXIS

ELBOW_MAX_COUNTS = 42500
SHOULDER_MAX_COUNTS = 67333
Z_AXIS_MAX_COUNTS = 26200

GRIPPER_COUNTS_PER_REV = 4000
ELBOW_COUNTS_PER_REV = 51000
SHOULDER_COUNTS_PER_REV = 101000
Z_AXIS_COUNTS_PER_MM = 100

ELBOW_OFFSET = 21250
SHOULDER_OFFSET = 33667
Z_AXIS_OFFSET = 30  # test grippers - TODO: MAKE THIS GENERIC, TOOL IK ETC.

POS_X = -math.pi/2
POS_Y = 0
NEG_X = math.pi/2
NEG_Y = math.pi

DEFAULT_TOOL_ORIENTATION = POS_Y

SHOULDER_CENTER = 0
SHOULDER_OUT = 1

PUMP_MAX_COUNTS = 3000

def counts_to_rad(axis, counts):
    if axis == GRIPPER:  # TODO: check sign
        return -counts * (math.tau / GRIPPER_COUNTS_PER_REV)
    elif axis == ELBOW:
        return -(counts - ELBOW_OFFSET) * (math.tau / ELBOW_COUNTS_PER_REV)
    elif axis == SHOULDER:
        return (counts - SHOULDER_OFFSET) * (math.tau / SHOULDER_COUNTS_PER_REV)

    raise RuntimeError("ERROR: Axis does not support measurements in radians")


def rad_to_counts(axis, rad):
    if axis == GRIPPER:
        return -int((rad/math.tau) * GRIPPER_COUNTS_PER_REV + 0.5)
    elif axis == ELBOW:
        return int(ELBOW_OFFSET - (rad / math.tau) * ELBOW_COUNTS_PER_REV + 0.5)
    elif axis == SHOULDER:
        return int((rad / math.tau) * SHOULDER_COUNTS_PER_REV + SHOULDER_OFFSET + 0.5)

    raise RuntimeError("ERROR: Axis does not support measurements in radians")


def counts_to_mm(axis, counts):
    if axis == Z_AXIS:  # TODO: check sign
        return (Z_AXIS_MAX_COUNTS - counts) / Z_AXIS_COUNTS_PER_MM + Z_AXIS_OFFSET

    raise RuntimeError("ERROR: Axis does not support measurements in mm")


def mm_to_counts(axis, mm):
    if axis == Z_AXIS:
        return int(Z_AXIS_MAX_COUNTS - Z_AXIS_COUNTS_PER_MM * (mm - Z_AXIS_OFFSET) + 0.5)

    raise RuntimeError("ERROR: Axis does not support measurements in mm")

def fk_rad (theta_gripper, theta_elbow, theta_shoulder, tool_length=0):

    l1 = l2 = 170

    x1 = l1 * math.cos(theta_shoulder)
    y1 = l1 * math.sin(theta_shoulder)
    x2 = l2 * math.cos(theta_shoulder + theta_elbow) + x1
    y2 = l2 * math.sin(theta_shoulder + theta_elbow) + y1
    x3 = tool_length * math.cos(theta_shoulder + theta_elbow + theta_gripper) + x2
    y3 = tool_length * math.sin(theta_shoulder + theta_elbow + theta_gripper) + y2

    x = -y3
    y = x3

    return x, y

def fk(gripper_cts, elbow_cts, shoulder_cts, tool_length=0, pipette_tip_offset=False):  # TODO, include gripper, z-axis tool, etc
    theta_gripper = counts_to_rad(GRIPPER, gripper_cts)
    theta_elbow = counts_to_rad(ELBOW, elbow_cts)
    theta_shoulder = counts_to_rad(SHOULDER, shoulder_cts)

    l1 = 170  # length of shoulder to elbow
    l2 = 170 + pipette_tip_offset*44  # length of elbow to gripper, plus tool

    x1 = l1 * math.cos(theta_shoulder)
    y1 = l1 * math.sin(theta_shoulder)
    x2 = l2 * math.cos(theta_shoulder + theta_elbow) + x1
    y2 = l2 * math.sin(theta_shoulder + theta_elbow) + y1
    theta = theta_shoulder + theta_elbow + theta_gripper
    x3 = tool_length * math.cos(theta) + x2
    y3 = tool_length * math.sin(theta) + y2

    x = -y3
    y = x3
    theta += math.pi/2

    return x, y, theta

#todo: should this return counts?
def ik(x, y, tool_length=0, tool_orientation=None, pipette_tip_offset=False, shoulder_preference=None):
    #swap x/y for IK convention (i.e. a pose of [0, 0, 0] on the three R joints is straight out along +y axis)
    if shoulder_preference is None:
        shoulder_preference = SHOULDER_CENTER

    if tool_orientation is None:
        tool_orientation = DEFAULT_TOOL_ORIENTATION

    tmp = x
    x = y
    y = -tmp
    tool_orientation -= math.pi/2

    x -= tool_length * math.cos(tool_orientation)
    y -= tool_length * math.sin(tool_orientation)

    l1 = 170
    l2 = 170 + pipette_tip_offset*44  # add pipette tip offset if True

    temp = (x ** 2 + y ** 2 - l1 ** 2 - l2 ** 2) / (-2 * l1 * l2)
    elbow_inside_angle = math.acos(temp)
    elbow_angle_1 = math.pi - elbow_inside_angle
    elbow_angle_2 = -elbow_angle_1

    pseudo_line = math.sqrt(x ** 2 + y ** 2)
    pseudo_angle = math.atan2(y, x)

    temp = (l1 ** 2 + pseudo_line ** 2 - (l2 ** 2)) / (2 * l1 * pseudo_line)
    shoulder_inside_angle = math.acos(temp)

    shoulder_angle_1 = pseudo_angle - shoulder_inside_angle
    shoulder_angle_2 = pseudo_angle + shoulder_inside_angle

    if abs(shoulder_angle_1) < abs(shoulder_angle_2):
        if shoulder_preference == SHOULDER_CENTER:
            shoulder_final = shoulder_angle_1
            elbow_final = elbow_angle_1
        else:
            shoulder_final = shoulder_angle_2
            elbow_final = elbow_angle_2
    else:
        if shoulder_preference == SHOULDER_CENTER:
            shoulder_final = shoulder_angle_2
            elbow_final = elbow_angle_2
        else:
            shoulder_final = shoulder_angle_1
            elbow_final = elbow_angle_1

    gripper_final = tool_orientation - (shoulder_final + elbow_final)  # 0 if tool_length == 0 else...

    return gripper_final, elbow_final, shoulder_final
