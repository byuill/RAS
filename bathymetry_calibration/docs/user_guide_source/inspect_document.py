"""Check navigation, page layout and embedded diagrams; render every page for review."""
from pathlib import Path
import json
import math
import zipfile

import pymupdf
from PIL import Image, ImageDraw
from docx import Document

from guide_paths import ROOT
QA = ROOT / 'qa'
QA.mkdir(parents=True, exist_ok=True)
pdf = pymupdf.open(ROOT / 'Bathymetry_Calibration_User_Guide.pdf')
expected = json.loads((QA / 'expected_pages.json').read_text())
assert len(pdf) == len(expected) + 2, f'Unexpected overflow: {len(pdf)} pages'
for item in expected:
    assert item['title'] in pdf[item['page'] - 1].get_text(), item
outline = pdf.get_toc()
parts = [entry for entry in outline if entry[0] == 1 and entry[1].startswith('PART ')]
assert len(parts) == 6, parts
assert len([entry for entry in outline if entry[0] == 2]) == len(expected)
contents_links = pdf[1].get_links()
assert len(contents_links) == len(expected), contents_links
assert sorted(link['page'] + 1 for link in contents_links) == [item['page'] for item in expected]
thumbs, issues = [], []
for i, page in enumerate(pdf):
    # Full-page renders are the visual QA record; diagrams also require inspection.
    page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(QA / f'page-{i+1:02d}.png')
    pix = page.get_pixmap(matrix=pymupdf.Matrix(.53, .53), alpha=False)
    thumb = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
    label = Image.new('RGB', (thumb.width, thumb.height + 22), '#dde5eb')
    label.paste(thumb, (0, 22))
    ImageDraw.Draw(label).text((8, 4), f'Page {i+1}', fill='black')
    thumbs.append(label)
    assert len(page.get_text().strip()) > 50, f'Blank page {i+1}'
    for block in page.get_text('dict')['blocks']:
        x0, y0, x1, y1 = block['bbox']
        if x0 < 20 or x1 > page.rect.width - 20 or y0 < 10 or y1 > page.rect.height - 10:
            issues.append({'page': i+1, 'bbox': list(block['bbox']), 'type': block['type']})
cols = 6
w, h = max(t.width for t in thumbs), max(t.height for t in thumbs)
contact = Image.new('RGB', (cols*w, math.ceil(len(thumbs)/cols)*h), '#c5cfd6')
for i, thumb in enumerate(thumbs):
    contact.paste(thumb, ((i % cols)*w, (i // cols)*h))
contact.save(QA / 'contact-sheet.jpg', quality=92)
doc = Document(ROOT / 'Bathymetry_Calibration_User_Guide.docx')
assert len(doc.inline_shapes) == 16
assert len({s._inline.docPr.get('descr') for s in doc.inline_shapes}) == 16
with zipfile.ZipFile(ROOT / 'Bathymetry_Calibration_User_Guide.docx') as archive:
    assert len([n for n in archive.namelist() if n.startswith('word/media/')]) == 16
    xml = archive.read('word/document.xml').decode()
    for item in expected:
        assert f'w:anchor="{item["bookmark"]}"' in xml
    assert 'REPLACE_WITH' not in xml
    assert 'zₜₐᵣɢₑₜ' not in xml
    assert 'w:vertAlign w:val="subscript"' in xml
assert not issues, issues
report = {
    'pages': len(pdf), 'illustrations': len(doc.inline_shapes),
    'section_page_checks': len(expected), 'chapter_outline_checks': len(parts),
    'contents_link_checks': len(contents_links), 'edge_issues': issues,
    'word_file_bytes': (ROOT / 'Bathymetry_Calibration_User_Guide.docx').stat().st_size,
    'pdf_file_bytes': (ROOT / 'Bathymetry_Calibration_User_Guide.pdf').stat().st_size,
}
(QA / 'document_checks.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
