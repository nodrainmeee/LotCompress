"""Exceptions métier, avec messages en français."""


class LotCompressError(Exception):
    """Erreur générique affichée à l'utilisateur."""


class UnsupportedFormatError(LotCompressError):
    pass


class CorruptedFileError(LotCompressError):
    pass


class FilePermissionError(LotCompressError):
    pass


class CancelledError(LotCompressError):
    pass


def describe(exc: BaseException) -> str:
    """Message lisible pour n'importe quelle exception."""
    if isinstance(exc, LotCompressError):
        return str(exc)
    if isinstance(exc, PermissionError):
        return "Accès refusé (permissions insuffisantes)"
    if isinstance(exc, FileNotFoundError):
        return "Fichier introuvable"
    if isinstance(exc, OSError):
        return f"Erreur disque : {exc.strerror or exc}"
    return f"Erreur inattendue : {exc}"
