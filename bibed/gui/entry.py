
import os
import logging

from bibed.foundations import ltrace_function_name

from collections import OrderedDict
from threading import Lock

from bibed.constants import (
    BOXES_BORDER_WIDTH,
    GRID_COLS_SPACING,
    GRID_ROWS_SPACING,
    GRID_BORDER_WIDTH,
    # GENERIC_HELP_SYMBOL,
)

from bibed.preferences import defaults, preferences, gpod

from bibed.gui.helpers import (
    widget_properties,
    label_with_markup,
    in_scrolled,
    add_classes,
    find_child_by_name,
    # frame_defaults,
    # scrolled_textview,
    build_entry_field_labelled_entry,
    build_entry_field_textview,
    # build_help_popover,
)

from bibed.gui.gtk import GLib, Gtk, Gio

LOGGER = logging.getLogger(__name__)


class BibedEntryDialog(Gtk.Dialog):

    def __init__(self, parent, entry):

        if entry.key is None:
            title = "Create new @{0}".format(entry.type)
        else:
            try:
                mnemonic = getattr(defaults.fields.mnemonics,
                                   entry.type).label

            except AttributeError:
                # Poor man's solution.
                mnemonic = entry.type.title()

            title = "Edit {0} {1}".format(mnemonic, entry.key)

        super().__init__(title, parent, use_header_bar=True)

        # Will be filled by GLib.idle_add() in *save*() methods.
        self.save_trigger_source = None
        self.save_lock = Lock()

        # TODO: This is probably a dupe with Gtk's get_parent(),
        #       but despite super() beiing given parent arg,
        #       get_parent() returns None in
        #       on_rename_confirm_clicked().
        self.parent = parent

        self.set_modal(True)
        self.set_default_size(500, 500)
        self.set_border_width(BOXES_BORDER_WIDTH)
        self.connect('hide', self.on_entry_hide)

        self.entry = entry

        # direct access to fields for *save() methods.
        self.fields = OrderedDict()

        # This set() will be updated by widget callbacks,
        # and used in self.update_entry_and_save_file().
        self.changed_fields = set()

        # Direct access to fields grids.
        self.grids = {}

        self.box = self.get_content_area()

        self.setup_headerbar()
        self.setup_key_entry()
        self.setup_stack()
        self.setup_help_label()

        self.show_all()

        # Focus the first sensitive field
        # (eg. 'key' for new entries, 'title' for existing).
        for val in self.fields.values():
            if val.get_sensitive():
                val.grab_focus()
                break

    def setup_headerbar(self):

        self.headerbar = self.get_header_bar()

        bbox = widget_properties(
            Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL),
            classes=['linked'],
        )

        button = Gtk.Button()
        button.add(Gtk.Arrow(arrow_type=Gtk.ArrowType.LEFT,
                             shadow_type=Gtk.ShadowType.NONE))
        bbox.add(button)

        self.btn_previous = button
        self.btn_previous.connect('clicked', self.on_previous_clicked)

        button = Gtk.Button()
        button.add(Gtk.Arrow(arrow_type=Gtk.ArrowType.RIGHT,
                             shadow_type=Gtk.ShadowType.NONE))
        bbox.add(button)

        self.btn_next = button
        self.btn_next.connect('clicked', self.on_next_clicked)

        self.headerbar.pack_start(bbox)

        if self.entry.key is None:
            # We need to wait after the entry is first saved.
            bbox.set_sensitive(False)

        if not gpod('bib_auto_save'):
            btn_save = widget_properties(
                Gtk.Button('Save'),
                expand=False,
                classes=['suggested-action'],
                connect_to=self.on_save_clicked,
                default=True,
            )

            self.headerbar.pack_end(btn_save)

        btn_switch_type = widget_properties(Gtk.Button(), expand=False)
        btn_switch_type.connect('clicked', self.on_switch_type_clicked)
        icon = Gio.ThemedIcon(name='network-transmit-receive-symbolic')
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        btn_switch_type.add(image)
        btn_switch_type.set_tooltip_markup('Switch entry type')

        self.headerbar.pack_end(btn_switch_type)

    def setup_help_label(self):

        if gpod('bib_auto_save'):
            self.box.add(widget_properties(label_with_markup(
                '<span foreground="grey">Entry is automatically saved; '
                'just hit <span face="monospace">ESC</span> or close '
                'the window when you are done.'
                '</span>',
                xalign=0.5),
                expand=Gtk.Orientation.HORIZONTAL,
                halign=Gtk.Align.CENTER,
                margin_top=5))

    def setup_key_entry(self):

        def build_key_rename_popover(attached_to):

            popover = Gtk.Popover()

            vbox = widget_properties(
                Gtk.Box(orientation=Gtk.Orientation.VERTICAL),
                margin=BOXES_BORDER_WIDTH,
            )

            label = widget_properties(
                label_with_markup(
                    'Type new entry key.\n'
                    'Use button to generate\n'
                    'a new one from entry data.',
                    xalign=0.5,
                ),
                expand=True,
                halign=Gtk.Align.CENTER,
            )

            vbox.pack_start(label, False, True, 0)

            # ——————————————————————————————————————————— Entry+Auto-compute

            entry = widget_properties(
                Gtk.Entry(name='new_entry_key'),
                expand=Gtk.Orientation.HORIZONTAL,
                # margin=BOXES_BORDER_WIDTH,
                halign=Gtk.Align.FILL,
                valign=Gtk.Align.CENTER,
                width=300,
            )

            btn_compute = widget_properties(Gtk.Button(), expand=False)
            btn_compute.connect('clicked', self.on_key_compute_clicked, entry)
            icon = Gio.ThemedIcon(name='system-run-symbolic')
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            btn_compute.add(image)
            btn_compute.set_tooltip_markup(
                'Compute a key from already filled entry fields.'
            )

            hbox = widget_properties(
                Gtk.HBox(),
                expand=False,
                halign=Gtk.Align.CENTER,
                classes=['linked'],
            )

            hbox.add(entry)
            hbox.add(btn_compute)

            vbox.pack_start(hbox, False, True, GRID_ROWS_SPACING)

            # ————————————————————————————————————————— error label (hidden)

            error_label = widget_properties(
                Gtk.Label(name='error_label'),
                expand=True,
                halign=Gtk.Align.CENTER,
            )

            vbox.pack_start(error_label, False, True, 0)

            # ————————————————————————— popover confirmation / close button

            btn_confirm_rename = widget_properties(
                Gtk.Button('Change Key'),
                classes=['suggested-action'],
                connect_to=self.on_rename_confirm_clicked,
                default=True,
                connect_args=(entry, popover, ),
            )

            vbox.pack_start(btn_confirm_rename, False, True, 0)

            popover.add(vbox)

            popover.set_position(Gtk.PositionType.BOTTOM)
            popover.set_relative_to(attached_to)

            return popover

        field_name = 'key'

        hbox = widget_properties(
            Gtk.HBox(),
            expand=False,
            halign=Gtk.Align.CENTER,
            classes=['linked']
        )

        mnemonics = defaults.fields.mnemonics

        label, entry = build_entry_field_labelled_entry(
            mnemonics, field_name, self.entry
        )

        self.fields[field_name] = entry

        # Special: align label next to entry.
        label.set_xalign(1.0)
        entry.set_size_request(250, -1)
        # HEADS UP: don't connect here, else the first set_text()
        #           triggers a false-positive 'changed' signal.

        # entry.set_placeholder_text('')

        btn_rename = widget_properties(Gtk.Button(), expand=False)
        btn_rename.connect('clicked', self.on_rename_clicked)
        icon = Gio.ThemedIcon(name='document-edit-symbolic')
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        btn_rename.add(image)
        btn_rename.set_tooltip_markup('Rename entry key')

        if self.entry.key is None:
            btn_rename.set_sensitive(False)

            entry.set_icon_from_icon_name(
                Gtk.EntryIconPosition.SECONDARY,
                'help-about-symbolic'
            )

            entry.set_icon_tooltip_markup(
                Gtk.EntryIconPosition.SECONDARY,
                'Let field empty if you want a\n'
                'computed key to be automatically\n'
                'generated from other fields (see\n'
                '<span face="monospace">Preferences</span> for details).'
            )

        else:
            entry.set_text(self.entry.key)
            entry.set_sensitive(False)

            self.rename_popover = build_key_rename_popover(btn_rename)

        # Connect after the set_text() to avoid a
        # false-positive 'changed' signal emission.
        entry.connect('changed',
                      self.on_field_changed,
                      field_name)

        hbox.add(label)
        hbox.add(entry)
        hbox.add(btn_rename)

        # TODO: if self.entry.get_field('ids') is not None:
        #       build “aliases” label + entry + button to
        #       clear them with confirmation popover.

        # TODO: integrate file combo to select the file where
        #       the entry will be saved.
        #       At first save, the combo is greyed out, and
        #       replaced with an entry + button to move the
        #       entry, with a popover like for the key.

        self.box.add(hbox)

    def setup_stack(self):

        def build_fields_grid(entry, fields):

            def connect_and_attach_to_grid(label, entry, field_name):
                entry.connect('changed',
                              self.on_field_changed,
                              field_name)
                self.fields[field_name] = entry
                grid.attach(label, 0, index, 1, 1)
                grid.attach(entry, 1, index, 1, 1)

            grid = Gtk.Grid()
            grid.set_border_width(BOXES_BORDER_WIDTH)
            grid.set_column_spacing(GRID_COLS_SPACING)
            grid.set_row_spacing(GRID_ROWS_SPACING)

            mnemonics = defaults.fields.mnemonics

            if len(fields) == 1:
                field_name = fields[0]
                scr, txv = build_entry_field_textview(
                    mnemonics, field_name, entry)

                for signal_name in (
                    'insert-at-cursor',
                    'delete-from-cursor',
                        'paste-clipboard', ):

                    txv.connect(
                        signal_name,
                        self.on_field_changed,
                        field_name
                    )

                self.fields[field_name] = txv
                grid.attach(scr, 0, 0, 1, 1)

            else:
                index = 0
                for field_name in fields:
                    if isinstance(field_name, list):
                        for subfield_name in field_name:
                            connect_and_attach_to_grid(
                                *build_entry_field_labelled_entry(
                                    mnemonics, subfield_name, entry
                                ), subfield_name,
                            )
                            index += 1
                    else:
                        connect_and_attach_to_grid(
                            *build_entry_field_labelled_entry(
                                mnemonics, field_name, entry
                            ), field_name,
                        )
                        index += 1

            return grid

        stack = Gtk.Stack()

        fields_entry_node = getattr(preferences.fields, self.entry.type)

        if fields_entry_node is None:
            fields_entry_node = getattr(defaults.fields, self.entry.type)

            # HEADS UP: attributes names are different
            #       between defaults and preferences.
            fields_main = fields_entry_node.required[:]
            fields_secondary = []

            fields_other = fields_entry_node.optional[:]

            try:
                fields_stacks = fields_entry_node.stacked[:]

            except TypeError:
                fields_stacks = []

        else:
            fields_main = fields_entry_node.main[:]
            fields_secondary = fields_entry_node.secondary[:]
            fields_other = fields_entry_node.other[:]

            try:
                fields_stacks = fields_entry_node.stacks[:]

            except TypeError:
                fields_stacks = []

        for field_name in fields_stacks:
            if field_name in fields_other:
                # This can happen in defaults.
                # TODO: chek defaults to avoid it.
                fields_other.remove(field_name)

        self.grids['main'] = build_fields_grid(
            self.entry, fields_main,
        )

        if fields_secondary:
            self.grids['secondary'] = build_fields_grid(
                self.entry, fields_secondary,
            )

        for field_name in fields_stacks:
            self.grids[field_name] = build_fields_grid(
                self.entry,  # TODO: Find Mnemonic
                [field_name],
            )

        self.grids['other'] = build_fields_grid(
            self.entry, fields_other,
        )

        stack_switcher = widget_properties(
            Gtk.StackSwitcher(),
            expand=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            margin=GRID_BORDER_WIDTH,
        )

        stack_switcher.set_stack(stack)

        if preferences.types.main is None:
            main_stack_label = "Required fields"
            other_stack_label = "Optional fields"

        else:
            main_stack_label = "Main fields"
            secondary_stack_label = "Secondary fields"
            other_stack_label = "Other fields"

        stack.add_titled(
            in_scrolled(self.grids['main']),
            'main',
            main_stack_label,
        )

        if fields_secondary:
            stack.add_titled(
                in_scrolled(self.grids['secondary']),
                'secondary',
                secondary_stack_label,
            )

        stack.add_titled(
            in_scrolled(self.grids['other']),
            'other',
            other_stack_label,
        )

        for grid_name, grid in self.grids.items():
            if grid_name in ['main', 'secondary', 'other']:
                continue

            stack.add_titled(
                grid,
                grid_name,
                grid_name.title(),  # TODO: find mnemonic
            )

        self.stack_switcher = stack_switcher
        self.stack = stack

        self.box.add(self.stack_switcher)
        self.box.add(self.stack)

    def on_key_compute_clicked(self, widget, entry):

        LOGGER.info('Compute Button Clicked.')

        # Compute a new key
        # Fill the entry

        pass

    def on_rename_clicked(self, button):

        self.rename_popover.show_all()
        find_child_by_name(
            self.rename_popover, 'error_label'
        ).hide()
        self.rename_popover.popup()

    def on_rename_confirm_clicked(self, widget, entry, popover):

        new_key = entry.get_text().strip()

        if new_key in (None, ''):
            popover.popdown()
            return

        if new_key == self.entry.key:
            popover.popdown()
            return

        if __debug__:
            LOGGER.debug('Renaming key from {0} to {1}.'.format(
                self.entry.key, new_key))

        # TODO: why does get_parent() fails here ?
        #       See TODO/comment in __init__().
        has_key_in = self.parent.application.check_has_key(new_key)

        if has_key_in is not None:
            error_label = find_child_by_name(popover, 'error_label')
            new_entry_key = find_child_by_name(popover, 'new_entry_key')
            error_label.set_markup(
                'Key already present in\n'
                '<span face="monospace">{filename}</span>.\n'
                'Please choose another'.format(
                    filename=os.path.basename(has_key_in))
            )
            error_label.show()
            add_classes(new_entry_key, ('error', ))
            new_entry_key.grab_focus()
            return

        # put old key in 'aliases'
        if 'ids' in self.entry.keys():
            self.entry['ids'] += ', {}'.format(self.entry.key)

        else:
            self.entry['ids'] = self.entry.key

        # This will be done in update_entry_and_save_file()
        # Just for the consistency with "new entry case"
        # where the current method is NOT ran.
        # self.entry.key = new_key

        self.changed_fields |= set(('key', 'ids', ))

        if not gpod('bib_auto_save'):
            return

        with self.save_lock:
            self.update_entry_and_save_file()

        popover.popdown()

    def on_entry_hide(self, window):

        # We need to save
        with self.save_lock:

            if gpod('bib_auto_save'):
                self.clear_save_callback()

            self.update_entry_and_save_file()

    def on_switch_type_clicked(self, button):

        LOGGER.info('Switch type clicked')

    def on_previous_clicked(self, button):

        if not gpod('bib_auto_save') and self.needs_save:
            # display a new modal discard / save and go on
            pass

        else:
            pass

    def on_next_clicked(self, button):

        if not gpod('bib_auto_save') and self.needs_save:
            # display a new modal discard / save and go on
            pass

        else:
            pass

    def on_field_changed(self, entry, field_name):

        # Multiple updates to same widget will be
        # recorded only once, thanks to the set.
        self.changed_fields.add(field_name)

        if not gpod('bib_auto_save'):
            return

        if __debug__:
            LOGGER.debug('Field {} changed.'.format(field_name))

        with self.save_lock:
            self.clear_save_callback()

            self.save_trigger_source = GLib.timeout_add_seconds(
                priority=GLib.PRIORITY_DEFAULT, interval=5,
                function=self.on_save_trigger_callback)

    def on_save_clicked(self, widget, *args, **kwargs):

        with self.save_lock:
            self.update_entry_and_save_file()

    def on_save_trigger_callback(self, *args, **kwargs):

        if __debug__:
            LOGGER.debug('on_save_trigger_callback({})'.format(
                self.entry.key))

        with self.save_lock:
            self.update_entry_and_save_file()

        # Remove the callback from IDLE list.
        # Next will be triggered by future entry changes.
        return False

    def clear_save_callback(self):

        if self.save_trigger_source:
            # Remove the in-progress save()
            try:
                GLib.source_remove(self.save_trigger_source)

            except Exception:
                # The callback finished while we were blocked on the lock,
                # or GLib didn't automatically wipe self.save_trigger_source.
                pass

    def check_entry(self):

        LOGGER.warning(
            'IMPLEMENT {}.check_entry()'.format(
                self.__class__.__name__))

        return True

    def update_entry_and_save_file(self):

        print(ltrace_function_name())

        entry = self.entry

        if not self.changed_fields:
            LOGGER.info(
                'Entry {} did not change, avoiding superfluous save.'.format(
                    entry.key))
            return

        if gpod('ensure_biblatex_checks'):
            if not self.check_entry():
                return

        LOGGER.info('Fields changed on {0}: [{1}]'.format(
            entry.key, ', '.join(self.changed_fields)
        ))

        key_updated = False
        new_entry   = False

        if 'ids' in self.changed_fields:
            self.changed_fields.remove('ids')
            key_updated = True

        if 'key' in self.changed_fields:
            # Do not remove() the field, we
            # could be in 'new entry' case.
            if not key_updated:
                new_entry = True

        for field_name in self.changed_fields:
            widget = self.fields[field_name]

            if isinstance(widget, Gtk.Entry):
                entry[field_name] = widget.get_text()

            elif isinstance(widget, Gtk.TextView):
                entry[field_name] = widget.get_textbuffer().get_text()

            else:
                LOGGER.warning('Unhandled changed field {}'.format(field_name))

        if new_entry:
            # TODO: find a database !!!
            entry.database.add_entry(entry)

        elif key_updated:
            entry.database.move_entry(entry)

        # In other case (just some fields updated), the job is
        # already done. We just have to dump the file to disk.

        entry.database.save()

        # Reset changed fields now that everything is saved.
        self.changed_fields = set()