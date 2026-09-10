"""模组文本提取测试 — 阶段 5.1（goal §7）。

纯函数测试：不碰 DB、不花 token、不联网。DOCX / PDF 样例都在内存里现场构造，
所以 CI 与本地行为一致。真实 PDF 模组的提取质量由阶段 5 收尾的浏览器实测覆盖。
"""
import io
import zipfile

import pytest

import app.agent.module_parser as parser
from app.agent.module_parser import (
    MAX_UPLOAD_BYTES,
    detect_source_type,
    extract_text,
    normalize_text,
)


def _docx_bytes(paragraphs: list[str], *, with_document: bool = True) -> bytes:
    """最小 DOCX：提取逻辑只认 word/document.xml，故只造这一个部件。"""
    body = ''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        if with_document:
            zf.writestr('word/document.xml', xml)
        zf.writestr('[Content_Types].xml', '<Types/>')
    return buf.getvalue()


def _pdf_bytes(text: str) -> bytes:
    """手工拼一个单页最小 PDF：xref 偏移按实际字节长度算，pypdf 可正常解析。"""
    content = f'BT /F1 24 Tf 40 100 Td ({text}) Tj ET'.encode('latin-1')
    objs = [
        b'<</Type/Catalog/Pages 2 0 R>>',
        b'<</Type/Pages/Kids[3 0 R]/Count 1>>',
        b'<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]'
        b'/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>',
        b'<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>',
        b'<</Length ' + str(len(content)).encode() + b'>>\nstream\n' + content + b'\nendstream',
    ]
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for index, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f'{index} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref_pos = len(out)
    out += f'xref\n0 {len(objs) + 1}\n'.encode() + b'0000000000 65535 f \n'
    for offset in offsets:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += (f'trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\n'
            f'startxref\n{xref_pos}\n%%EOF\n').encode()
    return bytes(out)


# ---------- 格式判定与文本规整 ----------

def test_detect_source_type_supported_and_unsupported():
    assert detect_source_type('雪盲.docx') == 'docx'
    assert detect_source_type('八月二十二日.PDF') == 'pdf'
    assert detect_source_type('notes.TXT') == 'txt'
    assert detect_source_type('notes.md') == 'txt'
    with pytest.raises(ValueError, match='仅支持'):
        detect_source_type('模组.exe')
    with pytest.raises(ValueError, match='仅支持'):
        detect_source_type('无扩展名')


def test_normalize_text_collapses_blank_lines_and_crlf():
    raw = '第一段\r\n\r\n\r\n\r\n第二段   \n\n\n第三段\n\n'
    assert normalize_text(raw) == '第一段\n\n第二段\n\n第三段'


# ---------- TXT ----------

def test_extract_txt_utf8():
    source_type, text = extract_text('雪盲.txt', '钟摆在十一点四十七分停住。'.encode('utf-8'))
    assert source_type == 'txt'
    assert text == '钟摆在十一点四十七分停住。'


def test_extract_txt_gb18030_fallback():
    """中文老模组常见 GBK 编码：按编码链回退，不许整份丢弃。"""
    raw = '守秘人须知：本模组为三幕。'.encode('gb18030')
    _, text = extract_text('守秘人.txt', raw)
    assert text == '守秘人须知：本模组为三幕。'


def test_extract_txt_empty_raises():
    with pytest.raises(ValueError, match='为空'):
        extract_text('空.txt', b'')


# ---------- DOCX ----------

def test_extract_docx_paragraphs_and_entities():
    data = _docx_bytes(['第一幕：罗恩', '场景：旧宅 & 挂钟', '线索：Kaldt'])
    source_type, text = extract_text('雪盲.docx', data)
    assert source_type == 'docx'
    assert text.split('\n') == ['第一幕：罗恩', '场景：旧宅 & 挂钟', '线索：Kaldt']


def test_extract_docx_bad_zip_raises():
    with pytest.raises(ValueError, match='DOCX'):
        extract_text('坏.docx', b'not a zip at all')


def test_extract_docx_missing_document_xml_raises():
    with pytest.raises(ValueError, match='document.xml'):
        extract_text('空壳.docx', _docx_bytes([], with_document=False))


# ---------- PDF ----------

def test_extract_pdf_real_parse():
    """真实走一遍 pypdf：手工最小 PDF 能被解析并取出文本层。"""
    _, text = extract_text('八月二十二日.pdf', _pdf_bytes('Hello Module'))
    assert 'Hello Module' in text


def test_extract_pdf_corrupt_raises():
    with pytest.raises(ValueError, match='PDF'):
        extract_text('坏.pdf', b'%PDF-1.4 broken payload')


def test_extract_pdf_without_text_layer_raises():
    """扫描件（无文本层）要给出可读原因，而不是静默落一个空模组。"""
    with pytest.raises(ValueError, match='未从文件中提取到任何文本'):
        extract_text('扫描件.pdf', _pdf_bytes(''))


# ---------- 体积与截断 ----------

def test_oversize_file_rejected():
    with pytest.raises(ValueError, match='过大'):
        extract_text('巨.txt', b'x' * (MAX_UPLOAD_BYTES + 1))


def test_raw_text_truncated_to_max_chars(monkeypatch):
    monkeypatch.setattr(parser, 'MAX_RAW_CHARS', 50)
    _, text = extract_text('长.txt', ('字' * 200).encode('utf-8'))
    assert len(text) == 50
