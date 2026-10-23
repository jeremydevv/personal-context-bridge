"""Keep source distributions independent of the builder's operating-system identity."""

import copy
import gzip
import os
from pathlib import Path
import tarfile
import tempfile

from setuptools import setup
from setuptools.command.sdist import sdist


class PrivateSdist(sdist):
    def make_archive(self, *args, **kwargs):
        filename = super().make_archive(*args, **kwargs)
        path = Path(filename)
        if not path.name.endswith('.tar.gz'):
            raise ValueError('Only reviewed tar.gz source distributions are supported')
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tar.gz')
        try:
            with os.fdopen(descriptor, 'wb') as raw, tarfile.open(path, 'r:gz') as source:
                with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as target:
                        for original in source:
                            member = copy.copy(original)
                            member.uid = member.gid = 0
                            member.uname = member.gname = ''
                            member.pax_headers = {k: v for k, v in original.pax_headers.items()
                                                  if k in ('path', 'mtime')}
                            content = source.extractfile(original) if original.isfile() else None
                            try:
                                target.addfile(member, content)
                            finally:
                                if content is not None:
                                    content.close()
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return filename


setup(cmdclass={'sdist': PrivateSdist})
