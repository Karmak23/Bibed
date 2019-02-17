
# ———————————————————————————————————————————————————————————————— Base classes


class BibedException(Exception):
    pass


class BibedError(BibedException):
    pass


# ———————————————————————————————————————————————————————————— utils exceptions


class BibedStringException(BibedException):
    pass


class ActionError(BibedError):
    def __init__(self, action, *args, **kwargs):
        self.action = action

        super().__init__(*args, **kwargs)


# ——————————————————————————————————————————————————————————— Stores exceptions


class BibedDataStoreException(BibedException):
    pass


class BibedDataStoreError(BibedError):
    pass


class BibedFileStoreException(BibedException):
    pass


class BibedFileStoreError(BibedError):
    pass


class AlreadyLoadedException(BibedFileStoreException):
    pass


class NoDatabaseForDBIDError(BibedFileStoreError):
    pass


class NoDatabaseForFilenameError(BibedFileStoreError):
    pass


class FileNotFoundError(BibedFileStoreError):
    pass


class BibKeyNotFoundError(BibedError):
    pass


# ————————————————————————————————————————————————————————— Database exceptions


class BibedDatabaseException(BibedException):
    pass


class BibedDatabaseError(BibedError):
    pass


class IndexingFailedError(BibedDatabaseError):
    pass


class DuplicateKeyError(BibedDatabaseError):
    pass


# —————————————————————————————————————————————————————————————— GUI exceptions


class BibedTreeViewException(BibedException):
    pass
