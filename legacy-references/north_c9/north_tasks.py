from collections import deque
import inspect
import logging
from sortedcontainers import SortedList
from time import time, sleep
import sys

from typing import Callable

from .north_c9 import NorthC9

class Task:

    # todo: support *args, **kwargs
    def __init__(self, task_id, func, max_t=-1, priority=1, child=False, args=None):
        """

        :param int task_id:
        :param Callable func:
        :param int max_t:
        :param priority:
        """
        self.name = func.__name__
        self.task_id = task_id
        self.child = child
#        if not child:
        self.func = func
        self.gen_func = func if inspect.isgeneratorfunction(func) else self._make_gen(func)
        if args is None:
            args = []

        self.gen = self.gen_func(*args)
#        else:
#            self.func = func
#            self.gen = None
        self._max_t = max_t
        self.times_hist = []
        self.priority = priority
        self.resume_t = None
        self._desired_resume_t = None

        print (f'making a new task {self} with args {args}')

    def __next__(self):
#        if self.child:
#            return self.func(*self.args)
        self._desired_resume_t = 0
        self.resume_t = 0
        return next(self.gen)

    def __repr__(self):
        return self.name

    @property
    def desired_resume_t(self):
        return self._desired_resume_t

    @desired_resume_t.setter
    def desired_resume_t(self, new_desired_resume_t):
        if new_desired_resume_t < 0:
            new_desired_resume_t = 0

        self._desired_resume_t = new_desired_resume_t
        self.resume_t = new_desired_resume_t

    @property
    def max_t(self):
        return self._max_t

    @max_t.setter
    def max_t(self, new_max_t):
        if new_max_t < 0:
            new_max_t = 0
        self._max_t = new_max_t

    @ property
    def end_t(self):
        return self.resume_t + self.max_t

    @staticmethod
    def _make_gen(func):
        """
        :param Callable func:
        :return: generator function
        """
        def wrapped(*args, **kwargs):  # todo: could we reverse the order of f() and yield to prevent extra call to get stopiterexcptn?
            yield func(*args, **kwargs)
        return wrapped

#todo - scheduler should be able to schedule schedulers

class Scheduler:
    
    def __init__(self, c9, verbose=False):
        """
        Scheduler class.

        :param NorthC9 c9: The controller object you'd like to schedule over.
        """
        assert isinstance(c9, NorthC9)
        assert not c9.has_scheduler
        self.controller = c9
        c9._scheduler = self

        self._tasks = {}
        self._scheduled = SortedList(key=lambda task: task.resume_t)  # tasks to resume, sorted by increasing resume_t
        self._bg_q = deque()  # a queue of background tasks run in round-robin style as they fit
        self._running = False
        self._next_id = 0

        self._id_name_d = {}

        self._cur_task = None

        self.verbose=verbose

    def vprint(self, *args):
        if self.verbose:
            print(*args)

    def _get_next_id(self, func_name=None):
        if func_name is None:
            self._next_id += 1
            return self._next_id

        if func_name in self._id_name_d:
            return self._id_name_d[func_name]

        self._next_id += 1
        self._id_name_d[func_name] = self._next_id
        return self._next_id

    def add_task(self, func, max_t='auto', safe_factor=0.1, priority=1, child=False):
        """
        Add task to schedule.

        :param Callable func:
        :param max_t:
        :param float safe_margin:
        :param int priority:
        """
        assert isinstance(func, Callable)
        # handle automatic time estimates
        task_id = self._get_next_id()

        if max_t == 'auto':
            max_t = self.controller._dry_run_func_est_time(func)
            max_t += safe_factor * max_t
            print(f"Assigned task {task_id}: {func.__name__} a max_t of {max_t}s")
        else:
            #todo: maybe we want to set the default safe_factor to a string like 'default', so if it is explicitly set
            #      as 0.1 this warning will still be thrown out?
            assert type(max_t) in [int, float]
            if safe_factor != 0.1:
                logging.warning("add_task: setting 'safe_margin' only affects automatic time estimates (max_t='auto')")

        self._tasks[task_id] = Task(task_id, func, max_t=max_t, priority=priority, child=child)
        return self._tasks[task_id]

    @staticmethod
    def duplicate_task(task, new_args=None):
        if new_args is None:
            new_args = []
        return Task(task_id=task.task_id,
                    func=task.func,
                    max_t=task.max_t,
                    priority=task.priority,
                    child=task.child,
                    args=new_args)

    def get_task(self):
        return self._cur_task.task_id if self._cur_task is not None else -1

    def run(self):
        self._running = True
        for task in self._tasks.values():
            if not task.child:
                self._bg_q.append(task)  # everything starts as a background task

        while self._running:
            cur_t = self._get_time()

            #try running a scheduled task
            if self._scheduled:
                task = self._scheduled[0]
                resume_t = task.resume_t
                if cur_t >= task.resume_t:  # time to try running the task
                    del self._scheduled[0]  # remove the task
                    self._do(task)  # do the task
                    continue
            else:
                resume_t = 0

            # try running a background task
            if self._bg_q:
                if resume_t:  # see if any tasks can be run before the next scheduled task
                    found_candidate = False
                    for i in range(len(self._bg_q)):
                        if self._bg_q[0].max_t + cur_t >= resume_t:
                            self._bg_q.rotate(-1)  # rotate left
                        else:
                            found_candidate = True
                            break
                    if not found_candidate:
                        self._delay(resume_t - cur_t)  # wait until there's something ready to run
                        continue
                task = self._bg_q.popleft()
                self._do(task)
            else:  # bg deque is empty
                if not self._scheduled:  # if no scheduled tasks
                    break
                else:
                    self._delay(resume_t - cur_t)   # wait until there's something ready to run

        self._cur_task = None
        self._running = False   # todo - some way to externally stop the scheduler

    def _do(self, task):
        """
        :param Task task: do this task
        """

        st = self._get_time()

        try:
            self._cur_task = task
            result = next(task)
            self._cur_task = None
        except StopIteration:
            self._cur_task = None
            return

        self.vprint(f'Started {task.name}: {task} at time {"%.3f" % st}')

        #parse response
        try:
            len(result)
        except TypeError:
            result = [result]

        is_scheduled = False

        for r in result:
            if isinstance(r, ResumeInSignal):
                resume_t = r.wait_t + self._get_time()
                self._schedule_task(resume_t, task)  # add as scheduled task
                is_scheduled = True
                self.vprint(f'scheduling {task.name} at time {"%.3f" % resume_t}')
            elif isinstance(r, MaxTimeSignal):
                task.max_t = r.max_t
            elif isinstance(r, ScheduleChild):
                resume_t = r.wait_t + self._get_time()
                child_id = self._get_next_id(r.func.__name__)
                if child_id in self._tasks:
                    self.vprint(f"using previous task with id {child_id}")
                    child_task = self.duplicate_task(self._tasks[child_id], new_args=r.args)
                    child_task.priority = task.priority
                    if r.max_t is not None:
                        child_task.max_t = r.max_t
                else:
                    child_task = Task(child_id, r.func, r.max_t, task.priority, child=True, args=r.args)
                self._schedule_task(resume_t, child_task)
                self.vprint(f'scheduling {child_task.name} at time {"%.3f" % resume_t}')


        # TODO: can child be scheduled in bg queue?
        if not is_scheduled and not task.child:
            self._bg_q.append(task)  # requeue as background task
           # self.vprint(f'BG queue added {task.name}')

    def _schedule_task(self, new_resume_t, new_task):
        """
        Add a new task to the schedule queue, resolving any scheduling conflicts by priority

        :param new_resume_t:
        :param new_task:
        """

        new_task.desired_resume_t = new_resume_t
        self._scheduled.add(new_task)

        #reorder all tasks according to resume time, respecting conflicts according to priority:

        priority_list = SortedList(key=lambda task: -task.priority, iterable=self._scheduled)  # todo: should this be maintained or made new every time?
        for task in priority_list:
            task.resume_t = task.desired_resume_t

        new_schedule = SortedList(key=lambda task: task.resume_t)

        # place tasks in the new schedule:
        for task in priority_list:
            for i, placed_task in enumerate(new_schedule):
                if task.resume_t < placed_task.resume_t: # two cases: resume_t conflicts or not. If not, does end_t conflict?
                    if i > 0:
                        if task.resume_t < new_schedule[i-1].end_t: #if resume_t conflicts, push back the resume_t til higher priority task is done
                            task.resume_t = new_schedule[i-1].end_t
                    if task.end_t > placed_task.resume_t: # if end_t conflicts, push the resume_t further back and check next placed task
                        task.resume_t = placed_task.end_t
                    else:
                        break

            new_schedule.add(task)

        self._scheduled = new_schedule

    def _get_time(self):
        return self.controller.current_time

    def _delay(self, secs):
        """
        :param float secs: Seconds to delay for.
        """

        self.vprint("waiting:", secs)
        self.controller.delay(secs)


    @staticmethod
    def resume_in(secs):
        """
        :param float secs: Seconds to resume in.
        :return: Resume in signal.
        """
        if secs < 0:
            secs = 0
        return ResumeInSignal(secs)

    @staticmethod
    def max_t(secs):
        """
        Update the max_t property of the current task

        :param float secs: the maximum time before the next yield in seconds.
        :return: Max time signal.
        """
        if secs < 0:
            secs = 0
        return MaxTimeSignal(secs)

    @staticmethod
    def schedule_child(*, func, max_t=None, resume_in, args=None):
        return ScheduleChild(func, max_t, resume_in, args)


class ResumeInSignal:
    def __init__(self, secs):
        assert type(secs) in [float, int]
        self.wait_t = float(secs)

class MaxTimeSignal:
    def __init__(self, secs):
        assert type(secs) in [float, int]
        self.max_t = float(secs)

class ScheduleChild:
    def __init__(self, func, max_t, resume_in, args):
        assert type(resume_in) in [float, int]
        self.func = func
        self.max_t = max_t
        self.wait_t = resume_in
        self.args = args

