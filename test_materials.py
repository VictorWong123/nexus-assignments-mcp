"""Self-contained document fixtures; no Nexus account or network required."""
import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch, Mock

from docx import Document
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfReader, PdfWriter

import materials
import server
import test_server as existing

URL = 'https://nexus.union.edu/pluginfile.php/1/'


def saved(document):
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def presentation():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = 'Lecture 1'
    slide.placeholders[1].text = 'Energy and motion'
    slide.notes_slide.notes_text_frame.text = 'Explain the diagram'
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(4), Inches(1)).table
    table.cell(0, 0).text = 'Mass'
    table.cell(1, 0).text = '10'
    second = deck.slides.add_slide(deck.slide_layouts[1])
    second.shapes.title.text = 'Lecture 2'
    return saved(deck)


def workbook(cached=False):
    book = Workbook()
    ws = book.active
    ws.title = 'Results'
    ws.append(['Trial', 'Value'])
    ws.append(['First', 3])
    ws.append(['Second', 4])
    ws['C2'] = '=1+1'
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    ws.add_chart(chart, 'E2')
    book.create_sheet('Notes')['A1'] = 'Second sheet'
    data = saved(book)
    if cached:
        target = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(target, 'w') as output:
            for member in original.infolist():
                body = original.read(member)
                if member.filename == 'xl/worksheets/sheet1.xml':
                    body = body.replace(b'<f>1+1</f><v></v>', b'<f>1+1</f><v>99</v>')
                output.writestr(member, body)
        return target.getvalue()
    return data


def document():
    doc = Document()
    doc.add_paragraph('Before table')
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = 'Data'
    table.cell(0, 1).text = '42'
    doc.add_paragraph('After table')
    return saved(doc)


def pdf(pages=2):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def image_bytes(fmt='PNG', size=(3000, 1000)):
    stream = io.BytesIO()
    Image.new('RGB', size, 'navy').save(stream, format=fmt)
    return stream.getvalue()


class MaterialTests(unittest.TestCase):
    def test_slide_text_notes_tables_and_targeting(self):
        data = presentation()
        result = materials.extract(data, 'pptx')
        self.assertEqual(result['slide_count'], 2)
        self.assertEqual(result['slides'][0]['slide'], 1)
        self.assertIn('Energy and motion', result['slides'][0]['text'])
        self.assertIn('Explain the diagram', result['slides'][0]['notes'])
        self.assertEqual(result['slides'][0]['tables'][0][0][0], 'Mass')
        selected = materials.extract(data, 'pptx', page=2)
        self.assertEqual([s['slide'] for s in selected['slides']], [2])
        with self.assertRaisesRegex(materials.MaterialError, 'slide count'):
            materials.extract(data, 'pptx', page=3)
        with patch.object(materials, 'MAX_PAGES', 1):
            self.assertTrue(materials.extract(data, 'pptx')['truncated'])

    def test_docx_keeps_block_order(self):
        blocks = materials.extract(document(), 'docx')['blocks']
        self.assertEqual([b['type'] for b in blocks], ['paragraph', 'table', 'paragraph'])
        self.assertEqual(blocks[1]['rows'], [['Data', '42']])

    def test_workbook_formulas_and_cache(self):
        for cache, expected in [(False, None), (True, 99)]:
            result = materials.spreadsheet(workbook(cache), 'xlsx', 'Results', 'B2:C2')
            self.assertEqual(result['sheet_names'], ['Results', 'Notes'])
            cells = result['sheets'][0]['cells']
            self.assertEqual(cells[0]['address'], 'B2')
            self.assertEqual(cells[0]['value'], 3)
            self.assertEqual(cells[1]['formula'], '=1+1')
            self.assertEqual(cells[1]['cached_value'], expected)
            self.assertEqual(cells[1]['cached_value_missing'], not cache)

    def test_range_validation_and_sheet_errors(self):
        data = workbook()
        for invalid in ['A:A', '1:5', 'A0:B2', 'B2:A1', 'A1:XFD2', 'junk', 'A1:A1048577']:
            with self.subTest(invalid=invalid), self.assertRaises(materials.MaterialError):
                materials.spreadsheet(data, 'xlsx', 'Results', invalid)
        with self.assertRaisesRegex(materials.MaterialError, 'Sheet not found'):
            materials.spreadsheet(data, 'xlsx', 'Missing', 'A1')

    def test_sheet_preview_budget_and_targeted_followup(self):
        book = Workbook()
        for _ in range(60):
            book.active.append(list(range(25)))
        data = saved(book)
        result = materials.extract(data, 'xlsx')
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['sheets'][0]['cells']), 1000)
        result = materials.spreadsheet(data, 'xlsx', 'Sheet', 'Y60')
        self.assertEqual(result['sheets'][0]['cells'][0]['value'], 24)
        self.assertFalse(result['truncated'])

    def test_csv_preserves_addresses_and_does_not_execute_formulas(self):
        data = b'\xef\xbb\xbfname,value\n"a,b",=1+1\n'
        result = materials.spreadsheet(data, 'csv', 'CSV', 'A2:B2')
        self.assertEqual(result['sheets'][0]['cells'][0]['value'], 'a,b')
        self.assertEqual(result['sheets'][0]['cells'][1]['value'], '=1+1')
        self.assertIsNone(result['sheets'][0]['cells'][1]['formula'])

    def test_text_truncation(self):
        with patch.object(materials, 'MAX_TEXT', 10):
            result = materials.extract(b'x' * 20, 'text')
            self.assertEqual(result['content'], 'x' * 10)
            self.assertTrue(result['truncated'])

    def test_archive_limits_and_corruption(self):
        with self.assertRaisesRegex(materials.MaterialError, 'Corrupt'):
            materials.extract(b'broken', 'docx')
        data = document()
        with patch.object(materials, 'MAX_ARCHIVE_BYTES', 10):
            with self.assertRaisesRegex(materials.MaterialError, 'decompression'):
                materials.extract(data, 'docx')
        with patch.object(materials, 'MAX_ARCHIVE_MEMBERS', 1):
            with self.assertRaisesRegex(materials.MaterialError, 'entries'):
                materials.extract(data, 'docx')

    def test_image_metadata_preview_bounds_and_pixel_limit(self):
        for fmt in ['PNG', 'JPEG']:
            data = image_bytes(fmt)
            self.assertEqual(materials.extract(data, fmt.lower())['width'], 3000)
            info, image = materials.preview(data, fmt.lower())
            self.assertLessEqual(info['width'], 2048)
            self.assertLessEqual(info['height'], 2048)
            self.assertEqual(Image.open(io.BytesIO(image)).format, 'PNG')
        with patch.object(materials, 'MAX_IMAGE_PIXELS', 1):
            with self.assertRaisesRegex(materials.MaterialError, 'pixel limit'):
                materials.preview(data, 'jpeg')

    def test_pdf_preview_navigation_and_blank_warning(self):
        info, _ = materials.preview(pdf(), 'pdf', page=2)
        self.assertEqual(info['page_count'], 2)
        self.assertTrue(info['empty'])
        for page in [0, -1, 3, True]:
            with self.subTest(page=page), self.assertRaises(materials.MaterialError):
                materials.preview(pdf(), 'pdf', page)
        with self.assertRaises(materials.MaterialError):
            materials.preview(b'broken', 'pdf')

    def test_missing_renderer_does_not_break_extraction(self):
        data = presentation()
        with patch.object(materials.shutil, 'which', return_value=None):
            self.assertIn('slides', materials.extract(data, 'pptx'))
            with self.assertRaisesRegex(materials.MaterialError, 'renderer unavailable'):
                materials.preview(data, 'pptx')

    def test_conversion_failure_cleans_temp_directory(self):
        seen = []
        def fail(_data, _kind, directory):
            seen.append(directory)
            raise materials.MaterialError('conversion failed')
        with patch.object(materials, '_office_pdf', side_effect=fail):
            with self.assertRaisesRegex(materials.MaterialError, 'conversion failed'):
                materials.preview(document(), 'docx')
        self.assertFalse(seen[0].exists())

    def test_timeout_kills_renderer_and_suppresses_credentials(self):
        process = Mock(pid=123456789)
        process.wait.side_effect = [subprocess.TimeoutExpired('office', 30), 0]
        with patch.object(materials.subprocess, 'Popen', return_value=process) as popen:
            with patch.object(materials.os, 'killpg') as kill:
                with patch.dict(os.environ, {'NEXUS_TOKEN': 'secret'}):
                    with self.assertRaisesRegex(materials.MaterialError, 'timed out'):
                        materials._run_renderer(['office'], Path('/tmp'))
                self.assertNotIn('NEXUS_TOKEN', popen.call_args.kwargs['env'])
                if os.name == 'posix':
                    kill.assert_called_once()

    def test_external_relationships_rejected_before_conversion(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('word/_rels/document.xml.rels',
                '<Relationships><Relationship TargetMode="External" Type="image" '
                'Target="https://example.com/pixel"/></Relationships>')
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(materials.shutil, 'which', return_value='/office'):
                with self.assertRaisesRegex(materials.MaterialError, 'externally linked'):
                    materials._office_pdf(stream.getvalue(), 'docx', Path(temp))

    def test_external_data_connections_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('xl/connections.xml', '<connections/>')
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(materials.shutil, 'which', return_value='/office'):
                with self.assertRaisesRegex(materials.MaterialError, 'external data connections'):
                    materials._office_pdf(stream.getvalue(), 'xlsx', Path(temp))

    def test_conversion_failure_and_missing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(materials.shutil, 'which', return_value='/office'):
                with patch.object(materials, '_run_renderer'):
                    with self.assertRaisesRegex(materials.MaterialError, 'no preview'):
                        materials._office_pdf(document(), 'docx', Path(temp))
        process = Mock(pid=123456789)
        process.wait.return_value = 1
        with patch.object(materials.subprocess, 'Popen', return_value=process):
            with patch.object(materials.os, 'killpg'):
                with self.assertRaisesRegex(materials.MaterialError, 'conversion failed'):
                    materials._run_renderer(['office'], Path('/tmp'))



class ToolTests(unittest.TestCase):
    client = existing.NexusServerTest.client

    def test_new_file_formats_and_redaction(self):
        doc = Document()
        doc.add_paragraph('top-secret-token token=private')
        result = self.client(saved(doc), 'application/octet-stream').read_file(URL + 'file.docx')
        self.assertNotIn('top-secret-token', json.dumps(result))
        self.assertNotIn('token=private', json.dumps(result))
        self.assertEqual(result['type'], 'docx')

    def test_pdf_reading_supports_page_selection_and_truncation(self):
        data = pdf(3)
        result = self.client(data, 'application/pdf').read_file(URL + 'slides.pdf', page=2)
        self.assertEqual([p['page'] for p in result['pages']], [2])
        with patch.object(server, 'MAX_PDF_PAGES', 1):
            result = self.client(data, 'application/pdf').read_file(URL + 'slides.pdf')
        self.assertTrue(result['truncated'])
        self.assertEqual(result['page_count'], 3)

    def test_discovery_context_paths_and_external_links(self):
        client = existing._FakeClient([('core_course_get_contents', [{
            'id': 1, 'name': 'Week 1', 'modules': [{
                'id': 2, 'name': 'Materials', 'modname': 'folder', 'uservisible': True,
                'contents': [{'type': 'file', 'filename': 'lecture.pptx', 'filepath': '/week1/',
                              'fileurl': URL + 'lecture.pptx?token=old', 'filesize': 123},
                             {'type': 'url', 'fileurl': 'https://docs.google.com/presentation/123'}]}]}])])
        with patch.object(server, 'MoodleClient', return_value=client):
            result = server.list_course_files(9)
        file = result['files'][0]
        self.assertEqual((file['section'], file['activity'], file['path']),
                         ('Week 1', 'Materials', '/week1/'))
        self.assertTrue(file['readable'] and file['previewable'])
        self.assertNotIn('token=', file['url'])
        self.assertTrue(result['links'][0]['external'])

    def test_preview_tool_returns_native_mcp_image_and_metadata(self):
        client = self.client(image_bytes(), 'image/png')
        with patch.object(server, 'MoodleClient', return_value=client):
            result = server.preview_file(URL + 'picture.png')
        metadata = json.loads(result[0].text)
        self.assertEqual(metadata['url'], URL + 'picture.png')
        self.assertEqual(result[1].type, 'image')
        self.assertEqual(result[1].mimeType, 'image/png')
        self.assertTrue(base64.b64decode(result[1].data).startswith(b'\x89PNG'))

    def test_targeted_tool_uses_authenticated_download(self):
        client = self.client(workbook(), 'application/octet-stream')
        with patch.object(server, 'MoodleClient', return_value=client):
            result = server.read_spreadsheet(URL + 'results.xlsx', 'Notes', 'A1')
        self.assertEqual(result['sheets'][0]['cells'][0]['value'], 'Second sheet')
        self.assertIn('/webservice/pluginfile.php/', client.opener.request.full_url)

    def test_new_tools_are_registered_read_only(self):
        tools = asyncio.run(server.mcp.list_tools())
        by_name = {tool.name: tool for tool in tools}
        for name in ['list_course_files', 'read_spreadsheet', 'preview_file']:
            self.assertTrue(by_name[name].annotations.readOnlyHint)

    def test_mcp_client_receives_image_content(self):
        from fastmcp import Client
        client = self.client(image_bytes(size=(100, 50)), 'image/png')
        async def invoke():
            async with Client(server.mcp) as connection:
                return await connection.call_tool('preview_file', {'url': URL + 'image.png'})
        with patch.object(server, 'MoodleClient', return_value=client):
            result = asyncio.run(invoke())
        self.assertFalse(result.is_error)
        self.assertEqual([block.type for block in result.content], ['text', 'image'])

    def test_corrupt_encrypted_and_oversized_files_return_safe_errors(self):
        for name in ['file.xlsx', 'file.pptx', 'file.docx']:
            client = self.client(b'not-an-office-file', 'application/octet-stream')
            with patch.object(server, 'MoodleClient', return_value=client):
                with self.assertRaises(server.NexusError):
                    server.preview_file(URL + name)
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=100)
        writer.encrypt('password')
        stream = io.BytesIO()
        writer.write(stream)
        client = self.client(stream.getvalue(), 'application/pdf')
        with self.assertRaises(server.NexusError):
            client.read_file(URL + 'encrypted.pdf')
        with patch.object(server, 'MAX_FILE_BYTES', 10):
            with self.assertRaisesRegex(server.NexusError, '10 MB'):
                self.client(b'x' * 11, 'text/plain').read_file(URL + 'large.txt')
        client = self.client(b'{}', 'text/plain')
        client.opener.response.headers['Content-Length'] = str(server.MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(server.NexusError, '10 MB'):
            client.read_file(URL + 'large.txt')



@unittest.skipUnless(shutil.which('soffice') or shutil.which('libreoffice'), 'LibreOffice not installed')
class RenderingIntegrationTests(unittest.TestCase):
    def test_real_office_previews(self):
        for kind, data, page, sheet in [('pptx', presentation(), 2, None),
                                         ('docx', document(), 1, None),
                                         ('xlsx', workbook(True), 1, 'Notes')]:
            with self.subTest(kind=kind):
                info, image = materials.preview(data, kind, page=page, sheet=sheet)
                self.assertFalse(info['empty'])
                self.assertLessEqual(max(info['width'], info['height']), 2048)
                self.assertTrue(image.startswith(b'\x89PNG'))
                if kind == 'xlsx':
                    self.assertEqual(info['sheet'], 'Notes')
                    self.assertEqual(info['page_count'], 2)

    def test_spreadsheet_render_uses_saved_cache_without_recalculation(self):
        with tempfile.TemporaryDirectory() as temp:
            output = materials._office_pdf(workbook(True), 'xlsx', Path(temp))
            text = '\n'.join(page.extract_text() for page in PdfReader(output).pages)
            self.assertIn('99', text)  # Saved cache for =1+1 is intentionally 99, not 2.
            self.assertIn('Second sheet', text)
            self.assertIn('Value', text)


if __name__ == '__main__':
    unittest.main()
