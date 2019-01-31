
import os
import shutil
import datetime
import tempfile

import logging
import bibtexparser

from bibed.foundations import lprint, lprint_caller_name  # NOQA
from bibed.preferences import gpod
from bibed.entry import BibedEntry


LOGGER = logging.getLogger(__name__)


class BibedDatabase:

    def __init__(self, filename, store):

        self.filename = filename
        self.store = store

        self.parser = bibtexparser.bparser.BibTexParser(
            ignore_nonstandard_types=False,
            interpolate_strings=False,
            common_strings=True,
        )

        self.writer = bibtexparser.bwriter.BibTexWriter()
        self.writer.indent = '    '

        with open(self.filename, 'r') as bibfile:
            self.bibdb = self.parser.parse_file(bibfile)

        # self.bibdb.comments
        # self.bibdb.preambles
        # self.bibdb.strings

        self.entries = {}

        for index, entry in enumerate(self.bibdb.entries):
            self.entries[entry['ID']] = (entry, index)

    def get_entry_by_key(self, key):

        # assert lprint_caller_name()

        return BibedEntry(self, *self.entries[key])

    def keys(self):

        # assert lprint_caller_name()

        return self.entries.keys()

    def itervalues(self):

        # assert lprint_caller_name()

        for index, entry in enumerate(self.bibdb.entries):
            yield BibedEntry(self, entry, index)

    def values(self):

        # assert lprint_caller_name()

        return [x for x in self.itervalues()]

    def add_entry(self, entry):

        # assert lprint_caller_name()
        # assert lprint(entry)

        new_index = len(self.bibdb.entries)
        entry.index = new_index

        # Insert in BibedDatabase.
        self.entries[entry.key] = (entry.entry, new_index)

        # Idem in bibtexparser database.
        self.bibdb.entries.append(entry.entry)

    def move_entry(self, entry):

        # assert lprint_caller_name()
        # assert lprint(entry)

        old_keys = [x.strip() for x in entry['ids'].split(',')]

        for old_key in old_keys:
            if old_key in self.keys():
                old_index = self.entries[old_key][1]
                break

        # delete and re-insert in BibedDatabase.
        del self.entries[old_key]
        self.entries[entry.key] = (entry.entry, old_index)

        # idem in bibtexparser database.
        del self.bibdb.entries[old_index]
        self.bibdb.entries.insert(old_index, entry.entry)

        assert(entry.index)

    def backup(self):

        # assert lprint_caller_name()
        # assert lprint(self.filename)

        dirname = os.path.dirname(self.filename)
        basename = os.path.basename(self.filename)

        prefix = '{}.save.{}.'.format(
            basename.rsplit('.', 1)[0],
            datetime.date.today().isoformat())

        (handle, new_filename) = tempfile.mkstemp(
            suffix='.bib', prefix=prefix, dir=dirname)

        try:
            shutil.copyfile(self.filename, new_filename)
            shutil.copystat(self.filename, new_filename)

        except Exception:
            LOGGER.exception('Problem while backing up file before save.')

    def write(self):

        # assert lprint_caller_name()
        # assert lprint(self.filename)

        if gpod('backup_before_save'):
            self.backup()

        with open(self.filename, 'w') as bibfile:
                bibfile.write(self.writer.write(self.bibdb))
