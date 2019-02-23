
import os
import logging

from bibed.ltrace import (  # NOQA
    ldebug, lprint,
    lprint_caller_name,
    lprint_function_name,
)

from collections import OrderedDict

from bibed.constants import (
    BOXES_BORDER_WIDTH,
    GRID_COLS_SPACING,
    GRID_ROWS_SPACING,
    GRID_BORDER_WIDTH,
)

from bibed.strings import friendly_filename
from bibed.preferences import defaults, preferences, memories, gpod
from bibed.entry import (
    generate_new_key,
    EntryFieldCheckMixin,
    EntryFieldBuildMixin,
)
from bibed.locale import _
from bibed.gtk import Gtk, Gdk, Gio

from bibed.gui.helpers import (
    widget_properties,
    label_with_markup,
    in_scrolled,
    get_children_recursive,
    stack_switch_next,
    add_classes, remove_classes,
    # find_child_by_name,
    build_entry_field_labelled_entry,
    build_entry_field_textview,
    grid_with_common_params,
)


LOGGER = logging.getLogger(__name__)


class EntryBlockSignalContextManager:
    def __init__(self, entry, handler):
        self.entry = entry
        self.handler = handler

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.entry.handler_unblock_by_func(self.handler)


class BibedEntryDialog(Gtk.Dialog, EntryFieldCheckMixin, EntryFieldBuildMixin):

    @property
    def needs_save(self):

        return len(self.changed_fields)

    @property
    def can_save(self):

        # assert lprint_caller_name(levels=3)
        # assert lprint_function_name()

        entry_has_key = (self.entry.key is not None or 'key' in self.changed_fields)
        entry_has_database = self.entry.database is not None

        if self.brand_new:
            # `bibtexparser` fails when there is an entry with only a key.
            # We need at least a field more than ID and ENTRYTYPE.
            entry_has_more_than_id_and_type = len(self.changed_fields) > 1

            key_is_unique = not self.files.has_bib_key(
                self.entry.key
                if self.entry.key
                else self.get_field_value('key')
            )

        else:
            # This has already been checked by other methods.
            entry_has_more_than_id_and_type = True
            key_is_unique = True

        entry_is_new = self.brand_new
        entry_is_known = not entry_is_new

        result = (
            entry_has_key
            and entry_has_database
            and entry_has_more_than_id_and_type
            and (
                entry_is_known or (
                    entry_is_new and key_is_unique
                )
            )
        )

        # assert lprint(
        #     entry_has_key,
        #     entry_has_database,
        #     entry_has_more_than_id_and_type,
        #     entry_is_known,
        #     entry_is_new,
        #     key_is_unique,
        #     result
        # )

        return result

    def __init__(self, parent, entry):

        type_label = _(getattr(defaults.types.labels,
                               entry.type)).replace('_', '').lower()

        if entry.key is None:
            title = _('Create new {type}').format(type=type_label)

        else:
            title = _('Edit {type} {key}').format(
                type=type_label, key=entry.key)

        super().__init__(title, parent, use_header_bar=True)

        self.files = parent.application.files

        # Used for the field builder, which needs data store.
        self.application = parent.application

        # TODO: This is probably a dupe with Gtk's get_parent(),
        #       but despite super() beiing given parent arg,
        #       get_parent() returns None in
        #       on_rename_confirm_clicked().
        self.parent = parent

        self.set_modal(True)
        self.set_default_size(500, 500)
        self.set_border_width(BOXES_BORDER_WIDTH)

        self.entry = entry

        # direct access to fields for *save() methods.
        self.fields = OrderedDict()

        # This set() will be updated by widget callbacks,
        # and used in self.update_entry_and_save_file().
        self.changed_fields = set()

        # Idem
        self.error_fields = set()

        # This is needed for auto_save to interact gracefully with
        # destination_file popover, and be able to (re)set it as
        # will until the first save.
        self.brand_new = self.entry.key is None

        # Will be set to True by the update*() method.
        # Needed by window.*row_activated*() to know
        # if it needs to update the treeview or not.
        self.changed = False

        # Direct access to fields grids.
        self.grids = {}

        self.connect('key-press-event', self.on_key_pressed)

        self.box = self.get_content_area()

        self.setup_headerbar()
        self.setup_infobar()
        self.setup_key_entry()
        self.setup_stack()
        self.setup_help_label()

        self.show_all()

        self.first_focus()

    # ————————————————————————————————————————————————————————————————— blocker

    def block_changed_signal(self, field):

        field.handler_block_by_func(self.on_field_changed)

        return EntryBlockSignalContextManager(field, self.on_field_changed)

    # ————————————————————————————————————————————————————————— Interface build

    def on_key_pressed(self, widget, event):

        keyval = event.keyval

        # check the event modifiers (can also use SHIFTMASK, etc)
        ctrl = (event.state & Gdk.ModifierType.CONTROL_MASK)

        if ctrl and keyval == Gdk.KEY_s:

            if gpod('bib_auto_save'):
                # This is a placebo, anyway.
                self.update_entry_and_save_file()

            else:
                self.btn_save.emit('clicked')

        elif ctrl and keyval == Gdk.KEY_d:

            self.btn_destination_set.emit('clicked')

        elif ctrl and keyval == Gdk.KEY_t:

            # Should open switch type popover.

            LOGGER.info('Control-T pressed in dialog (no action yet).')

        elif ctrl and keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):

            # TODO: switch previous / next entry (filtered / sorted…)

            LOGGER.info('Control-Page-[UP/DOWN] pressed in dialog (no action yet).')

        elif not ctrl:
            if keyval == Gdk.KEY_Page_Down:
                self.select_first_sensitive_field(
                    stack_switch_next(self.stack)
                )

            elif keyval == Gdk.KEY_Page_Up:
                self.select_first_sensitive_field(
                    stack_switch_next(self.stack, reverse=True)
                )

            else:
                # The keycode combination was not handled, propagate.
                return False

        else:
            # The keycode combination was not handled, propagate.
            return False

        # Stop propagation of signal, we handled it.
        return True

    def first_focus(self):

        # assert lprint_function_name()

        if self.brand_new:
            # TODO: if gpod('autogenerate_bib_keys'):
            #
            # We have to fake an error on the key field for it
            # to be auto-fixed and auto-generated on first save().
            # If the user enters a key manually, this will be wiped
            # by the check method if the key is OK. If the entered
            # key is bad, the fix method will update it before last
            # resort save() in run().
            #
            # Not the right way of doing it
            # self.fields['key'].emit('changed')

            self.error_fields.add('key')

        self.fields['key'].set_placeholder_text(
            _('Let empty for autogenerated')
        )

        if self.preselect_destination():
            self.select_first_sensitive_field(self.stack.get_children()[0])

        else:
            self.destination_popover.show_all()
            self.destination_popover.popup()
            self.cmb_destination.grab_focus()

    def select_first_sensitive_field(self, root=None):

        # assert lprint_function_name()

        if root is None:
            fields = self.fields.values()

        else:
            fields = [
                child
                for child in get_children_recursive(root)
                if (isinstance(child, Gtk.Entry)
                    or isinstance(child, Gtk.TextView))
            ]

        # assert lprint([f.get_name() for f in fields])

        # Focus the first sensitive field
        # (eg. 'key' for new entries, 'title' for existing).
        for val in fields:
            if val.get_sensitive() and val.is_visible():
                val.grab_focus()
                # assert lprint(val.get_name())
                break

    def preselect_destination(self):

        # HEADS UP: we cannot just test `if self.entry.database`, because in
        #           case of an empty database, it will return False. See
        #           https://pythontic.com/functions/built-in/bool for details.
        if self.entry.database is not None:
            combo = self.cmb_destination
            destination_filename = self.entry.database.filename

            combo.handler_block_by_func(self.on_destination_changed)

            for row in combo.get_model():
                if row[0] == destination_filename:
                    combo.set_active_iter(row.iter)
                    break

            combo.handler_unblock_by_func(self.on_destination_changed)

            if memories.last_destination != destination_filename:
                memories.last_destination = destination_filename

            return True

        return False

    def setup_infobar(self):

        self.infobar = widget_properties(
            Gtk.InfoBar(),
            expand=Gtk.Orientation.HORIZONTAL,
            margin_bottom=GRID_ROWS_SPACING,
            no_show_all=True,
        )

        self.lbl_infobar = label_with_markup(
            '',
            xalign=0.0,
        )

        self.infobar.get_content_area().add(self.lbl_infobar)
        self.lbl_infobar.show_all()
        self.infobar.set_show_close_button(True)

        self.infobar.connect('response', self.close_infobar)

        self.box.add(self.infobar)

    def close_infobar(self, *args, **kwargs):
        self.infobar.set_revealed(False)

        # To get rid of the 1 remaining pixel.
        # self.infobar.hide()
        pass

    def message_info(self, message):

        self.lbl_infobar.set_markup(message)

        self.infobar.set_message_type(Gtk.MessageType.INFO)
        self.infobar.show_now()
        self.infobar.set_revealed(True)

    def message_error(self, message):

        self.lbl_infobar.set_markup(message)

        self.infobar.set_message_type(Gtk.MessageType.ERROR)
        self.infobar.show_now()
        self.infobar.set_revealed(True)

    def setup_headerbar(self):

        def build_destination_popover(attached_to):

            popover = Gtk.Popover()

            grid = grid_with_common_params()

            label = widget_properties(
                label_with_markup(
                    _('Choose file to record entry into:'),
                    xalign=0.5,
                ),
                expand=True,
                halign=Gtk.Align.CENTER,
            )

            grid.attach(label, 0, 0, 1, 1)

            # ——————————————————————————————————————————— Entry+Auto-compute

            self.cmb_destination = widget_properties(
                Gtk.ComboBoxText(name='destination_file'),
                expand=Gtk.Orientation.HORIZONTAL,
                halign=Gtk.Align.FILL,
                valign=Gtk.Align.CENTER,
                width=300,
            )

            self.cmb_destination.set_entry_text_column(0)
            self.cmb_destination.set_popup_fixed_width(False)

            for filename in self.files.get_open_filenames():
                self.cmb_destination.append_text(filename)

            self.cmb_destination.connect(
                'changed', self.on_destination_changed)

            grid.attach_next_to(
                self.cmb_destination, label,
                Gtk.PositionType.BOTTOM,
                1, 1
            )

            # ————————————————————————— popover confirmation / close button

            self.btn_destination_set = widget_properties(
                Gtk.Button(_('Set')),
                classes=['suggested-action'],
                connect_to=self.on_destination_set_clicked,
                default=True,
                connect_args=(self.cmb_destination, popover, ),
            )

            grid.attach_next_to(
                self.btn_destination_set,
                self.cmb_destination,
                Gtk.PositionType.BOTTOM,
                1, 1
            )

            popover.add(grid)

            popover.set_position(Gtk.PositionType.BOTTOM)
            popover.set_relative_to(attached_to)

            return popover

        self.headerbar = self.get_header_bar()

        # ————————————————————————————————————————————— Prev / Next buttons

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

        # TODO: remove this "1" when ←→ navigation is implemented.
        if 1 or self.entry.key is None:
            # We need to wait after the entry is first saved.
            bbox.set_sensitive(False)

        # ———————————————————————————————————————————— Eventual save button

        if not gpod('bib_auto_save'):
            self.btn_save = widget_properties(
                Gtk.Button(_('Save')),
                expand=False,
                classes=['suggested-action'],
                connect_to=self.on_save_clicked,
                default=True,
            )

            self.headerbar.pack_end(self.btn_save)

        # ————————————————————————————————————————————— Save in file button

        btn_destination_choose = widget_properties(Gtk.Button(), expand=False)
        icon = Gio.ThemedIcon(name='system-file-manager-symbolic')
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        btn_destination_choose.add(image)
        btn_destination_choose.set_tooltip_markup(
            _('Set or change BIB storage file'))

        self.destination_popover = build_destination_popover(
            btn_destination_choose)
        self.btn_destination_choose = btn_destination_choose
        self.headerbar.pack_end(btn_destination_choose)

        btn_destination_choose.connect(
            'clicked', self.on_destination_choose_clicked,
            self.destination_popover)

        if self.entry.database is not None:
            if not gpod('bib_auto_save'):
                # Move without bib_auto_save needs to be
                # carefully thought. It's not implemented yet.
                self.btn_destination_choose.set_sensitive(False)

        # —————————————————————————————————————————————— Switch type button

        btn_switch_type = widget_properties(Gtk.Button(), expand=False)
        icon = Gio.ThemedIcon(name='network-transmit-receive-symbolic')
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        btn_switch_type.add(image)
        btn_switch_type.set_tooltip_markup('Switch entry type')
        btn_switch_type.connect('clicked', self.on_switch_type_clicked)

        self.btn_switch_type = btn_switch_type
        self.headerbar.pack_end(btn_switch_type)

        # TODO: reactivate this when popover is implemented.
        self.btn_switch_type.set_sensitive(False)

    def setup_help_label(self):

        if gpod('bib_auto_save'):
            self.box.add(widget_properties(label_with_markup(
                _('<span foreground="grey">Entry is automatically saved; '
                  'just hit <span face="monospace">ESC</span> or close '
                  'the window when you are done.'
                  '</span>'),
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
                    _('Type new entry key.\n'
                      'Use button to generate\n'
                      'a new one from entry data.'),
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
                # halign=Gtk.Align.FILL,
                valign=Gtk.Align.CENTER,
                # width=300,
                activates_default=True,
            )

            if not self.brand_new:
                entry.set_text(self.entry.key)

            btn_compute = widget_properties(Gtk.Button(), expand=False)
            btn_compute.connect('clicked', self.on_key_compute_clicked, entry)
            icon = Gio.ThemedIcon(name='system-run-symbolic')
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
            btn_compute.add(image)
            btn_compute.set_tooltip_markup(
                _('Compute a key from already filled entry fields.')
            )

            hbox = widget_properties(
                Gtk.HBox(),
                expand=Gtk.Orientation.HORIZONTAL,
                valign=Gtk.Align.CENTER,
                classes=['linked'],
            )

            hbox.pack_start(entry, True, True, 0)
            hbox.pack_start(btn_compute, False, False, 0)

            vbox.pack_start(hbox, True, True, GRID_ROWS_SPACING)

            # ————————————————————————————————————————— error label (hidden)

            error_label = widget_properties(
                Gtk.Label(name='error_label'),
                expand=True,
                halign=Gtk.Align.CENTER,
                no_show_all=True,
            )

            vbox.pack_start(error_label, False, True, 0)

            # ————————————————————————— popover confirmation / close button

            btn_confirm_rename = widget_properties(
                Gtk.Button(_('Change Key')),
                classes=['suggested-action'],
                connect_to=self.on_rename_confirm_clicked,
                default=True,
                connect_args=(popover, entry, error_label),
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

        fields_labels = defaults.fields.labels
        fields_docs   = defaults.fields.docs

        label, entry = build_entry_field_labelled_entry(
            fields_docs, fields_labels, field_name, self.entry
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

        def build_fields_groups():
            ''' Get fields groups from user preferences,
                or application defaults. '''

            try:
                fields_entry_node = getattr(
                    preferences.fields.by_type, self.entry.type)

            except AttributeError:
                # We have no preferences at all (user has started the
                # app for the first time, or did not set any prefs).
                fields_entry_node = getattr(
                    defaults.fields.by_type, self.entry.type)

                # HEADS UP: attributes names are different
                #       between defaults and preferences.
                fields_main = fields_entry_node.required[:]

                fields_secondary = []

                try:
                    fields_other = fields_entry_node.optional[:]

                except TypeError:
                    fields_other = []

                try:
                    fields_stacked = fields_entry_node.stacked[:]

                except TypeError:
                    fields_stacked = []

            else:
                fields_main = fields_entry_node.main[:]

                try:
                    fields_secondary = fields_entry_node.secondary[:]

                except TypeError:
                    fields_secondary = []

                try:
                    fields_other = fields_entry_node.other[:]

                except TypeError:
                    fields_other = []

                try:
                    fields_stacked = fields_entry_node.stacked[:]

                except TypeError:
                    fields_stacked = []

            for field_name in fields_stacked:
                if field_name in fields_other:
                    # This can happen in defaults.
                    # TODO: chek defaults to avoid it.
                    fields_other.remove(field_name)

            return (
                fields_main,
                fields_secondary,
                fields_other,
                fields_stacked,
            )

        def build_fields_grid(entry, fields):

            def connect_and_attach_to_grid(label, entry, field_name):

                entry.connect('changed',
                              self.on_field_changed,
                              field_name)
                self.fields[field_name] = entry
                grid.attach(label, 0, index, 1, 1)
                grid.attach(entry, 1, index, 1, 1)

                post_build_method = getattr(
                    self, 'build_field_{}_post'.format(field_name), None)

                if post_build_method is not None:
                    post_build_method(self.fields, field_name, entry,
                                      self.application.data)

            grid = Gtk.Grid()
            grid.set_border_width(BOXES_BORDER_WIDTH)
            grid.set_column_spacing(GRID_COLS_SPACING)
            grid.set_row_spacing(GRID_ROWS_SPACING)

            if len(fields) == 1:
                # Only one field in the group, we
                # fill the stack with a text view.
                field_name = fields[0]

                scr, txv = build_entry_field_textview(
                    fields_docs, field_name, entry)

                txv.get_buffer().connect(
                    'changed', self.on_field_changed, field_name)

                self.fields[field_name] = txv
                grid.attach(scr, 0, 0, 1, 1)

            else:
                index = 0
                for field_name in fields:

                    if isinstance(field_name, list):
                        # list in list: cf. defaults.fields.by_type.required
                        # where some fields are required by tuples.
                        for subfield_name in field_name:
                            connect_and_attach_to_grid(
                                *build_entry_field_labelled_entry(
                                    fields_docs, fields_labels,
                                    subfield_name, entry
                                ), subfield_name,
                            )
                            index += 1

                    else:
                        connect_and_attach_to_grid(
                            *build_entry_field_labelled_entry(
                                fields_docs, fields_labels,
                                field_name, entry
                            ), field_name,
                        )
                        index += 1

            return grid

        def build_stack_labels():

            if preferences.types.main is None:
                main_stack_label = _('Required fields')

                # We have no "secondary" in defaults,
                # this is a user-level feature.
                secondary_stack_label = None

                other_stack_label = _('Optional fields')

            else:
                main_stack_label = _('Main fields')
                secondary_stack_label = _('Secondary fields')
                other_stack_label = _('Other fields')

            if len(fields_main) == 1:
                main_stack_label = _(getattr(fields_labels,
                                             fields_main[0]))

            if len(fields_secondary) == 1:
                secondary_stack_label = _(getattr(fields_labels,
                                                  fields_secondary[0]))

            if len(fields_other) == 1:
                other_stack_label = _(getattr(fields_labels,
                                              fields_other[0]))

            return (
                main_stack_label,
                secondary_stack_label,
                other_stack_label,
            )

        # ———————————————————————————————————————————————— Fields groups stacks

        stack = Gtk.Stack()

        stack_switcher = widget_properties(
            Gtk.StackSwitcher(),
            expand=Gtk.Orientation.HORIZONTAL,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            margin=GRID_BORDER_WIDTH,
        )

        stack_switcher.set_stack(stack)

        # ————————————————————————————————————————————— Fields groups building

        (fields_main,
         fields_secondary,
         fields_other,
         fields_stacked) = build_fields_groups()

        # Get labels & docs from application defaults (YAML data file).
        fields_labels = defaults.fields.labels
        fields_docs   = defaults.fields.docs

        self.grids['main'] = build_fields_grid(
            self.entry, fields_main,
        )

        if fields_secondary:
            self.grids['secondary'] = build_fields_grid(
                self.entry, fields_secondary,
            )

        for field_name in fields_stacked:
            self.grids[field_name] = build_fields_grid(
                self.entry,  # TODO: Find Mnemonic label.
                [field_name],
            )

        if fields_other:
            self.grids['other'] = build_fields_grid(
                self.entry, fields_other,
            )

        # ————————————————————————————————————————————— Populate stack switcher

        (main_stack_label,
         secondary_stack_label,
         other_stack_label, ) = build_stack_labels()

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

        if fields_other:
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
                # HEADS UP: OTF translation.
                _(getattr(fields_labels, grid_name)),
            )

        # ————————————————————————————————————————————————— Add widgets, finish

        self.stack_switcher = stack_switcher
        self.stack = stack

        self.box.add(self.stack_switcher)
        self.box.add(self.stack)

    # ————————————————————————————————————————————————————————————— Gtk signals

    def on_key_compute_clicked(self, widget, entry):

        # Do not close the popup, user
        # could like to alter the generated key.
        entry.set_text(generate_new_key(self.entry))

    def on_rename_clicked(self, button):

        # error_label has no_show_all set.
        self.rename_popover.show_all()
        # find_child_by_name(
        #     self.rename_popover, ''
        # ).hide()
        self.rename_popover.popup()

    def on_rename_confirm_clicked(self, widget, popover, new_entry_key, error_label):

        new_key = new_entry_key.get_text().strip()

        if new_key in (None, '') or new_key == self.entry.key:
            popover.popdown()
            return

        LOGGER.debug('Renaming key from {0} to {1}.'.format(
                     self.entry.key, new_key))

        # TODO: why does get_parent() fails here ?
        #       See TODO/comment in __init__().
        has_key_in = self.files.has_bib_key(new_key)

        if has_key_in is not None:
            error_label.set_markup(
                _('Key already present in\n'
                  '<span face="monospace">{filename}</span>.\n'
                  'Please choose another one.').format(
                    filename=friendly_filename(has_key_in))
            )
            error_label.show()
            add_classes(new_entry_key, ('error', ))
            new_entry_key.grab_focus()
            return

        # TODO: look for old key in other entries comments, note, addendum…
        #       there are probably other fields where the key can be.

        # put old key in 'aliases'
        if 'ids' in self.entry.fields():
            old_ids = self.entry.ids
            old_ids.insert(0, self.entry.key)
            self.entry.ids = old_ids

        else:
            self.entry.ids = [self.entry.key]

        # This will be done in update_entry_and_save_file()
        # Just for the consistency with "new entry case"
        # where the current method is NOT ran.
        # self.entry.key = new_key

        # fake the field change and populate the UI entry
        # for *save() to update the BIB entry key.
        self.set_field_value('key', new_key, self.fields['key'])

        self.changed_fields |= set(('key', 'ids', ))

        popover.popdown()

        self.update_entry_and_save_file(save=gpod('bib_auto_save'))

    def on_destination_changed(self, combo):

        if self.entry.database is None:
            self.btn_destination_set.set_label('Set')
            return

        destination_filename = combo.get_active_text()

        if destination_filename == self.entry.database.filename:
            self.btn_destination_set.set_label(_('Close'))
            return

        self.btn_destination_set.set_label(_('Set'))

    def on_destination_choose_clicked(self, button, destination_popover):
        ''' When the popover opener is clicked. '''

        if destination_popover.is_visible():
            destination_popover.popdown()

        else:
            destination_popover.show_all()
            destination_popover.popup()

    def on_destination_set_clicked(self, button, combo_destination, popover):
        ''' When the button IN the popover is clicked. '''

        destination_filename = combo_destination.get_active_text()

        if not destination_filename:
            # TODO: "you must choose one" error label.
            return

        get_database = self.parent.application.files.get_database

        if self.entry.database is None:

            self.entry.database = get_database(filename=destination_filename)

        elif destination_filename != self.entry.database.filename:
            if self.brand_new:
                self.entry.database = get_database(filename=destination_filename)

            else:
                if gpod('bib_auto_save'):
                    self.entry.database.move_entry(
                        self.entry,
                        get_database(filename=destination_filename))
                else:
                    # TODO: move the entry from one database to another.
                    # NOTE: we should not get here, button is disabled
                    #       in this case.
                    raise NotImplementedError(
                        'Implement destination change without bib_auto_save.')

        if not self.entry.database.selected:
            # Make the future destination database visible, else user will
            # not be able to see the entry after creation, which is deeply
            # confusing.
            #
            # In this particular case, whatever databases were visible
            # before, the user just selected one that was NOT. This most
            # probably means she has switched on something very different.
            # Thus, we select this database only, forgetting the previously
            # selected ones. This is intended.

            assert lprint('select', self.entry.database)
            self.parent.set_selected_databases([self.entry.database])

        # Help next entry creation if conditions do not change.
        memories.last_destination = destination_filename

        popover.popdown()

        self.select_first_sensitive_field(self.stack.get_children()[0])

    def run(self, *args, **kwargs):

        result = super().run(*args, **kwargs)

        # We need to save before closing for
        # treeview update to use the new entry.

        if gpod('bib_auto_save'):
            # Dialog is closing. using fix_errors=True is the ONLY way
            # to save the maximum of what the user created / modified.
            return self.update_entry_and_save_file(save=True, fix_errors=True)

        else:
            # If user did not save, be sure we don't
            # insert an invalid entry in the treeview.
            self.reset_fields()

        return result

    def reset_fields(self, with_brand_new=False, only_no_error=False):

        if only_no_error:
            for field_name in self.changed_fields.copy():
                if field_name not in self.error_fields:
                    self.changed_fields.remove(field_name)

        else:
            self.changed_fields = set()
            self.error_fields = set()

        if with_brand_new:
            self.brand_new = False

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

    def get_field_value(self, field_name, widget=None):

        if widget is None:
            widget = self.fields[field_name]

        if isinstance(widget, Gtk.Entry):
            return widget.get_text()

        elif isinstance(widget, Gtk.TextView):
            buffer = widget.get_buffer()
            return buffer.get_text(
                buffer.get_start_iter(),
                buffer.get_end_iter(),
                False,
            )

        else:
            LOGGER.warning('Unhandled changed field {}'.format(field_name))
            return None

    def set_field_value(self, field_name, value, widget=None):

        # assert lprint_function_name()

        if widget is None:
            widget = self.fields[field_name]

        if isinstance(widget, Gtk.Entry):
            return widget.set_text(value)

        elif isinstance(widget, Gtk.TextView):
            buffer = widget.get_buffer()

            return buffer.set_text(value)

        else:
            LOGGER.warning('Unhandled field {}'.format(field_name))
            return None

    def __check_field_wrapper(self, field_name, field, fix_errors=False):

        try:
            check_method = getattr(self, 'check_field_{}'.format(field_name))

        except AttributeError:
            # No check method, we assume any value is OK.
            return True

        field_value = self.get_field_value(field_name, field)

        error = check_method(self.fields, field_name, field, field_value)

        if error:
            add_classes(field, ['error'])
            self.error_fields.add(field_name)
            self.message_error(error)

            # LOGGER.error('Field {} do NOT pass checks.'.format(field_name))

            return False

        else:
            remove_classes(field, ['error'])
            try:
                self.error_fields.remove(field_name)

            except KeyError:
                # already not in error state.
                pass
            self.close_infobar()

        return True

    def on_field_changed(self, entry, field_name):

        LOGGER.debug('Field {} eventually changed.'.format(field_name))

        if not self.__check_field_wrapper(field_name, entry):
            return

        LOGGER.debug('Field {} changed and OK, marking it.'.format(field_name))

        if self.get_field_value(field_name) == '':
            # In cas of a new entry, don't save it if has no field filled.
            # If the user fills a field, then empties if, we must consider
            # it hasn't changed, else this will create an empty entry, which
            # can be considered as some sort of “false positive”.
            if self.brand_new:
                LOGGER.debug(
                    'Field {} was emptyed on a new entry, unmarking it.'.format(
                        field_name))
                try:
                    self.changed_fields.remove(field_name)

                except (ValueError, KeyError):
                    pass

                return

        # Multiple updates to same widget will be
        # recorded only once, thanks to the set.
        self.changed_fields.add(field_name)

    def on_save_clicked(self, widget, *args, **kwargs):

        self.update_entry_and_save_file(save=True)

    def check_biblatex_entry(self):

        LOGGER.warning(
            'IMPLEMENT {}.check_biblatex_entry()'.format(
                self.__class__.__name__))

        return True

    def get_changed_fields_with_values(self, only_no_error=False):

        updated_fields = {
            field_name: self.get_field_value(field_name)
            for field_name in self.changed_fields
            if (
                only_no_error and field_name not in self.error_fields
                or not only_no_error
            )
        }

        # assert lprint(updated_fields)

        return updated_fields

    def fix_all_error_fields(self):

        # assert lprint_function_name()

        # Mock a transient entry to fix fields from.
        copy_entry = self.entry.copy()
        copy_entry.update_fields(
            **self.get_changed_fields_with_values(only_no_error=True)
        )

        for field_name in self.error_fields.copy():

            field = self.fields[field_name]

            field_value = self.get_field_value(field_name, field)

            try:
                fix_method = getattr(self, 'fix_field_{}'.format(field_name))

            except AttributeError:
                # No fix method, we have to wipe the field.
                fixed_value = None

            else:
                fixed_value = fix_method(self.fields,
                                         field_name, field, field_value,
                                         entry=copy_entry, files=self.files)

            # Block “changed” signal and update changed_fields ouselves,
            # Else it happens in another thread/reality, and ou caller
            # update_entry_and_save_file() continues too fast and
            # doesn't “see” the update.
            with self.block_changed_signal(field):
                self.set_field_value(field_name, fixed_value, field)

                self.changed_fields.add(field_name)
            try:
                self.error_fields.remove(field_name)

            except KeyError:
                # In the case of auto-generating “key” field, this
                # will fail because field was not in error.
                pass

            LOGGER.info('{entry}: error field “{field}” fixed with new value '
                        '{fix}'.format(entry=self.entry, field=field_name,
                                       fix=fixed_value))

    def update_entry_and_save_file(self, save=True, fix_errors=False):

        entry = self.entry

        # assert lprint_function_name()

        if not self.changed_fields:
            LOGGER.debug('{}: did not change, avoiding save().'.format(
                         entry.key))
            return

        if not self.can_save:
            LOGGER.debug('{}: cannot save yet.'.format(entry))

            if fix_errors:
                LOGGER.debug('{}: auto fixing errors ({}) to '
                             'ensure save().'.format(
                                 entry, ', '.join(self.error_fields)))

                # Push everything pushable to the
                # entry, then fix fields in place.
                self.fix_all_error_fields()

            else:
                LOGGER.debug('{}: aborting save().'.format(entry))
                return

        if gpod('ensure_biblatex_checks'):
            if not self.check_biblatex_entry():
                return

        LOGGER.debug(
            'update_entry_and_save_file(): will save {0}: {1}'.format(
                entry, ', '.join(self.changed_fields)))

        # User renamed the key via popover.
        key_updated = False

        # First save or auto-save.
        new_entry = False

        if 'ids' in self.changed_fields:
            self.changed_fields.remove('ids')
            key_updated = True

        if 'key' in self.changed_fields:
            # Do not remove() the field, we could be in 'new entry' case.
            if not key_updated:
                if self.brand_new:
                    # Special case at first save / auto-save.
                    new_entry = True

        entry.update_fields(
            **self.get_changed_fields_with_values(),
            update_store=not self.brand_new)

        if new_entry:
            entry.database.add_entry(entry)

        elif key_updated:
            entry.database.update_entry_key(entry)

        if save:
            self.files.save(entry)

        # Reset changed fields now that everything is saved.
        # Entry is not brand_new, it now has a key and it's
        # written in one of our files.
        self.reset_fields(with_brand_new=True)

        return entry
