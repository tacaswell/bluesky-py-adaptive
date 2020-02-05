from bluesky_adaptive.runners import generator
from bluesky_adaptive.callback import AdaptiveCallback
import operator
from functools import reduce
import bluesky.preprocessors as bpp
import bluesky.plan_stubs as bps
import itertools
from queue import Queue


def learner_plan(dets, motors, learner, goal, *, md=None):

    exogenous_keys = tuple(reduce(operator.add, (d.hints["fields"] for d in dets), []))
    dimensions = [(motor.hints["fields"], "primary") for motor in motors]
    endogenous_keys = [d for ((d,), s) in dimensions]
    _md = {"hints": {}}
    _md.update(md or {})
    _md["hints"].setdefault("dimensions", dimensions)

    @bpp.stage_decorator(dets + motors)
    @bpp.run_decorator(md=_md)
    def inner():

        gen = generator(learner, goal)
        # have to "prime the pump"
        xy = None
        while True:
            try:
                x = gen.send(xy)
            except StopIteration:
                break
            yield from bps.mov(*itertools.chain(*zip(motors, x)))
            ret = yield from bps.trigger_and_read(dets + motors)

            # handle simulated case
            if ret:
                y = tuple(ret[k]["value"] for k in exogenous_keys)
                x = tuple(ret[k]["value"] for k in endogenous_keys)
            else:
                y = tuple(x[:1]) * len(exogenous_keys)
                x = x

            xy = (x, y)

    return (yield from inner())


def learner_callback_plan(dets, motors, learner, goal, **kwargs):
    queue = Queue()
    callback = AdaptiveCallback(learner, goal, queue)

    return (
        yield from bpp.subs_wrapper(
            learner_queue(dets, motors, queue, **kwargs), callback
        )
    )


def learner_queue(dets, motors, queue, *, md=None, step_plan=None):

    if step_plan is None:

        def step_plan(motors, x):
            yield from bps.mov(*itertools.chain(*zip(motors, x)))

    dimensions = [(motor.hints["fields"], "primary") for motor in motors]
    _md = {"hints": {}}
    _md.update(md or {})
    _md["hints"].setdefault("dimensions", dimensions)

    @bpp.stage_decorator(dets + motors)
    @bpp.run_decorator(md=_md)
    def inner():
        while True:
            x = queue.get(timeout=1)
            if x is None:
                return

            yield from step_plan(motors, x)
            yield from bps.trigger_and_read(dets + motors)

    return (yield from inner())
