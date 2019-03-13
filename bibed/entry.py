
import os
import re
import uuid
import logging
import datetime

import bibtexparser

from bibed.ltrace import (
    lprint, ldebug,
    lprint_caller_name,
    lprint_function_name,
)

from bibed.constants import (
    BibAttrs, FileTypes,
    ENTRY_COLORS,
    JABREF_READ_KEYWORDS,
    JABREF_QUALITY_KEYWORDS,
    MAX_KEYWORDS_IN_TOOLTIPS,
    MINIMUM_BIB_KEY_LENGTH,
    TEXT_MAX_LENGHT_IN_TOOLTIPS,
    TEXT_LENGHT_FOR_CR_IN_TOOLTIPS,
)

from bibed.dtu import isotoday
from bibed.strings import (
    asciize,
    bibtex_clean,
    friendly_filename,
    latex_to_pango_markup,
)
from bibed.locale import _
from bibed.fields import FieldUtils as fu
from bibed.actions import EntryActionStatusMixin
from bibed.completion import (
    DeduplicatedStoreColumnCompletion,
)
from bibed.preferences import defaults, preferences, gpod
from bibed.exceptions import FileNotFoundError
from bibed.gui.helpers import markup_bib_filename
from bibed.gtk import GLib


LOGGER = logging.getLogger(__name__)


# ————————————————————————————————————————————————————————— Regular expressions


KEY_RE = re.compile('^[a-z]([-:_a-z0-9]){2,}$', re.IGNORECASE)

# There is a non-breaking space and an space.
SPLIT_RE = re.compile(' | |:|,|;|\'|"|«|»|“|”|‘|’', re.IGNORECASE)


# ——————————————————————————————————————————————————————————————————— Functions

markup_escape_text = GLib.markup_escape_text
bibtexparser_as_text = bibtexparser.bibdatabase.as_text


def format_edition(edition, short=False):
    ''' Returns Pango Markup for [book] edition. '''

    if edition == 1:
        if short:
            return _('1<sup>st</sup> ed.')
        return _('First edition')

    elif edition == 2:
        if short:
            return _('2<sup>nd</sup> ed.')
        return _('Second edition')

    elif edition == 3:
        if short:
            return _('3<sup>rd</sup> ed.')
        return _('Third edition')

    elif edition == 4:
        if short:
            return _('4<sup>th</sup> ed.')
        return _('Fourth edition')

    elif edition == 5:
        if short:
            return _('5<sup>th</sup> ed.')
        return _('Fifth edition')

    elif edition == 6:
        if short:
            return _('6<sup>th</sup> ed.')
        return _('Sixth edition')

    elif edition == 7:
        if short:
            return _('7<sup>th</sup> ed.')
        return _('Seventh edition')

    elif edition == 8:
        if short:
            return _('8<sup>th</sup> ed.')
        return _('Eighth edition')

    elif edition == 9:
        if short:
            return _('9<sup>th</sup> ed.')
        return _('Nineth edition')

    elif edition == 10:
        if short:
            return _('10<sup>th</sup> ed.')
        return _('Tenth edition')

    else:
        if short:
            return _('{ednum}<sup>th</sup> ed.').format(ednum=edition)

        return _('{ednum}th edition').format(ednum=edition)


# ————————————————————————————————————————————————————————————————————— Classes


class BibedEntry(EntryActionStatusMixin):
    '''

        Free fields from BibLaTeX documentation:

        - list[a–f]
        - user[a–f]
        - verb[a–c]

        Bibed uses `verbb` (for “verbatim-bibed”).
    '''

    VERBB_SEPARATOR    = '|'
    KEYWORDS_SEPARATOR = ','
    TRASHED_FROM       = 'trashedFrom'
    TRASHED_DATE       = 'trashedDate'

    # Will be set by app / css methods.
    COLORS = None

    files = None

    @classmethod
    def new_from_type(cls, entry_type):

        LOGGER.info('New @{0} created'.format(entry_type))

        return cls(
            None,
            {'ENTRYTYPE': entry_type},
        )

    @classmethod
    def new_from_entry(cls, entry_to_dupe):

        new_entry = cls(
            entry_to_dupe.database,
            entry_to_dupe.bib_dict.copy(),
        )

        # It's a new entry. Wipe key, else the old could get overwritten.
        del new_entry.bib_dict['ID']

        LOGGER.info('Entry {0} duplicated into {1}'.format(
            entry_to_dupe, new_entry))

        return new_entry

    @classmethod
    def single_bibkey_pattern_check(cls, pattern):

        if '@@key@@' in pattern:
            return pattern

        else:
            return defaults.accelerators.copy_to_clipboard_single_value

    @classmethod
    def single_bibkey_format(cls, bib_key):

        defls = defaults.accelerators.copy_to_clipboard_single_value
        prefs = preferences.accelerators.copy_to_clipboard_single_value

        if prefs is None:
            pattern = defls

        else:
            pattern = prefs

        pattern = cls.single_bibkey_pattern_check(pattern)

        result = pattern.replace('@@key@@', bib_key)

        return result

    # ———————————————————————————————————————————— Python / dict-like behaviour

    def __init__(self, database, entry):

        # The raw bibtextparser entry.
        self.bib_dict = entry

        # Our BibedDatabase.
        self.database = database

        self.__internal_verbb = {
            key: value
            for (key, value) in (
                line.split(':')
                for line in self.__internal_split_tokens(
                    self.bib_dict.get('verbb', ''),
                    separator=self.VERBB_SEPARATOR
                )
            )
        }

        # Proxy keywords here for faster operations.
        self.__internal_keywords = self.__internal_split_tokens(
            self.bib_dict.get('keywords', ''))

    def __setitem__(self, item_name, value):
        ''' Translation Bibed ←→ bibtexparser. '''

        # TODO: keep this method or not ?
        #       we have more and more proxy specifics.
        #       Keeping this could lead to inconsistencies and bugs.

        value = value.strip()
        item_name = self.__internal_translate(item_name)

        if value is None or value == '':
            try:
                del self.bib_dict[item_name]
            except KeyError:
                # Situation: the field was initially empty. Then, in the
                # editor dialog, the field was filled, then emptied before
                # dialog close. Solution: don't crash.
                pass

            else:
                LOGGER.info('{0}: removing field {1} now empty.'.format(
                    self, item_name))

        else:
            self.bib_dict[item_name] = value

    def __getitem__(self, item_name):

        # TODO: keep this method or not ?
        #       we have more and more proxy specifics.
        #       Keeping this could lead to inconsistencies and bugs.

        return self.bib_dict[self.__internal_translate(item_name)]

    def __str__(self):

        return 'Entry {}@{}{}'.format(
            self.key, self.type,
            ' NEW' if self.database is None
            else ' in {}'.format(
                self.database))

    def copy(self):
        ''' Return a copy of self, with no database and. '''

        return BibedEntry(None, self.bib_dict.copy())

    # ——————————————————————————————————————————————————————————————— Internals

    def __internal_split_tokens(self, value, separator=None):

        if separator is None:
            separator = self.KEYWORDS_SEPARATOR

        return [
            expression.strip()
            for expression in value.split(separator)
            if expression.strip() != ''
        ]

    def __internal_add_keywords(self, keywords):

        self.__internal_keywords.extend(keywords)

        self.bib_dict['keywords'] = ', '.join(self.__internal_keywords)

    def __internal_remove_keywords(self, keywords):

        for kw in keywords:
            try:
                self.__internal_keywords.remove(kw)

            except IndexError:
                pass

        self.bib_dict['keywords'] = ', '.join(self.__internal_keywords)

    def __internal_translate(self, name):
        ''' Translation Bibed ←→ bibtexparser. '''

        if name == 'key':
            return 'ID'

        # Do not translate `type`.
        # We have a `type` field for thesis, etc.
        # elif name == 'type':
        #     return 'ENTRYTYPE'

        return name

    def __internal_set_verbb(self):
        ''' update `verbb` BibLaTeX field with our internal values. '''

        # assert lprint_function_name()

        self.bib_dict['verbb'] = self.VERBB_SEPARATOR.join(
            ':'.join((key, value, ))
            for (key, value) in self.__internal_verbb.items()
        )

    def __escape_for_tooltip(self, text):
        ''' Escape esperluette and other entities for GTK tooltip display. '''

        # .replace('& ', '&amp; ')

        text = markup_escape_text(text)

        # TODO: re.sub() sur texttt, emph, url, etc.
        #       probably some sort of TeX → Gtk Markup.
        #       and code the opposite for rich text
        #       editor on abstract / comment.

        return text

    def __clean_for_display(self, name):
        ''' Be agressive against BibLaTeX and bibtexparser, for GUI display. '''

        # TODO: do better than this.
        field = bibtexparser_as_text(self.bib_dict.get(name, ''))

        if field == '':
            return ''

        if field.startswith('{') and field.endswith('}'):
            field = field[1:-1]

        # Still in persons fields, we have can have more than one level of {}s.
        if '{' in field and '\\' not in field:
            # but if we've got some backslashes, we have latex commands.
            # Don't remove them, else latex_to_pango_markup() will fail.
            field = field.replace('{', '').replace('}', '')

        field = field.replace('\\', '')

        # WARNING: order is important, else pango markup gets escaped…
        field = markup_escape_text(field)
        field = latex_to_pango_markup(field, reverse=False)

        return field

    # ———————————————————————————————————————————————————— Methods & attributes

    def fields(self):

        return self.bib_dict.keys()

    def set_timestamp_and_owner(self):

        if gpod('bib_add_timestamp'):
            current_ts = self.bib_dict.get('timestamp', None)

            if current_ts is None or gpod('bib_update_timestamp'):
                self.bib_dict['timestamp'] = isotoday()

        owner_name = preferences.bib_owner_name

        if owner_name:
            owner_name = owner_name.strip()

            if gpod('bib_add_owner'):
                current_owner = self.bib_dict.get('owner', None)

                if current_owner is None or gpod('bib_update_owner'):
                    self.bib_dict['owner'] = owner_name

    def get_field(self, name, default=None):
        ''' Used massively and exclusively in editor dialog and data store. '''

        # We should use properties for these attributes.
        if name == 'keywords':
            return ', '.join([x for x in self.keywords if x.strip()])

        name = self.__internal_translate(name)

        if default is None:

            value = self.bib_dict.get(name, None)

            if value is not None:
                return bibtexparser_as_text(value)

            return None

        return bibtexparser_as_text(self.bib_dict.get(name, default))

    def set_field(self, name, value):

        if value in (None, '', [], ) or len(value) == 0:
            # remove field. Doing this here is
            # required by field mechanics in GUI.
            try:
                del self.bib_dict[name]

            except KeyError:
                pass

            return

        name = self.__internal_translate(name)

        try:
            setter = getattr(self, 'set_field_{}'.format(name))

        except AttributeError:
            self.bib_dict[name] = value

        else:
            setter(value)

    def set_field_keywords(self, value):
        ''' Either an str instance, or [str, ] (must be a list in that case). '''

        if isinstance(value, str):
            kw = self.__internal_split_tokens(value)

        else:
            assert isinstance(value, list)
            kw = value

        self.__internal_keywords = kw + [self.read_status] + [self.quality]

        # Flatten for bibtexparser
        flattened_keywords = (','.join(
            # If no read_status or quality, we need to “re-cleanup”
            kw for kw in self.__internal_keywords if kw.strip() != ''
        )).strip()

        if flattened_keywords != '':
            self.bib_dict['keywords'] = flattened_keywords

        else:
            # remove now-empty field.
            del self.bib_dict['keywords']

    # —————————————————————————————————————————————————————————————— properties

    @property
    def is_trashed(self):

        # assert lprint_function_name()

        return self.TRASHED_FROM in self.__internal_verbb

    @property
    def trashed_informations(self):
        ''' Return trash-related information. '''

        # assert lprint_function_name()

        try:
            return (
                self.__internal_verbb[self.TRASHED_FROM],
                self.__internal_verbb[self.TRASHED_DATE],
            )
        except KeyError:
            return None

    def set_trashed(self, is_trashed=True):

        # assert lprint_function_name()
        # assert lprint(is_trashed)

        if is_trashed:
            assert not self.is_trashed

            self.__internal_verbb[self.TRASHED_FROM] = self.database.filename
            self.__internal_verbb[self.TRASHED_DATE] = isotoday()

        else:
            assert self.is_trashed

            del self.__internal_verbb[self.TRASHED_FROM]
            del self.__internal_verbb[self.TRASHED_DATE]

        self.__internal_set_verbb()

    @property
    def type(self):

        return self.bib_dict['ENTRYTYPE']

    @type.setter
    def type(self, value):

        self.bib_dict['ENTRYTYPE'] = value

    @property
    def key(self):

        return self.bib_dict.get('ID', None)

    @key.setter
    def key(self, value):

        # TODO: check key validity on the fly ?
        #       this should be implemented higher
        #       in the GUI check_field*() methods.
        self.bib_dict['ID'] = value

    @property
    def ids(self):

        return [
            x.strip()
            for x in self.bib_dict.get('ids', '').split(',')
            if x.strip() != ''
        ]

    @ids.setter
    def ids(self, value):

        self.bib_dict['ids'] = ', '.join(v for v in value
                                         if v not in (None, ''))

    @property
    def title(self):

        return self.__clean_for_display('title')

    @property
    def comment(self):

        return self.bib_dict.get('comment', '')

    @property
    def abstract(self):

        return self.bib_dict.get('abstract', '')

    @comment.setter
    def comment(self, value):

        self.bib_dict['comment'] = value

    @property
    def author(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('author')

    @property
    def editor(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('editor')

    @property
    def year(self):
        ''' Will try to return year field or year part of date field. '''

        # assert lprint_caller_name(levels=5)

        year = self.bib_dict.get('year', None)

        if year is None:
            date = self.bib_dict.get('date', None)

            if date is None:
                return None

            try:
                # TODO: handle non-ISO date gracefully.
                return int(date.split('-')[0])

            except Exception:
                return None

        else:
            return int(year)

    @property
    def keywords(self):
        ''' Return entry keywords without JabRef internals. '''

        # HEADS UP: copy(), else we alter __internal_keywords!
        keywords = self.__internal_keywords[:]

        for kw in JABREF_QUALITY_KEYWORDS + JABREF_READ_KEYWORDS:
            try:
                keywords.remove(kw)

            except ValueError:
                pass

        return keywords

    @property
    def quality(self):
        ''' Get the JabRef quality from keywords. '''

        keywords = self.__internal_keywords

        for kw in JABREF_QUALITY_KEYWORDS:
            if kw in keywords:
                return kw

        return ''

    @property
    def read_status(self):
        ''' Get the JabRef read status from keywords. '''

        keywords = self.__internal_keywords

        for kw in JABREF_READ_KEYWORDS:
            if kw in keywords:
                return kw

        # NO keyword means book unread.
        # See constants.py
        return ''

    @property
    def short_display(self):
        ''' Used in GUI dialogs (thus uses Pango markup). '''

        assert getattr(defaults.types.labels, self.type)

        if self.is_trashed:
            trashedFrom, trashedDate = self.trashed_informations
        else:
            trashedFrom, trashedDate = None, None

        return (
            '{type} <b><i>{title}</i></b> '
            'by <b>{author}</b>{in_or_by}{year}{trashed}'.format(
                type=self.type_label,

                title=(
                    (self.title[:24] + (self.title[24:] and ' […]'))
                    if self.title else _('No title')
                ),
                author=(
                    self.author if self.author else _('No author')
                ),

                in_or_by=(
                    ' in <i>{}</i>'.format(self.col_in_or_by)
                    if self.col_in_or_by else ''
                ),

                year=(
                    ' ({})'.format(self.year)
                    if self.year else ''
                ),

                trashed=_(' <span color="grey">(trashed on {tDate} from <span face="monospace">{tFrom}</span>)</span>').format(
                    tFrom=GLib.markup_escape_text(
                        friendly_filename(trashedFrom)),
                    tDate=trashedDate
                ) if self.is_trashed else '',
            )
        )

    # ——————————————————————————————————————————————————————— translated labels

    @property
    def type_label(self):

        return self.type_label_with_mnemonic.replace('_', '')

    @property
    def type_label_with_mnemonic(self):
        ''' Translated type label. '''

        return _(getattr(defaults.types.labels, self.type))

    # ——————————————————————————————————————————————————————— ListStore Columns

    @property
    def col_type(self):

        # subtype = self.bib_dict.get('entrysubtype', None)

        # if subtype is not None:
        #     return _(subtype)

        # etype = self.bib_dict.get('type', None)

        # if etype is not None:
        #     return _(etype)

        # return _(getattr(defaults.types.labels,
        #                  self.bib_dict['ENTRYTYPE'])).replace('_', '')

        return self.bib_dict['ENTRYTYPE']

    @property
    def col_author(self):

        # TODO: handle {and}, "and", and other author particularities.

        author = self.author

        if author in (None, '', ):
            editor = self.editor

            if editor in (None, '', ):
                return ''

            else:
                return _('<span color="grey">{} (Ed.)</span>').format(
                    markup_escape_text(bibtex_clean(editor)))

        else:
            return markup_escape_text(bibtex_clean(author))

    @property
    def col_in_or_by(self):

        fields_to_try = (
            'journaltitle',
            'publisher',
            'howpublished',
            'institution',
            'organization',
            'booktitle',
            'isbn',

            # backward compatible field name for JabRef.
            'journal',

            # other backward compatible fields.
            'school',
        )

        for field_name in fields_to_try:

            field_value = self.__clean_for_display(field_name)

            if field_value:
                return field_value

        return ''

    @property
    def col_read_status(self):

        return self.read_status

    @property
    def col_quality(self):

        return self.quality

    @property
    def col_abstract_or_comment(self):

        if self.comment:
            if self.abstract:
                return 'both'
            else:
                return 'comment'
        else:
            if self.abstract:
                return 'abstract'
            else:
                return ''

    @property
    def col_title(self):

        title = self.__clean_for_display('title')

        if len(title) <= 48:
            subtitle = self.__clean_for_display('subtitle')

            if subtitle:
                title += _(': <i>{}</i>').format(subtitle)

        edition = self.bib_dict.get('edition', None)

        if edition is not None and edition != '':
            title += ' <span color="grey">({})</span>'.format(
                format_edition(edition, short=True))

        return title

    @property
    def col_year(self):

        return self.year

    # —————————————————————————————————————————— search columns (not displayed)

    @property
    def col_subtitle(self):

        # No need to escape, this column is not displayed.
        return self.bib_dict.get('subtitle', '')

    @property
    def col_comment(self):

        # No need to escape, this column is not displayed.
        return self.bib_dict.get('comment', '')

    @property
    def col_abstract(self):

        # No need to escape, this column is not displayed.
        return self.bib_dict.get('abstract', '')

    @property
    def col_keywords(self):

        # No need to escape, this column is not displayed.
        return ','.join(self.keywords)

    # —————————————————————————————————————————————— Special: tooltip & context

    @property
    def context_color(self):

        if self.action_status is not None:
            return self.COLORS[self.action_status]

        else:
            return self.COLORS[self.database.filetype]

    @property
    def col_tooltip(self):

        esc = self.__escape_for_tooltip
        is_trashed = self.is_trashed

        def strike(text):
            return (
                '<s>{}</s>'.format(text)
                if is_trashed else text
            )

        tooltips = []

        subtitle = self.get_field('subtitle', default='')
        year     = self.year

        base_tooltip = (
            '<big><i>{title}</i></big>\n{subtitle}'
            'by <b>{author}</b>'.format(
                title=strike(self.col_title),
                subtitle='<i>{}</i>\n'.format(strike(esc(subtitle)))
                if subtitle else '',
                author=esc(self.col_author),
            )
        )

        if self.col_in_or_by:
            base_tooltip += ', published in <b><i>{in_or_by}</i></b>'.format(
                in_or_by=esc(self.col_in_or_by))

        if year:
            base_tooltip += ' ({year})'.format(year=year)

        tooltips.append(base_tooltip)

        if self.comment:
            comment = self.comment
            comment_cr = (
                '\n'
                if len(comment) > TEXT_LENGHT_FOR_CR_IN_TOOLTIPS
                else ' '
            )
            comment = comment[:TEXT_MAX_LENGHT_IN_TOOLTIPS] \
                + (comment[TEXT_MAX_LENGHT_IN_TOOLTIPS:] and '[…]')

            tooltips.append('<b>Comment:</b>{cr}{comment}'.format(
                cr=comment_cr,  # Note the space.
                comment=latex_to_pango_markup(esc(comment))))

        abstract = self.get_field('abstract', default='')

        if abstract:
            abstract = abstract[:TEXT_MAX_LENGHT_IN_TOOLTIPS] \
                + (abstract[TEXT_MAX_LENGHT_IN_TOOLTIPS:] and '[…]')

            tooltips.append('<b>Abstract</b>:\n{abstract}'.format(
                abstract=latex_to_pango_markup(esc(abstract))))

        keywords = self.keywords

        if keywords:
            if len(keywords) > MAX_KEYWORDS_IN_TOOLTIPS:
                kw_text = '{}{}'.format(
                    ', '.join(keywords[:MAX_KEYWORDS_IN_TOOLTIPS]),
                    ', and {} other(s).'.format(
                        len(keywords[MAX_KEYWORDS_IN_TOOLTIPS:])
                    ),
                )
            else:
                kw_text = ', '.join(keywords)

            tooltips.append('<b>Keywords:</b> {}'.format(kw_text))

        url = self.get_field('url', '')

        if url:
            tooltips.append('<b>URL:</b> <a href="{url}">{url}</a>'.format(url=esc(url)))

        if is_trashed:
            tFrom, tDate = self.trashed_informations

            missing = False

            try:
                tType = BibedEntry.files.get_filetype(tFrom)

            except FileNotFoundError:
                # Most probably a deleted database, but could be also (99%)
                # that the current method is called while the origin BIB file
                # is unloaded. This happens notably at application start.

                if os.path.exists(tFrom):
                    tType = FileTypes.USER

                else:
                    tType = FileTypes.NOTFOUND
                    missing = True

            # TODO: what if trashed from QUEUE? FileTypes must be dynamic!
            tFrom = markup_bib_filename(
                tFrom, tType, parenthesis=True, missing=missing)

            tooltips.append('Trashed from {tFrom} on {tDate}.'.format(
                tFrom=tFrom, tDate=tDate))

        else:
            timestamp = self.get_field('timestamp', default='')

            if timestamp:
                tooltips.append('Added to {filename} on <b>{timestamp}</b>.'.format(
                    filename=markup_bib_filename(
                        self.database.filename,
                        self.database.filetype),
                    timestamp=timestamp))

            else:
                tooltips.append('Stored in {filename}.'.format(
                    filename=markup_bib_filename(
                        self.database.filename,
                        self.database.filetype,
                        parenthesis=True)))

        final_tooltip_string = '\n\n'.join(tooltips)

        return final_tooltip_string

    # ——————————————————————————————————————————————————— Completion properties

    @property
    def comp_journaltitle(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('journaltitle')

    @property
    def comp_editor(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('editor')

    @property
    def comp_publisher(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('publisher')

    @property
    def comp_series(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('series')

    @property
    def comp_type(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('type')

    @property
    def comp_howpublished(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('howpublished')

    @property
    def comp_entrysubtype(self):

        # TODO: handle {and}, "and", and other author particularities.

        return self.__clean_for_display('entrysubtype')

    # ————————————————————————————————————————————————————————————————— Methods

    def update_fields(self, **kwargs):

        # assert lprint_function_name()
        # assert lprint(kwargs)

        update_store = kwargs.pop('update_store', True)

        LOGGER.debug('{0}.update_fields({1})'.format(self, kwargs))

        for field_name, field_value in kwargs.items():
            # Use set_field() to automatically handle special cases.
            self.set_field(field_name, field_value)

        self.set_timestamp_and_owner()

        if update_store:
            # TODO: map entry fields to data_store fields?
            #       for now it's not worth it.
            self.update_store_row()

    def update_store_row(self, fields=None):

        if self.database:
            LOGGER.debug('{0}.update_store_row({1})'.format(self, fields))
            # If we have no database, entry is not yet created.
            # The data store will be updated later by add_entry().
            BibedEntry.files.data.update_entry(self, fields)

    def pivot_key(self):
        ''' Special method to update an entry key in the data store. '''

        self.database.data_store.update_entry(
            self, {BibAttrs.KEY: self.key}, old_keys=self.ids)

    def toggle_quality(self):

        if self.quality == '':
            self.__internal_add_keywords([JABREF_QUALITY_KEYWORDS[0]])

        else:
            self.__internal_remove_keywords([JABREF_QUALITY_KEYWORDS[0]])

        self.set_timestamp_and_owner()

        self.update_store_row({BibAttrs.QUALITY: self.quality})

    def cycle_read_status(self):

        read_status = self.read_status

        if read_status == '':
            self.__internal_add_keywords([JABREF_READ_KEYWORDS[0]])

        elif read_status == JABREF_READ_KEYWORDS[0]:
            self.__internal_remove_keywords([JABREF_READ_KEYWORDS[0]])
            self.__internal_add_keywords([JABREF_READ_KEYWORDS[1]])

        else:
            self.__internal_remove_keywords([JABREF_READ_KEYWORDS[1]])

        self.set_timestamp_and_owner()

        self.update_store_row({BibAttrs.READ: self.read_status})

    def delete(self, write=True):

        self.database.delete_entry(self)

        if write:
            self.database.write()


class EntryKeyGenerator:

    usable_fields = (
        'author',
        'title',
        'year',
    )

    @staticmethod
    def format_title(title):
        ''' Return first letter of each word. '''

        words = (word.strip() for word in SPLIT_RE.split(title))

        return asciize(''.join(
            word[0] for word in words if word
        ), aggressive=True).lower()

    @staticmethod
    def format_author(author):

        def get_last_name(name):

            try:
                return name.rsplit(' ', 1)[1]

            except IndexError:
                # No space, no split, only one name part.
                return name

        names = [name.strip() for name in author.split('and')]

        names_count = len(names)

        if names_count > 2:
            last_names = (get_last_name(name) for name in names)

            # Take the 2 first letters of each author last name.
            last_name = ''.join(
                asciize(name[:2], aggressive=True) for name in last_names)

        elif names_count == 2:

            last_names = (get_last_name(name) for name in names)

            # Take the 3 first letters of each author last name.
            last_name = ''.join(
                asciize(name[:3], aggressive=True) for name in last_names)

        else:
            last_name = asciize(get_last_name(names[0]), aggressive=True)

        return last_name.lower()

    @staticmethod
    def generate_new_key(entry, suffix=None):

        assert isinstance(entry, BibedEntry)
        assert suffix is None or int(suffix)

        if suffix is None:
            suffix = ''

        else:
            # return someting like '-03'
            suffix = '-{:02d}'.format(suffix)

        author = entry.author
        title = entry.title
        year = entry.year

        if year is None:
            year = ''

        if entry.type not in (
                'book', 'article', 'misc', 'booklet', 'thesis', 'online'):
            prefix = '{}:'.format(entry.type[0].lower())

        elif entry.type in ('misc', ):
            howpublished = entry.get_field('howpublished', '')
            prefix = '{}:'.format(howpublished[0].lower()) if howpublished else ''

        else:
            prefix = ''

        if not author and not title:
            # Nothing to make a key from…
            return uuid.uuid4().hex

        if not title:
            result = '{prefix}{author}{year}{suffix}'.format(
                prefix=prefix, author=EntryKeyGenerator.format_author(author),
                year=year, suffix=suffix)

        elif not author:
            result = '{prefix}{title}{year}{suffix}'.format(
                prefix=prefix, title=EntryKeyGenerator.format_title(title),
                year=year, suffix=suffix)

        else:
            # We've got an author and a title
            result = '{prefix}{author}-{title}{suffix}'.format(
                prefix=prefix, author=EntryKeyGenerator.format_author(author),
                title=EntryKeyGenerator.format_title(title), suffix=suffix)

        result_len = len(result)

        if result_len < MINIMUM_BIB_KEY_LENGTH:
            result = '{result}{padding}'.format(
                result=result,
                padding=uuid.uuid4().hex[:MINIMUM_BIB_KEY_LENGTH - result_len]
            )

        return result


generate_new_key = EntryKeyGenerator.generate_new_key


class EntryFieldBuildMixin:
    ''' Helpers for field building. '''

    def build_field_author_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.AUTHOR))

    def build_field_journaltitle_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.JOURNALTITLE))

    def build_field_editor_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.EDITOR))

    def build_field_publisher_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.PUBLISHER))

    def build_field_series_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.SERIES))

    def build_field_type_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.TYPEFIELD))

    def build_field_howpublished_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.HOWPUBLISHED))

    def build_field_entrysubtype_post(self, all_fields, field_name, field, store):

        field.set_completion(DeduplicatedStoreColumnCompletion(
            field, store, BibAttrs.ENTRYSUBTYPE))

    def build_field_entryset_post(self, all_fields, field_name, field, store):

        # TODO: add a custom entry key completer.

        pass

    def build_field_related_post(self, all_fields, field_name, field, store):

        # TODO: add a custom entry key completer.

        pass

    def build_field_keywords_post(self, all_fields, field_name, field, store):

        # TODO: add a custom keyword completer for a textview.

        pass


class EntryFieldCheckMixin:
    ''' This class is meant to be subclassed by any Window/Dialog that checks entries.

        .. seealso:: :class:`~bibed.gui.BibedEntryDialog`.
    '''

    # ——————————————————————————————————————————————————————————— Check methods

    def check_field_year(self, all_fields, field_name, field, field_value):

        if fu.value_is_empty(field_value):
            # User has removed the date after having
            # typed something. Everything is fine.
            return

        field_value = field_value.strip()

        if len(field_value) != 4:
            return (
                'Invalid year.'
            )

        try:
            _ = int(field_value)

        except Exception as e:
            return (
                'Invalid year, not understood: {exc}.'.format(exc=e)
            )

    def check_field_key(self, all_fields, field_name, field, field_value):

        field_value = field_value.strip()

        if KEY_RE.match(field_value) is None:
            return (
                'Key must start with a letter, contain only letters and numbers; special characters allowed: “-”, “:” and “_”.'
            )

        has_key = self.files.has_bib_key(field_value)

        if has_key:
            return (
                'Key already taken in <span '
                'face="monospace">{filename}</span>. '
                'Please choose another one.').format(
                    filename=os.path.basename(has_key)
            )

    def check_field_date(self, all_fields, field_name, field, field_value):

        if fu.value_is_empty(field_value):
            # User has removed the date after having
            # typed something. Everything is fine.
            return

        error_message = (
            'Invalid ISO date. '
            'Please type a date in the format YYYY-MM-DD.'
        )

        if len(field_value) < 10:
            return error_message

        try:
            _ = datetime.date.fromisoformat(field_value)

        except Exception as e:
            return '{error_message}\nExact error is: {exception}'.format(
                error_message=error_message, exception=e)

    check_field_urldate = check_field_date

    def check_field_url(self, all_fields, field_name, field, field_value):

        if fu.value_is_empty(field_value):
            # The URL was made empty after beiing set. Empty the date.
            fu.field_make_empty(all_fields['urldate'])
            return

        fu.field_set_date_today(all_fields['urldate'])

    # ————————————————————————————————————————————————————————————— Fix methods

    def fix_field_key(self, all_fields, field_name, field, field_value, entry, files):
        ''' Create a valid key. '''

        assert entry
        assert files

        new_key = generate_new_key(entry)
        counter = 1

        while files.has_bib_key(new_key):

            new_key = generate_new_key(entry, counter)
            counter += 1

        return new_key
