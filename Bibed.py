#!/usr/bin/env python

import sys
import logging
from bibed.app import BibEdApplication

LOGGER = logging.getLogger(__name__)


def setup_logging(level=logging.INFO):
    root = logging.getLogger()
    root.setLevel(level)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    ch.setFormatter(formatter)
    root.addHandler(ch)


if __name__ == "__main__":
    setup_logging()
    app = BibEdApplication()
    exit_status = app.run(sys.argv)
    sys.exit(exit_status)
