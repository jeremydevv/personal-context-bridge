"""Bounded local rendering of untrusted Canvas PDFs with Poppler."""
import re
import subprocess
import tempfile
from pathlib import Path

MAX_FILE_BYTES = 64 * 1024 * 1024


def _run(command):
    try:
        result = subprocess.run(command, capture_output=True, timeout=30)
    except FileNotFoundError as exc:
        raise RuntimeError('PDF viewing requires Poppler (pdfinfo and pdftoppm) on the archive server') from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError('PDF processing exceeded the time limit') from exc
    if result.returncode:
        raise ValueError('PDF processing failed; the document may be invalid or locked')
    return result.stdout


def _write_pdf(directory, data):
    if not data.startswith(b'%PDF-') or len(data) > MAX_FILE_BYTES:
        raise ValueError('invalid or oversized PDF')
    path = Path(directory) / 'source.pdf'
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def pdf_info(data):
    with tempfile.TemporaryDirectory(prefix='canvas-pdf-') as directory:
        source = _write_pdf(directory, data)
        output = _run(['pdfinfo', str(source)]).decode('utf-8', errors='replace')
    match = re.search(r'^Pages:\s+(\d+)\s*$', output, re.MULTILINE)
    if not match or int(match[1]) < 1:
        raise ValueError('PDF page count unavailable')
    return {'pages': int(match[1]), 'bytes': len(data)}


def render_page(data, page):
    if type(page) is not int or page < 1:
        raise ValueError('page must be a positive integer starting at 1')
    if page > pdf_info(data)['pages']:
        raise ValueError('page exceeds PDF page count')
    with tempfile.TemporaryDirectory(prefix='canvas-pdf-') as directory:
        source = _write_pdf(directory, data)
        output = Path(directory) / 'page'
        _run(['pdftoppm', '-f', str(page), '-l', str(page), '-singlefile',
              '-scale-to', '1800', '-png', str(source), str(output)])
        path = output.with_suffix('.png')
        if not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError('PDF preview unavailable or exceeds size limit')
        return path.read_bytes()
