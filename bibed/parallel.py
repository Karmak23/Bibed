
import logging

import threading
from threading import Thread, Event

from bibed.ltrace import lprint

from bibed.gtk import Gtk


LOGGER = logging.getLogger(__name__)


class BibedEventThread(Thread):

    def __init__(self, event, *args, **kwargs):

        self.event = event
        self.target = kwargs.get('target')

        super().__init__(*args, **kwargs)

    def run(self):

        super().run()

        if self.event is not None:
            self.event.set()

        LOGGER.debug('BibedEventThread({}): finished.'.format(
            self.target.__name__))


# ————————————————————————————————————————————————————————————————————— Helpers
# https://wiki.gnome.org/Projects/PyGObject/Threading


def parallel_status():

    return '{}, {} alive: {}'.format(
        threading.current_thread(),
        threading.active_count(),
        threading.enumerate(),
    )


def run_and_wait_on(func, *args, **kwargs):

    event = Event()
    # start thread on func with event

    thread = BibedEventThread(event, target=func, args=args, kwargs=kwargs)
    thread.start()

    while not event.is_set():
        while Gtk.events_pending():
            Gtk.main_iteration()

    thread.join()


def run_in_background(func, event=None, *args, **kwargs):
    ''' Start a daemon thread and forget it. It should run a finite function.

        :param event: a :class:`~threading.Event` instance. Can be ``none``.
            If given, the event will be set when the daemon thread exits.
    '''

    thread = BibedEventThread(event, target=func, args=args, kwargs=kwargs)
    thread.daemon = True
    thread.start()
