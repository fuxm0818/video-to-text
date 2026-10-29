"""A tiny, dependency-free .docx writer.

Only the parts Word/WPS need are emitted: one document part, a styles part and
package metadata. Keeping this in stdlib avoids shipping python-docx (and its
lxml wheel) in the desktop bundle.
"""
from __future__ import annotations

import datetime as _dt
import io
import re
import zipfile
from pathlib import Path

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _esc(text: str) -> str:
    text = _ILLEGAL_XML.sub("", text or "")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace('"', "&quot;").replace("\n", " ").replace("\r", " ")


def _paragraph(style: str, text: str) -> str:
    return (
        "<w:p>"
        f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
        f'<w:r><w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'
        "</w:p>"
    )


def _styles_xml() -> str:
    def para_style(style_id: str, name: str, size: int, bold: bool = False,
                   color: str = "1F1B16", before: int = 0, after: int = 120,
                   line: int = 320, justify: bool = False, base: str = "Normal") -> str:
        return f"""
<w:style w:type="paragraph" w:styleId="{style_id}">
  <w:name w:val="{name}"/><w:basedOn w:val="{base}"/><w:qFormat/>
  <w:pPr>
    <w:spacing w:before="{before}" w:after="{after}" w:line="{line}" w:lineRule="auto"/>
    {'<w:jc w:val="both"/>' if justify else ''}
  </w:pPr>
  <w:rPr>
    <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei" w:cs="Calibri"/>
    {'<w:b/>' if bold else ''}
    <w:color w:val="{color}"/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/>
  </w:rPr>
</w:style>"""

    styles = [
        para_style("Title", "Title", 40, bold=True, before=0, after=240, line=300),
        para_style("Meta", "Meta", 18, color="6B6259", after=60, line=260),
        para_style("Heading2", "heading 2", 28, bold=True, before=320, after=140, line=300),
        para_style("BodyText", "Body Text", 22, after=160, line=340, justify=True),
        para_style("Timestamp", "Timestamp", 20, color="4A453F", after=80, line=300),
    ]
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W_NS}">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei" w:cs="Calibri"/>
        <w:sz w:val="22"/><w:szCs w:val="22"/>
        <w:lang w:val="en-US" w:eastAsia="zh-CN"/>
      </w:rPr>
    </w:rPrDefault>
    <w:pPrDefault>
      <w:pPr><w:spacing w:after="120" w:line="320" w:lineRule="auto"/></w:pPr>
    </w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/><w:qFormat/>
    <w:pPr><w:spacing w:after="120" w:line="320" w:lineRule="auto"/></w:pPr>
    <w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei" w:cs="Calibri"/>
      <w:sz w:val="22"/><w:szCs w:val="22"/>
    </w:rPr>
  </w:style>
  {''.join(styles)}
</w:styles>"""


def build_docx(blocks: list[tuple[str, str]], title: str) -> bytes:
    """blocks: (kind, text), kind in title/meta/h2/body/timestamp."""
    style_for = {
        "title": "Title",
        "meta": "Meta",
        "h2": "Heading2",
        "body": "BodyText",
        "timestamp": "Timestamp",
    }
    body: list[str] = []
    for kind, text in blocks:
        style = style_for.get(kind, "BodyText")
        body.append(_paragraph(style, text))
    body.append(
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}"><w:body>'
        + "".join(body)
        + "</w:body></w:document>"
    )

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_esc(title)}</dc:title>"
        "<dc:creator>Video to Text</dc:creator>"
        "<cp:lastModifiedBy>Video to Text</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Video to Text</Application>"
        "<AppVersion>0.1</AppVersion>"
        "</Properties>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{_PKG_NS}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/styles.xml", _styles_xml())
        zf.writestr("docProps/core.xml", core)
        zf.writestr("docProps/app.xml", app)
    return buf.getvalue()


def write_docx(path: Path, blocks: list[tuple[str, str]], title: str) -> None:
    path.write_bytes(build_docx(blocks, title))
