from pathlib import Path
import shutil

from config import ONENOTE_IMPORT_DIR


def copy_onenote_export(
    run_dir: Path,
) -> Path:
    """
    Copy a meeting OneNote export into
    the NAS OneNote import landing area.
    """

    export_dir = (
        run_dir / "exports"
    )

    exports = list(
        export_dir.glob("OneNote_*.html")
    )

    if not exports:
        raise FileNotFoundError(
            f"No OneNote export found in {export_dir}"
        )

    source = exports[0]

    ONENOTE_IMPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        ONENOTE_IMPORT_DIR /
        source.name
    )

    shutil.copy2(
        source,
        destination,
    )

    return destination
