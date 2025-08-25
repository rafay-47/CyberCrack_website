import re
from pathlib import Path


def _read_text_from_file(path: str) -> tuple:
    """Read a file and return a tuple (text, links).

    links contains any URLs discovered in file metadata/annotations (useful for PDFs and DOCX hyperlinks).
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext in ('.txt', '.md'):
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(), []
    if ext == '.pdf':
        try:
            import fitz  # PyMuPDF
        except Exception:
            raise RuntimeError('PDF parsing requires PyMuPDF. Install PyMuPDF (pip install PyMuPDF) to enable PDF parsing.')
        doc = fitz.open(path)
        pages = []
        links = []
        try:
            for page in doc:
                # extract text
                pages.append(page.get_text("text") or '')
                # extract links/URIs from the page (annotations / link objects)
                for l in page.get_links():
                    uri = l.get('uri') or l.get('exturi') or l.get('target')
                    if uri:
                        links.append(uri)
        finally:
            doc.close()
        return '\n'.join(pages), links
    if ext == '.docx':
        try:
            import docx
        except Exception:
            raise RuntimeError('DOCX parsing requires python-docx. Install python-docx to enable DOCX parsing.')
        doc = docx.Document(path)
        text = '\n'.join(p.text for p in doc.paragraphs)
        links = []
        # try to extract hyperlink targets from document relationships
        try:
            rels = doc.part.rels
            for rel in rels:
                rel_obj = rels[rel]
                # relationship type for hyperlinks contains 'hyperlink'
                if rel_obj.reltype and 'hyperlink' in rel_obj.reltype:
                    target = getattr(rel_obj, 'target_ref', None) or getattr(rel_obj, 'target', None)
                    if target:
                        links.append(target)
        except Exception:
            # best-effort: if extraction fails, ignore and continue with text-only
            pass
        return text, links
    raise RuntimeError('Unsupported file type for resume parsing. Use .txt, .pdf, or .docx')


def parse_resume(path: str) -> dict:
    """Parse a resume file and return structured fields.

    Returns a dict with keys: name, email, phone, headline, location, summary, skills,
    work_experience (list), education (list), projects (list), certifications (list), languages (list), links (list)
    """
    text, file_links = _read_text_from_file(path)
    print("Links found in file metadata:", file_links)
    # Normalize and de-duplicate blank lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    full_text = '\n'.join(lines)

    # Email
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}', full_text)
    email = None
    if emails:
        for e in emails:
            if not re.search(r'(resume|noreply|no-reply|example|admin|contact)@', e, re.IGNORECASE):
                email = e
                break
        if not email:
            email = emails[0]

    # Phone
    phone_match = re.search(r'(\+?\d[\d \-\(\)]{7,}\d)', full_text)
    phone = phone_match.group(0) if phone_match else None

    # Name heuristic: first non-contact short line
    name = None
    for ln in lines[:8]:
        if '@' in ln or re.search(r'\d', ln):
            continue
        if 2 <= len(ln.split()) <= 5 and len(ln) < 80:
            name = ln
            break

    # Headline: line after name (if present and reasonable)
    headline = None
    if name:
        try:
            idx = lines.index(name)
            if idx + 1 < len(lines):
                cand = lines[idx + 1]
                if '@' not in cand and len(cand) < 140:
                    headline = cand
        except ValueError:
            pass

    # Summary: look for explicit headings or long paragraph near top
    summary = None
    for i, ln in enumerate(lines[:40]):
        if re.search(r'^(professional summary|professional profile|summary|profile)[:\- ]*$', ln, re.IGNORECASE):
            snippet = ' '.join(lines[i + 1:i + 6])
            if len(snippet) > 30:
                summary = snippet
                break
    if not summary:
        # choose the first reasonably long line near the top
        for ln in lines[1:16]:
            if 80 <= len(ln) <= 1000:
                summary = ln
                break

    # Improved summary heuristic: take first paragraph after contact block if still missing
    if not summary:
        contact_idx = -1
        for i, ln in enumerate(lines[:12]):
            if (email and email in ln) or (phone and phone in ln) or re.search(r'contact', ln, re.IGNORECASE):
                contact_idx = i
        start = contact_idx + 1 if contact_idx >= 0 else 0
        paras = []
        cur = []
        for ln in lines[start:start + 12]:
            if re.search(r'^(experience|work|education|skills|projects|certifications|languages|summary|profile|about|contact)[:\-]?', ln, re.IGNORECASE):
                break
            if ln.strip() == '':
                if cur:
                    paras.append(' '.join(cur)); cur = []
            else:
                cur.append(ln)
        if cur:
            paras.append(' '.join(cur))
        if paras:
            # pick the first paragraph that looks like a summary (length & contains verbs)
            for p in paras[:3]:
                if len(p) >= 50:
                    summary = p
                    break

    # Location: look for explicit label or "based in"
    location = None
    for ln in lines[:40]:
        if re.search(r'location[:\-]', ln, re.IGNORECASE):
            location = ln.split(':', 1)[-1].strip()
            break
        m = re.search(r'based in ([A-Za-z0-9 ,\-]+)', ln, re.IGNORECASE)
        if m:
            location = m.group(1).strip()
            break

    # Skills: detect a skills section or a short comma-separated line
    skills = []
    for i, ln in enumerate(lines):
        if re.search(r'^(?:technical\s+)?skills?[:\-]?', ln, re.IGNORECASE):
            block = []
            for j in range(i + 1, min(len(lines), i + 16)):
                nxt = lines[j]
                if re.search(r'^(experience|work|education|projects|certifications|languages|summary|profile|contact|about)[:\-]?', nxt, re.IGNORECASE):
                    break
                block.append(nxt)
            parts = re.split(r'[\,;•\n]+', '\n'.join(block))
            for p in parts:
                p = p.strip()
                if p:
                    skills.extend([s.strip() for s in re.split(r'[\/\\|]+', p) if s.strip()])
            break

    if not skills:
        for ln in lines[:40]:
            if ',' in ln and 3 <= len(ln.split(',')) <= 60 and len(ln) < 300:
                skills = [s.strip() for s in ln.split(',') if s.strip()]
                break

    # Helpers for sections and splitting
    def find_section(keywords):
        idx = None
        for i, ln in enumerate(lines):
            for kw in keywords:
                if re.search(rf'^{kw}[:\s]*$', ln, re.IGNORECASE) or re.search(rf'^{kw}[:\-\s]', ln, re.IGNORECASE):
                    idx = i
                    break
            if idx is not None:
                break
        if idx is None:
            return []
        block = []
        for j in range(idx + 1, len(lines)):
            nxt = lines[j]
            if re.search(r'^(experience|work|education|projects|certifications|languages|skills|summary|profile|contact|about)[:\-]?', nxt, re.IGNORECASE):
                break
            block.append(nxt)
        return block

    def split_items(block_lines):
        items = []
        cur = []
        for ln in block_lines:
            if re.match(r'^[\-\u2022•\*]\s+', ln) or re.match(r'^\d+\.', ln):
                if cur:
                    items.append(cur)
                    cur = []
                items.append([re.sub(r'^[\-\u2022•\*]\s+', '', ln)])
            elif ln.strip() == '':
                if cur:
                    items.append(cur)
                    cur = []
            else:
                cur.append(ln)
        if cur:
            items.append(cur)
        return items

    def extract_date_range(text):
        dr = {'start': None, 'end': None}
        m = re.search(r'(?P<start>(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\.,-]*\d{4})\s*[\-–—]\s*(?P<end>Present|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[\s\.,-]*\d{4}|Present)', text, re.IGNORECASE)
        if m:
            dr['start'] = m.group('start')
            dr['end'] = m.group('end')
            return dr
        m2 = re.search(r'(?P<start>\b(?:19|20)\d{2})\s*[\-–—]\s*(?P<end>Present|(?:19|20)\d{2})', text)
        if m2:
            dr['start'] = m2.group('start')
            dr['end'] = m2.group('end')
            return dr
        years = re.findall(r'\b(?:19|20)\d{2}\b', text)
        if len(years) >= 2:
            dr['start'] = years[0]
            dr['end'] = years[1]
        elif len(years) == 1:
            dr['start'] = years[0]
        return dr

    # Work experience
    work_block = find_section(['work experience', 'experience', 'employment'])
    work_items = []
    if work_block:
        items = split_items(work_block)
        for item in items:
            p = '\n'.join(item).strip()
            if not p:
                continue
            lines_p = [l.strip() for l in p.splitlines() if l.strip()]
            first = lines_p[0]
            title = None
            company = None
            # common patterns: "Title at Company" or "Title, Company" or "Title - Company"
            if ' at ' in first.lower():
                parts = re.split(r'\s+at\s+', first, flags=re.I)
                if len(parts) >= 2:
                    title = parts[0].strip()
                    company = parts[1].strip()
            elif ',' in first:
                parts = [x.strip() for x in first.split(',')]
                if len(parts) >= 2:
                    title = parts[0]
                    company = parts[1]
            elif ' - ' in first or ' — ' in first:
                parts = re.split(r'\s[-—]\s', first)
                if len(parts) >= 2:
                    title = parts[0]
                    company = parts[1]
            dr = extract_date_range(p)
            start = dr.get('start')
            end = dr.get('end')
            desc = '\n'.join(lines_p[1:]) if len(lines_p) > 1 else None
            work_items.append({'title': title, 'company': company, 'start': start, 'end': end, 'description': desc})

    # Education
    edu_block = find_section(['education', 'qualifications', 'academic'])
    edu_items = []
    if edu_block:
        items = split_items(edu_block)
        for item in items:
            p = '\n'.join(item).strip()
            if not p:
                continue
            lines_p = [l.strip() for l in p.splitlines() if l.strip()]
            first = lines_p[0]
            school = None
            degree = None
            if ',' in first:
                parts = [x.strip() for x in first.split(',')]
                school = parts[0]
                if len(parts) > 1:
                    degree = parts[1]
            else:
                school = first
            dr = extract_date_range(p)
            start = dr.get('start')
            end = dr.get('end')
            desc = '\n'.join(lines_p[1:]) if len(lines_p) > 1 else None
            edu_items.append({'school': school, 'degree': degree, 'start': start, 'end': end, 'description': desc})

    def is_project_title_line(s):
        s = s.strip()
        if not s:
            return False
        if len(s) > 140:
            return False
        if s.endswith('.'):
            return False
        if len(s.split()) <= 10 and len(re.findall(r'\b(is|was|managed|developed|designed|created|worked|led|built|implemented)\b', s, re.IGNORECASE)) == 0:
            if re.match(r'^[A-Z0-9][A-Za-z0-9 _\-:,()]{0,140}$', s) or re.search(r'project', s, re.IGNORECASE):
                return True
        return False

    # Projects: improved splitting to avoid concatenation
    proj_block = find_section(['projects', 'selected projects', 'personal projects'])
    project_items = []
    if proj_block:
        # First try to split on clear bullets/numbering
        items = split_items(proj_block)
        if len(items) <= 1:
            # fallback: split on blank lines or lines that look like a title (short, capitalized)
            temp = []
            cur = []

            for ln in proj_block:
                if ln.strip() == '' and cur:
                    temp.append(cur); cur = []
                elif is_project_title_line(ln) and cur:
                    # start a new project if we already have content
                    temp.append(cur); cur = [ln]
                else:
                    cur.append(ln)
            if cur:
                temp.append(cur)
            items = temp

        for item in items:
            block = '\n'.join(item).strip()
            if not block:
                continue
            lines_p = [l.strip() for l in block.splitlines() if l.strip()]
            # if the first line looks like a project title, use it as title
            title = None
            desc = None
            if lines_p:
                if is_project_title_line(lines_p[0]):
                    title = lines_p[0]
                    desc = '\n'.join(lines_p[1:]) if len(lines_p) > 1 else None
                else:
                    # sometimes title and description are on same line separated by ' - ' or ':'
                    first = lines_p[0]
                    if ' - ' in first or ' — ' in first or ':' in first:
                        parts = re.split(r'\s[-—]\s|:\s*', first, maxsplit=1)
                        title = parts[0].strip()
                        desc = '\n'.join(parts[1:]).strip() if len(parts) > 1 else '\n'.join(lines_p[1:]) if len(lines_p) > 1 else None
                    else:
                        title = first
                        desc = '\n'.join(lines_p[1:]) if len(lines_p) > 1 else None
            urlm = re.search(r'(https?:\/\/[^\s,;]+)', block)
            link = urlm.group(1) if urlm else None
            project_items.append({'title': title, 'link': link, 'description': desc})

    # Certifications
    cert_block = find_section(['certifications', 'licenses', 'certificates'])
    certs = []
    if cert_block:
        parts = []
        for ln in cert_block:
            if re.match(r'^[\-\u2022•\*]\s+', ln):
                parts.append(re.sub(r'^[\-\u2022•\*]\s+', '', ln))
            else:
                parts.extend(re.split(r'[;,]', ln))
        certs = [p.strip() for p in parts if p.strip() and not re.match(r'^(certifications?|licenses?)', p.strip(), re.I)]

    # Languages
    lang_block = find_section(['languages', 'language'])
    langs = []
    if lang_block:
        parts = re.split(r'[\n,;]+', '\n'.join(lang_block))
        langs = [p.strip() for p in parts if p.strip()]

    # Links -- any http(s)
    # Links: any http(s) in text plus any links extracted from the file (PDF annotations, DOCX rels)
    links = re.findall(r'(https?:\/\/[^\s,;]+)', full_text)
    # include file extracted links (deduplicate while preserving order)
    file_links = file_links or []
    for fl in file_links:
        if fl and fl not in links:
            links.append(fl)

    return {
        'name': name,
        'email': email,
        'phone': phone,
        'headline': headline,
        'location': location,
        'summary': summary,
        'skills': skills,
        'work_experience': work_items,
        'education': edu_items,
        'projects': project_items,
        'certifications': certs,
        'languages': langs,
        'links': links,
    }
