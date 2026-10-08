"""Atomic persistence for text exports and user configuration files."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


@contextmanager
def atomic_writer(path):
    """Stream text to a temporary sibling; replace the destination on success."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            yield stream
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def atomic_text(path,text):
    with atomic_writer(path) as stream:
        stream.write(text)
