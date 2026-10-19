"""Regression coverage for graphs lost by PDF text extraction."""
import base64
import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from personal_context.canvas_collect import collect_batches
from personal_context.canvas_mcp_server import register_tools
from personal_context.store import Store


def graph_pdf():
    # A vector bar chart with no extractable text: text-only reading loses it.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>']
    stream = b'0 0 1 rg 20 20 30 70 re f 70 20 30 120 re f'
    objects.append(b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream')
    data = b'%PDF-1.4\n'
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(n).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(data)
    data += b'xref\n0 5\n0000000000 65535 f \n'
    data += b''.join(('%010d 00000 n \n' % offset).encode() for offset in offsets[1:])
    return data + b'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n' + str(xref).encode() + b'\n%%EOF\n'


class CanvasPdfTests(unittest.TestCase):
    def test_collection_retains_original_even_when_extractor_fails(self):
        client = Mock()
        client.pages.side_effect = [[{'id': 7, 'name': 'Fictional'}], [], [],
            [{'id': 9, 'display_name': 'Worksheet', 'filename': 'chart.pdf',
              'url': 'https://canvas.example.invalid/file'}], [], []]
        client.download.return_value = graph_pdf()
        with patch('personal_context.canvas_collect.extract', side_effect=OSError('missing pdftotext')):
            record = collect_batches(client, 'demo', download_files=True)[3]['records'][0]
        self.assertEqual(base64.b64decode(record.get('pdf_base64', '')), graph_pdf())
        self.assertEqual(record['payload']['extraction_status'], 'unavailable')
        self.assertEqual(record['payload']['pdf_status'], 'available')

    @unittest.skipUnless(shutil.which('pdftoppm') and shutil.which('pdfinfo'), 'Poppler required')
    def test_archived_page_returns_actual_graph_image_without_binary_in_record(self):
        from mcp.server.fastmcp import FastMCP
        import asyncio
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / 'key'; key.write_bytes(os.urandom(32)); key.chmod(0o600)
            db = Path(tmp) / 'archive.sqlite3'
            store = Store(db, key_file=key)
            batch = {'schema': 1, 'source': 'canvas-lms', 'kind': 'canvas_file',
                     'scope': 'demo:course:7', 'collected_at': '2026-01-01T00:00:00Z',
                     'complete': True, 'records': [{'id': 'canvas:demo:file:7:9', 'title': 'chart.pdf',
                     'body': '', 'payload': {'pdf_status': 'available', 'extraction_status': 'no_text'},
                     'pdf_base64': base64.b64encode(graph_pdf()).decode()}]}
            store.ingest(batch)
            self.assertNotIn('pdf_base64', str(store.get('canvas_file', 'canvas:demo:file:7:9')))
            store.close()
            functions = {}
            class Registry:
                def tool(self, **kwargs):
                    def capture(function):
                        functions[function.__name__] = function
                        return function
                    return capture
            with patch.dict(os.environ, {'PERSONAL_CONTEXT_DB': str(db), 'PERSONAL_CONTEXT_KEY_FILE': str(key)}):
                register_tools(Registry())
                self.assertIn('view_canvas_pdf_page', functions)
                image = functions['view_canvas_pdf_page']('canvas:demo:file:7:9', page=1)
                from PIL import Image
                preview = Image.open(io.BytesIO(image.data)).convert('RGB')
                self.assertGreater(sum(1 for r,g,b in (preview.get_flattened_data() if hasattr(preview, "get_flattened_data") else preview.getdata()) if b > 150 and r < 80 and g < 80), 500)
                info = functions['canvas_pdf_info']('canvas:demo:file:7:9')
                self.assertEqual(info['pages'], 1)
                text = functions['read_canvas_file_text']('canvas:demo:file:7:9')
                self.assertIn('view_canvas_pdf_page', text['visual_hint'])
                for bad in (0, -1, 2, True):
                    with self.assertRaises(ValueError):
                        functions['view_canvas_pdf_page']('canvas:demo:file:7:9', page=bad)
                # Verify the real MCP result contains an image block, not a path or base64 in JSON.
                mcp = FastMCP('test'); register_tools(mcp)
                result = asyncio.run(mcp.call_tool('view_canvas_pdf_page', {'record_id': 'canvas:demo:file:7:9'}))
                content = result[0] if isinstance(result, tuple) else result
                self.assertEqual(content[0].type, 'image')
            # A newer snapshot with no PDF must not serve obsolete chart bytes.
            batch['collected_at'] = '2026-01-02T00:00:00Z'
            batch['records'][0].pop('pdf_base64')
            store = Store(db, key_file=key); store.ingest(batch); store.close()
            with patch.dict(os.environ, {'PERSONAL_CONTEXT_DB': str(db), 'PERSONAL_CONTEXT_KEY_FILE': str(key)}):
                with self.assertRaisesRegex(ValueError, 'not archived'):
                    functions['view_canvas_pdf_page']('canvas:demo:file:7:9')
