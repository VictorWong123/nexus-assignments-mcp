"""Bounded, offline extraction and visual previews of downloaded course materials."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import signal
import shutil
import subprocess
import tempfile
import warnings
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from defusedxml import ElementTree as SafeET
from PIL import Image, ImageOps

MAX_TEXT = 500_000
MAX_CELLS = 1_000
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000
MAX_IMAGE_PIXELS = 25_000_000
MAX_PREVIEW_SIDE = 2_048
MAX_PAGES = 50
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

MIME_TYPES = {
    'application/pdf': 'pdf',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': 'pptx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'text/csv': 'csv', 'image/png': 'png', 'image/jpeg': 'jpeg',
}
EXTENSIONS = {'.pdf': 'pdf', '.pptx': 'pptx', '.xlsx': 'xlsx', '.docx': 'docx',
              '.csv': 'csv', '.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg',
              '.txt': 'text', '.md': 'text', '.json': 'text', '.xml': 'text',
              '.html': 'text', '.htm': 'text', '.tsv': 'text'}


class MaterialError(RuntimeError):
    """A deliberately credential-free error suitable for tool responses."""


def file_kind(url: str, mime: str = '') -> str | None:
    # Specific Office extensions take precedence over generic binary/text MIME types.
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    if suffix in {'.xls', '.ppt', '.doc', '.xlsm', '.pptm', '.docm'}:
        return None
    return EXTENSIONS.get(suffix) or MIME_TYPES.get(mime) or (
        'text' if mime.startswith('text/') or mime in {
            'application/json', 'application/xml', 'application/xhtml+xml'} else None)


def capabilities(url: str, mime: str = '') -> dict[str, Any]:
    kind = file_kind(url, mime)
    return {'format': kind, 'readable': kind is not None,
            'previewable': kind in {'pdf', 'pptx', 'xlsx', 'docx', 'png', 'jpeg'},
            'renderer_required': kind in {'pptx', 'xlsx', 'docx'}}


def validate_archive(data: bytes) -> None:
    """Validate actual expansion, not just untrusted ZIP metadata; never extract paths."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise MaterialError('Office archive has too many entries')
            if sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
                raise MaterialError('Office archive exceeds decompression limit')
            total = 0
            for member in members:
                if member.flag_bits & 1:
                    raise MaterialError('Encrypted Office files are not supported')
                if 'vbaproject' in member.filename.lower():
                    raise MaterialError('Macro-enabled files are not supported')
                with archive.open(member) as stream:
                    while block := stream.read(64 * 1024):
                        total += len(block)
                        if total > MAX_ARCHIVE_BYTES:
                            raise MaterialError('Office archive exceeds decompression limit')
    except MaterialError:
        raise
    except Exception:
        raise MaterialError('Corrupt or encrypted Office archive') from None


class Budget:
    def __init__(self):
        self.remaining = MAX_TEXT
        self.truncated = False

    def text(self, value: Any) -> str:
        value = str(value or '')
        result = value[:self.remaining]
        self.remaining -= len(result)
        self.truncated |= len(result) < len(value)
        return result


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _cell(cell, cached, budget: Budget) -> dict[str, Any]:
    raw = cell.value
    if cell.data_type == 'f' and not isinstance(raw, str):
        raw = getattr(raw, 'text', None) or '[Unsupported saved formula]'
    value = _scalar(raw)
    if isinstance(value, str):
        value = budget.text(value)
    result = {'address': cell.coordinate, 'value': value, 'formula': None,
              'cached_value': None, 'cached_value_missing': False}
    if cell.data_type == 'f':
        result.update(value=None, formula=value, cached_value=_scalar(cached.value),
                      cached_value_missing=cached.value is None)
        if isinstance(result['cached_value'], str):
            result['cached_value'] = budget.text(result['cached_value'])
    return result


def _workbook(data: bytes):
    from openpyxl import load_workbook
    validate_archive(data)
    book = None
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        cached = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        return book, cached
    except Exception:
        if book is not None:
            book.close()
        raise MaterialError('Could not read XLSX file; it may be corrupt or encrypted') from None


def spreadsheet(data: bytes, kind: str, sheet: str | None = None,
                cell_range: str | None = None) -> dict[str, Any]:
    """No calculation engine: formula results come exclusively from saved caches."""
    from openpyxl.utils.cell import range_boundaries, get_column_letter
    budget = Budget()
    if cell_range:
        try:
            left, top, right, bottom = range_boundaries(cell_range.upper())
            if (None in (left, top, right, bottom) or left < 1 or top < 1 or
                    right < left or bottom < top or right > 16384 or bottom > 1048576):
                raise ValueError
            if (right - left + 1) * (bottom - top + 1) > MAX_CELLS:
                raise MaterialError('Request at most 1,000 cells per range')
        except MaterialError:
            raise
        except (TypeError, ValueError):
            raise MaterialError('cell_range must be an A1 range such as A1:D20') from None
    else:
        left, top, right, bottom = 1, 1, 20, 50
    sheets = []
    if kind == 'csv':
        if sheet not in (None, 'CSV'):
            raise MaterialError('CSV sheet name must be CSV')
        csv.field_size_limit(10 * 1024 * 1024)
        rows = csv.reader(io.StringIO(data.decode('utf-8-sig', errors='replace')))
        cells, row_count, columns = [], 0, 0
        for row_count, row in enumerate(rows, 1):
            columns = max(columns, len(row))
            if top <= row_count <= bottom:
                for column in range(left, min(right, len(row)) + 1):
                    cells.append({'address': f'{get_column_letter(column)}{row_count}',
                                  'value': budget.text(row[column - 1]), 'formula': None,
                                  'cached_value': None, 'cached_value_missing': False})
        sheets.append({'name': 'CSV', 'rows': row_count, 'columns': columns, 'cells': cells,
                       'truncated': not cell_range and (row_count > bottom or columns > right)})
        names = ['CSV']
    elif kind == 'xlsx':
        book, cached = _workbook(data)
        try:
            names = book.sheetnames
            if sheet is not None and sheet not in names:
                raise MaterialError('Sheet not found; use a sheet name returned by read_file')
            remaining = MAX_CELLS
            for name in ([sheet] if sheet else names):
                ws = book[name]
                max_row, max_col = ws.max_row or 0, ws.max_column or 0
                rbottom, rright = min(bottom, max_row), min(right, max_col)
                cells = []
                visited = 0
                if remaining and rbottom >= top and rright >= left:
                    values = ws.iter_rows(min_row=top, max_row=rbottom, min_col=left, max_col=rright)
                    caches = cached[name].iter_rows(min_row=top, max_row=rbottom, min_col=left, max_col=rright)
                    for row, cached_row in zip(values, caches):
                        for cell, saved in zip(row, cached_row):
                            if remaining == 0:
                                break
                            # EmptyCell lacks coordinate; blank cells need no source entry.
                            if cell.value is not None:
                                cells.append(_cell(cell, saved, budget))
                            remaining -= 1
                            visited += 1
                        if remaining == 0:
                            break
                total = max(0, rbottom - top + 1) * max(0, rright - left + 1)
                sheets.append({'name': name, 'rows': max_row, 'columns': max_col,
                               'cells': cells, 'truncated': total > visited
                               or (not cell_range and (max_row > bottom or max_col > right))})
        finally:
            book.close()
            cached.close()
    else:
        raise MaterialError('Targeted cell reading supports XLSX and CSV files')
    return {'sheet_names': names, 'sheets': sheets, 'cell_range': cell_range,
            'truncated': budget.truncated or any(s['truncated'] for s in sheets),
            'next': 'Use read_spreadsheet(url, sheet, cell_range) for another A1 range.',
            'formula_policy': 'Saved formulas and cached results only; no formulas executed.'}


def _image(data: bytes):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(data))
            if source.format not in {'PNG', 'JPEG'}:
                raise MaterialError('Expected a PNG or JPEG image')
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise MaterialError('Image exceeds 25-million-pixel limit')
            source.load()
            return ImageOps.exif_transpose(source)
    except MaterialError:
        raise
    except Exception:
        raise MaterialError('Corrupt or oversized image') from None


def extract(data: bytes, kind: str, page: int | None = None) -> dict[str, Any]:
    budget = Budget()
    result: dict[str, Any] = {'type': kind, 'warning': None, 'truncated': False}
    pieces = []
    try:
        if kind in {'xlsx', 'csv'}:
            result.update(spreadsheet(data, kind))
            # content is a convenient compatibility summary; structured cells are authoritative.
            pieces = [json.dumps(result['sheets'], ensure_ascii=False)]
        elif kind == 'pptx':
            from pptx import Presentation
            validate_archive(data)
            deck = Presentation(io.BytesIO(data))
            slides = []
            if page is not None and page > len(deck.slides):
                raise MaterialError(f"page exceeds slide count ({len(deck.slides)})")
            selected = [(page, deck.slides[page - 1])] if page else enumerate(deck.slides, 1)
            for number, slide in selected:
                if (page is None and number > MAX_PAGES) or budget.remaining == 0:
                    budget.truncated = True
                    break
                texts, tables = [], []
                def shapes(items):
                    for shape in items:
                        if hasattr(shape, 'shapes'):
                            shapes(shape.shapes)
                        if shape.has_text_frame:
                            texts.append(budget.text(shape.text))
                        if shape.has_table:
                            tables.append([[budget.text(c.text) for c in row.cells]
                                           for row in shape.table.rows])
                shapes(slide.shapes)
                notes = ''
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                    notes = budget.text(slide.notes_slide.notes_text_frame.text)
                slides.append({'slide': number, 'text': texts, 'tables': tables, 'notes': notes})
            result.update(slides=slides, slide_count=len(deck.slides))
            pieces = [json.dumps(slides, ensure_ascii=False)]
        elif kind == 'docx':
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            validate_archive(data)
            doc = Document(io.BytesIO(data))
            blocks = []
            for item in doc.iter_inner_content():
                if budget.remaining == 0:
                    budget.truncated = True
                    break
                if isinstance(item, Paragraph):
                    blocks.append({'block': len(blocks) + 1, 'type': 'paragraph',
                                   'text': budget.text(item.text)})
                elif isinstance(item, Table):
                    blocks.append({'block': len(blocks) + 1, 'type': 'table',
                                   'rows': [[budget.text(c.text) for c in row.cells] for row in item.rows]})
            result['blocks'] = blocks
            pieces = [json.dumps(blocks, ensure_ascii=False)]
        elif kind in {'png', 'jpeg'}:
            image = _image(data)
            result.update(width=image.width, height=image.height)
            result['warning'] = 'Use preview_file to inspect the image; OCR is not performed.'
        elif kind == 'text':
            pieces = [budget.text(data.decode('utf-8-sig', errors='replace'))]
        else:
            raise MaterialError('Unsupported file type')
    except MaterialError:
        raise
    except Exception:
        raise MaterialError(f'Could not read {kind.upper()} file; it may be corrupt or encrypted') from None
    content = '\n\n'.join(pieces)
    result['content'] = content[:MAX_TEXT]
    result['truncated'] |= budget.truncated or len(content) > MAX_TEXT
    result.setdefault('next', 'Use preview_file(url, page) to inspect a specific slide or page.')
    return result


def _office_pdf(data: bytes, kind: str, directory: Path) -> Path:
    executable = shutil.which('libreoffice') or shutil.which('soffice')
    if not executable:
        raise MaterialError('Office renderer unavailable; install LibreOffice. Structured reading still works.')
    validate_archive(data)
    # Reject automatically fetched relationships and embedded active content before rendering.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if ('/embeddings/' in name.lower() or '/externallinks/' in name.lower()
                    or name.lower() == 'xl/connections.xml' or '/querytables/' in name.lower()):
                raise MaterialError('Preview unavailable for embedded objects or external data connections')
            if name.endswith('.rels'):
                root = SafeET.fromstring(archive.read(name))
                for relationship in root:
                    if (relationship.get('TargetMode') == 'External' and
                            not relationship.get('Type', '').endswith('/hyperlink')):
                        raise MaterialError('Preview unavailable for externally linked content')
    source = directory / f'material.{kind}'
    if kind == 'xlsx':
        # Render a static copy: replace formulas with caches, preserving charts and cell styles.
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(source, 'w') as target:
            for member in original.infolist():
                body = original.read(member)
                ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                if member.filename == 'xl/workbook.xml':
                    root = SafeET.fromstring(body)
                    # Defined-name expressions can also carry executable formulas.
                    names = root.find(ns + 'definedNames')
                    if names is not None:
                        root.remove(names)
                    calc = root.find(ns + 'calcPr')
                    if calc is None:
                        calc = ET.SubElement(root, ns + 'calcPr')
                    calc.attrib.update(calcMode='manual', fullCalcOnLoad='0', forceFullCalc='0')
                    body = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                elif member.filename.startswith('xl/worksheets/') and member.filename.endswith('.xml'):
                    root = SafeET.fromstring(body)
                    for cell in root.iter(ns + 'c'):
                        formula = cell.find(ns + 'f')
                        if formula is not None:
                            cell.remove(formula)
                            value = cell.find(ns + 'v')
                            if value is None or value.text is None:
                                if value is not None:
                                    cell.remove(value)
                                cell.set('t', 'inlineStr')
                                text = ET.SubElement(ET.SubElement(cell, ns + 'is'), ns + 't')
                                text.text = '[No cached value]'
                    # These features can contain expressions as well.
                    for tag in ('conditionalFormatting', 'dataValidations', 'extLst'):
                        for child in root.findall(ns + tag):
                            root.remove(child)
                    body = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                elif member.filename.startswith('xl/tables/') and member.filename.endswith('.xml'):
                    root = SafeET.fromstring(body)
                    for column in root.iter(ns + 'tableColumn'):
                        column.attrib.pop('totalsRowFunction', None)
                        for tag in ('calculatedColumnFormula', 'totalsRowFormula'):
                            for expression in column.findall(ns + tag):
                                column.remove(expression)
                    body = ET.tostring(root, encoding='utf-8', xml_declaration=True)
                target.writestr(member, body)
    else:
        source.write_bytes(data)
    profile = directory / 'profile'
    (profile / 'user').mkdir(parents=True)
    (profile / 'user' / 'registrymodifications.xcu').write_text('''<?xml version="1.0"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>''')
    pdf_filter = 'pdf'
    if kind == 'xlsx':
        pdf_filter = 'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}'
    _run_renderer([executable, f'-env:UserInstallation={profile.as_uri()}', '--headless',
                   '--nologo', '--nodefault', '--norestore', '--convert-to', pdf_filter,
                   '--outdir', str(directory), str(source)], directory)
    output = directory / 'material.pdf'
    if not output.exists() or output.stat().st_size == 0:
        raise MaterialError('Office renderer produced no preview')
    if output.stat().st_size > MAX_ARCHIVE_BYTES:
        raise MaterialError('Rendered PDF exceeds size limit')
    return output


def _run_renderer(command: list[str], directory: Path) -> None:
    # Do not pass Nexus credentials or the user's Office profile to the renderer.
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'LD_LIBRARY_PATH'}}
    env.update(HOME=str(directory), TMPDIR=str(directory))
    process = None
    try:
        process = subprocess.Popen(command, env=env, start_new_session=os.name == 'posix',
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if process.wait(timeout=30) != 0:
            raise MaterialError('Office preview conversion failed; structured reading may still work')
    except subprocess.TimeoutExpired:
        raise MaterialError('Office preview timed out after 30 seconds') from None
    except OSError:
        raise MaterialError('Office preview could not start; structured reading still works') from None
    finally:
        if process is not None:
            # Kill the whole conversion group, including any surviving soffice.bin child.
            if os.name == 'posix':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait()


def preview(data: bytes, kind: str, page: int = 1, sheet: str | None = None) -> tuple[dict, bytes]:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise MaterialError('page must be a positive integer')
    if sheet is not None and kind != 'xlsx':
        raise MaterialError('sheet is only supported for XLSX previews')
    metadata: dict[str, Any] = {'type': kind, 'page': page, 'sheet': sheet}
    sheet_names = []
    if kind == 'xlsx':
        book, cache = _workbook(data)
        try:
            sheet_names = book.sheetnames
        finally:
            book.close()
            cache.close()
        if sheet is not None and sheet not in sheet_names:
            raise MaterialError('Sheet not found; use a sheet name returned by read_file')
        if sheet is not None and page != 1:
            raise MaterialError('Spreadsheet previews use one page per sheet; page must be 1 with sheet')
    try:
        if kind in {'png', 'jpeg'}:
            if page != 1:
                raise MaterialError('Images have only one page')
            image = _image(data)
            metadata['page_count'] = 1
        else:
            import pypdfium2 as pdfium
            if kind not in {'pdf', 'pptx', 'docx', 'xlsx'}:
                raise MaterialError('Visual previews support PDF, PPTX, DOCX, XLSX, PNG, and JPEG')
            with tempfile.TemporaryDirectory(prefix='nexus-preview-') as temp:
                if kind != 'pdf':
                    output = _office_pdf(data, kind, Path(temp))
                    data = output.read_bytes()
                with pdfium.PdfDocument(data) as document:
                    count = len(document)
                    if count == 0:
                        raise MaterialError('Document has no preview pages')
                    target = page
                    if kind == 'xlsx':
                        metadata['sheet_names'] = sheet_names
                        if count != len(sheet_names):
                            raise MaterialError('Renderer sheet mapping unavailable; use structured cell reading')
                        target = sheet_names.index(sheet) + 1 if sheet else page
                        if 1 <= target <= len(sheet_names):
                            metadata['sheet'] = sheet_names[target - 1]
                        metadata['preview_layout'] = 'One rendered page per sheet, fitted to 2,048 pixels.'
                        metadata['warning'] = ('Static preview using saved formula results; missing results '
                                               'are labeled. Conditional formatting and named ranges are omitted. '
                                               'Use read_spreadsheet for original formulas and exact values.')
                    if target > count:
                        raise MaterialError(f'page exceeds page count ({count})')
                    pdf_page = document[target - 1]
                    try:
                        width, height = pdf_page.get_size()
                        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                            raise MaterialError('Invalid preview page dimensions')
                        bitmap = pdf_page.render(scale=min(2, MAX_PREVIEW_SIDE / max(width, height)))
                        try:
                            image = bitmap.to_pil().copy()
                        finally:
                            bitmap.close()
                    finally:
                        pdf_page.close()
                    metadata['page_count'] = count
        image.thumbnail((MAX_PREVIEW_SIDE, MAX_PREVIEW_SIDE))
        image = image.convert('RGB')
        metadata.update(width=image.width, height=image.height,
                        empty=image.getextrema() == ((255, 255),) * 3)
        if metadata['empty']:
            metadata['warning'] = 'The rendered page is blank.'
        output = io.BytesIO()
        image.save(output, format='PNG')
        return metadata, output.getvalue()
    except MaterialError:
        raise
    except Exception:
        raise MaterialError('Could not preview file; it may be corrupt, encrypted, or unsupported') from None
