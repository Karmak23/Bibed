import logging
import webbrowser

# from bibed.foundations import ldebug
from bibed.constants import (
    RESIZE_SIZE_MULTIPLIER,
    BibAttrs,
    URL_PIXBUFS,
    COMMENT_PIXBUFS,
    READ_STATUS_PIXBUFS,
    QUALITY_STATUS_PIXBUFS,
    CELLRENDERER_PIXBUF_PADDING,
)

from bibed.preferences import memories  # , gpod
from bibed.entry import BibedEntry

from bibed.gui.renderers import CellRendererTogglePixbuf
from bibed.gui.entry import BibedEntryDialog
from bibed.gui.gtk import Gtk, Pango, GdkPixbuf


LOGGER = logging.getLogger(__name__)


class BibedMainTreeView(Gtk.TreeView):
    ''' Wraps :class:`Gtk.TreeView`

    '''

    def __init__(self, *args, **kwargs):
        ''' Return the treeview.

            :param:window: the main window.
            :param:a primary clipboard: the main window.
        '''

        self.main_model  = kwargs.get('model')
        self.application = kwargs.pop('application')
        self.clipboard   = kwargs.pop('clipboard')
        self.window      = kwargs.pop('window')

        super().__init__(*args, **kwargs)

        self.setup_pixbufs()

        # We get better search via global SearchEntry
        self.set_enable_search(False)

        # Not usable because columns are not fixed size. Bummer.
        # self.set_fixed_height_mode(True)

        self.col_global_id = self.add_treeview_text_column(
            '#', BibAttrs.GLOBAL_ID)
        self.col_id = self.add_treeview_text_column('#', BibAttrs.ID)
        self.col_id.props.visible = False

        self.col_type = self.add_treeview_text_column('type', BibAttrs.TYPE)

        # File column
        # URL column
        # DOI column

        # TODO: integrate a pixbuf for "tags" and create tooltip with tags.
        self.col_key = self.add_treeview_text_column(
            'key', BibAttrs.KEY, resizable=True,
            min=100, max=150, ellipsize=Pango.EllipsizeMode.START)

        self.col_url = self.setup_pixbuf_column(
            'U', BibAttrs.URL, self.get_url_cell_column,
            self.on_url_clicked)
        self.col_quality = self.setup_pixbuf_column(
            'Q', BibAttrs.QUALITY, self.get_quality_cell_column,
            self.on_quality_clicked)
        self.col_read = self.setup_pixbuf_column(
            'R', BibAttrs.READ, self.get_read_cell_column,
            self.on_read_clicked)
        self.col_comment = self.setup_pixbuf_column(
            'C', BibAttrs.COMMENT, self.get_comment_cell_column)

        self.col_author = self.add_treeview_text_column(
            'author', BibAttrs.AUTHOR, resizable=True,
            min=130, max=200, ellipsize=Pango.EllipsizeMode.END)
        self.col_title = self.add_treeview_text_column(
            'title', BibAttrs.TITLE, resizable=True, expand=True,
            min=300, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.col_journal = self.add_treeview_text_column(
            'journal', BibAttrs.JOURNAL, resizable=True,
            min=130, max=200, ellipsize=Pango.EllipsizeMode.END)

        self.col_year = self.add_treeview_text_column(
            'year', BibAttrs.YEAR, xalign=1)

        self.set_tooltip_column(BibAttrs.TOOLTIP)

        self.connect('row-activated', self.on_treeview_row_activated)

    def do_status_change(self, message):

        return self.window.do_status_change(message)

    def setup_pixbufs(self):

        for attr_name, constant_dict in (
            ('quality_status_pixbufs', QUALITY_STATUS_PIXBUFS),
            ('read_status_pixbufs', READ_STATUS_PIXBUFS),
            ('comment_pixbufs', COMMENT_PIXBUFS),
            ('url_pixbufs', URL_PIXBUFS),
        ):
            temp_dict = {}

            for status, icon in constant_dict.items():
                if icon:
                    temp_dict[status] = GdkPixbuf.Pixbuf.new_from_file(icon)
                else:
                    temp_dict[status] = None

            setattr(self, attr_name, temp_dict)

    def setup_pixbuf_column(self, title, store_num, renderer_method, signal_method=None):

        if signal_method:
            renderer = CellRendererTogglePixbuf()

        else:
            renderer = Gtk.CellRendererPixbuf()
            renderer.set_padding(CELLRENDERER_PIXBUF_PADDING,
                                 CELLRENDERER_PIXBUF_PADDING)

        column = Gtk.TreeViewColumn(title)
        column.pack_start(renderer, False)

        column.connect('clicked', self.on_treeview_column_clicked)
        column.set_sort_column_id(store_num)

        column.set_cell_data_func(renderer, renderer_method)

        if signal_method is not None:
            renderer.connect('clicked', signal_method)

        self.append_column(column)

        return column

    def get_read_cell_column(self, col, cell, model, iter, user_data):
            cell.set_property(
                'pixbuf', self.read_status_pixbufs[
                    model.get_value(iter, BibAttrs.READ)])

    def get_quality_cell_column(self, col, cell, model, iter, user_data):
            cell.set_property(
                'pixbuf', self.quality_status_pixbufs[
                    model.get_value(iter, BibAttrs.QUALITY)])

    def get_comment_cell_column(self, col, cell, model, iter, user_data):
            cell.set_property(
                'pixbuf', self.comment_pixbufs[
                    model.get_value(iter, BibAttrs.COMMENT) != ''])

    def get_url_cell_column(self, col, cell, model, iter, user_data):
            cell.set_property(
                'pixbuf', self.url_pixbufs[
                    model.get_value(iter, BibAttrs.URL) != ''])

    def add_treeview_text_column(self, name, store_num, resizable=False, expand=False, min=None, max=None, xalign=None, ellipsize=None):  # NOQA

        if ellipsize is None:
            ellipsize = Pango.EllipsizeMode.NONE

        column = Gtk.TreeViewColumn(name)

        column.connect('clicked', self.on_treeview_column_clicked)

        if xalign is not None:
            cellrender = Gtk.CellRendererText(
                xalign=xalign, ellipsize=ellipsize)
        else:
            cellrender = Gtk.CellRendererText(ellipsize=ellipsize)

        column.pack_start(cellrender, True)
        column.add_attribute(cellrender, "text", store_num)
        column.set_sort_column_id(store_num)

        if resizable:
            column.set_resizable(True)

        if expand:
            column.set_expand(True)

        if min is not None:
            # column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            column.set_min_width(min)
            column.set_fixed_width(min)

        if max is not None:
            # column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            column.set_max_width(min)

            # column.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        self.append_column(column)

        return column

    def columns_autosize(self, current_width):
        # Remove 1 else the treeview gets a few pixels too wide.
        # The last column will compensate any "missing" pixels,
        # and we get no horizontal scrollbar.
        column_width = round(current_width * RESIZE_SIZE_MULTIPLIER) - 1

        self.col_key.set_min_width(column_width)
        self.col_author.set_min_width(column_width)
        self.col_journal.set_min_width(column_width)

    def get_entry_by_path(self, path, with_global_id=False, return_iter=False, only_store_entry=False):

        # Are we on the list store, or a filter ?
        model     = self.get_model()
        treeiter  = model.get_iter(path)

        if only_store_entry:
            return model[treeiter]

        bib_key   = model[treeiter][BibAttrs.KEY]
        filename  = model[treeiter][BibAttrs.FILENAME]

        entry = self.application.files[filename].get_entry_by_key(bib_key)

        if with_global_id:
            entry.gid = model[treeiter][BibAttrs.GLOBAL_ID]

        if return_iter:
            return (entry, treeiter, )

        return entry

    def get_main_iter_by_gid(self, gid):

        # for row in self.main_model:
        #     if row[BibAttrs.GLOBAL_ID] == gid:
        #         return row.iter

        # TODO: make clear while I need to substract 1.
        #       make all counters equal everywhere.
        return self.main_model.get_iter(gid - 1)

    def do_column_sort(self):

        if memories.treeview_sort_column is not None:

            for col in self.get_columns():
                if col.props.title == memories.treeview_sort_column:

                    # print('COL', col.props.title)
                    # print(col.get_sort_order())
                    col.props.sort_order = memories.treeview_sort_order
                    # print(col.get_sort_order())

                    # print(col.get_sort_indicator())
                    col.props.sort_indicator = memories.treeview_sort_indicator
                    # print(col.get_sort_indicator())
                    break

    def on_quality_clicked(self, renderer, path):

        entry = self.get_entry_by_path(path, with_global_id=True)

        entry.toggle_quality()

        self.main_model[
            self.get_main_iter_by_gid(entry.gid)
        ][BibAttrs.QUALITY] = entry.quality

        # if gpod('bib_auto_save'):
        self.application.trigger_save(entry.database.filename)

    def on_read_clicked(self, renderer, path):

        entry = self.get_entry_by_path(path, with_global_id=True)

        entry.cycle_read_status()

        self.main_model[
            self.get_main_iter_by_gid(entry.gid)
        ][BibAttrs.READ] = entry.read_status

        # if gpod('bib_auto_save'):
        self.application.trigger_save(entry.database.filename)

    def on_url_clicked(self, renderer, path):

        self.open_url_in_webbrowser(
            entry=self.get_entry_by_path(path, only_store_entry=True))

    def on_treeview_column_clicked(self, column):

        coltit = column.props.title
        colidc = column.props.sort_indicator
        colord = column.props.sort_order

        if memories.treeview_sort_column is None:
            memories.treeview_sort_column = coltit
            memories.treeview_sort_indicator = colidc
            memories.treeview_sort_order = colord

        else:
            if memories.treeview_sort_column != coltit:
                memories.treeview_sort_column = coltit

            if memories.treeview_sort_indicator != colidc:
                memories.treeview_sort_indicator = colidc

            if memories.treeview_sort_order != colord:
                memories.treeview_sort_order = colord

    def on_treeview_row_activated(self, treeview, path, column):

        # GLOBAL_ID is needed to update the treeview after modifications.
        entry = self.get_entry_by_path(path, with_global_id=True)

        assert(isinstance(entry, BibedEntry))

        entry_edit_dialog = BibedEntryDialog(
            parent=self.window, entry=entry)

        entry_edit_dialog.run()

        # TODO: convert this test to Gtk.Response.OK and CANCEL
        #       to know if we need to insert/update or not.
        if entry.database is not None and entry_edit_dialog.can_save:
            # TODO: update list_store directly.
            # Entry was saved to disk, insert it in the treeview.
            self.main_model.update_entry(entry)

        entry_edit_dialog.destroy()

    def get_selected_store_entry(self):

        selection = self.get_selection()

        # Code to add to connect a method to new selection.
        # selection.connect('changed', self.on_treeview_selection_changed)
        # selection.unselect_all()

        model, treeiter = selection.get_selected()

        if treeiter is None:
            return None
        else:
            return model[treeiter]

    def copy_to_clipboard_or_action(self, field_index, transform_func=None, action_func=None, action_message=None, entry=None):

        if entry is None:
            store_entry = self.get_selected_store_entry()
        else:
            store_entry = entry

        if store_entry is None:
            self.do_status_change(
                'Nothing selected; nothing copied to clipboard.')
            return

        entry_gid  = store_entry[BibAttrs.GLOBAL_ID]
        entry_data = store_entry[field_index]

        if entry_data:
            transformed_data = (
                entry_data if transform_func is None
                else transform_func(entry_data)
            )

            if action_func is None:
                self.clipboard.set_text(transformed_data, len=-1)

                self.do_status_change(
                    '“{data}” copied to clipboard (from entry {key}).'.format(
                        data=transformed_data, key=entry_gid))

            else:
                action_func(transformed_data)

                self.do_status_change(
                    '“{data}” {message} (from entry {key}).'.format(
                        data=transformed_data,
                        message=('run through {func}'.format(
                            action_func.__name__
                            if action_message is None
                            else action_message)
                        ),
                        key=entry_gid,
                    )
                )

        else:
            self.do_status_change('Selected entry {key}.'.format(key=entry_gid))

    def copy_raw_key_to_clipboard(self, entry=None):
        return self.copy_to_clipboard_or_action(BibAttrs.KEY, entry=entry)

    def copy_url_to_clipboard(self, entry=None):
        return self.copy_to_clipboard_or_action(BibAttrs.URL, entry=entry)

    def copy_single_key_to_clipboard(self, entry=None):
        return self.copy_to_clipboard_or_action(
            BibAttrs.KEY,
            transform_func=BibedEntry.single_bibkey_format,
            entry=entry,
        )

    def open_url_in_webbrowser(self, entry=None):
        return self.copy_to_clipboard_or_action(
            BibAttrs.KEY,
            action_func=webbrowser.open_new_tab,
            action_message='opened in web browser',
            entry=entry,
        )
