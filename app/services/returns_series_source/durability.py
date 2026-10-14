"""Directory publication barrier for the supported Linux lineage filesystem.

The deployment must provide a filesystem/volume that honors file and directory
fsync and atomic same-directory hard links. Unsupported platforms fail custody;
they do not silently substitute file flushes for durable namespace publication.
"""

import errno
import os
import sys
from pathlib import Path


def sync_directory(directory: Path) -> None:
    if sys.platform != "linux":
        raise OSError(errno.ENOTSUP, "Source publication requires Linux directory fsync support.")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
