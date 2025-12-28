# modules/doc_renderer.py
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pypdf import PdfReader
from io import BytesIO
import zipfile

def extract_text(files):
    parts = []; full = ""
    if not files: return [], ""
    for f in files:
        txt = ""
        try:
            if f.type == "application/pdf":
                reader = PdfReader(f)
                txt = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])
            elif "word" in f.type:
                doc = Document(f)
                txt = "\n".join([p.text for p in doc.paragraphs])
            else:
                txt = str(f.read(), "utf-8")
            parts.append(f"--- {f.name} ---\n{txt}")
            full += f"\nFILE: {f.name}\n{txt}"
        except: pass
    return parts, full

def parse_markdown_pro(doc, text):
    lines = str(text).split('\n')
    in_table = False; table_data = []
    
    for line in lines:
        stripped = line.strip()
        if "|" in stripped and stripped.startswith("|"):
            if not in_table: in_table=True; table_data=[]
            cells = [c.strip() for c in stripped.split('|')[1:-1]]
            if not all(set(c).issubset({'-', ':', ' '}) for c in cells if c): table_data.append(cells)
            continue
        if in_table:
            if table_data:
                rows = len(table_data); cols = max(len(r) for r in table_data) if rows>0 else 0
                if rows>0:
                    tbl = doc.add_table(rows, cols); tbl.style = 'Table Grid'
                    for i,r in enumerate(table_data):
                        for j,c in enumerate(r):
                            if j<cols: tbl.cell(i,j).text=c
            in_table=False; table_data=[]
        
        if not stripped: continue
        if stripped.startswith('#'):
            level = min(stripped.count('#'), 3)
            doc.add_heading(stripped.lstrip('#').strip(), level=level)
        elif stripped.startswith('- ') or stripped.startswith('* '):
            doc.add_paragraph(stripped[2:], style='List Bullet')
        else:
            p = doc.add_paragraph(stripped)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

def create_zip(docs_dict, sanitizer):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in docs_dict.items():
            doc = Document()
            doc.add_heading(data.get("titolo", name), 0)
            content = sanitizer.restore(data.get("contenuto", ""))
            parse_markdown_pro(doc, content)
            
            b = BytesIO()
            doc.save(b)
            z.writestr(f"{name}.docx", b.getvalue())
    return buf
