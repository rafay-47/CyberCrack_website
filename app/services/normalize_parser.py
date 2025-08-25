import json
import re

def normalize(parsed_raw):
        """Normalize various parser outputs into a stable dict shape for the UI."""
        def safe_json_parse(text_data):
            """Safely parse JSON from various text formats with multiple fallback strategies."""
            if not isinstance(text_data, str) or not text_data.strip():
                return None
            
            text_data = text_data.strip()
            
            # Strategy 1: Direct JSON parsing
            try:
                return json.loads(text_data)
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Strategy 2: Extract from code blocks
            patterns = [
                r'```(?:json)?\s*([\s\S]*?)\s*```',  # ```json ... ``` or ``` ... ```
                r'<json>([\s\S]*?)</json>',          # <json> ... </json>
                r'JSON:\s*([\s\S]*?)(?:\n\n|\Z)',    # JSON: ... (until double newline or end)
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text_data, re.IGNORECASE | re.DOTALL)
                if match:
                    candidate = match.group(1).strip()
                    try:
                        return json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            # Strategy 3: Find JSON object boundaries
            brace_count = 0
            start_idx = -1
            
            for i, char in enumerate(text_data):
                if char == '{':
                    if start_idx == -1:
                        start_idx = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_idx != -1:
                        candidate = text_data[start_idx:i+1]
                        try:
                            return json.loads(candidate)
                        except (json.JSONDecodeError, ValueError):
                            start_idx = -1
                            continue
            
            # Strategy 4: Fix common JSON issues and retry
            try:
                # Replace single quotes with double quotes (carefully)
                fixed_text = re.sub(r"'([^']*)':", r'"\1":', text_data)  # Fix keys
                fixed_text = re.sub(r":\s*'([^']*)'", r': "\1"', fixed_text)  # Fix values
                return json.loads(fixed_text)
            except (json.JSONDecodeError, ValueError):
                pass
            
            return None

        # Handle different input types
        if isinstance(parsed_raw, str):
            parsed = safe_json_parse(parsed_raw)
            if not parsed:
                return {'raw': parsed_raw}
        elif isinstance(parsed_raw, dict):
            # Check if it's a wrapper dict containing JSON strings
            parsed = parsed_raw.copy()
            json_candidates = ['raw', 'text', 'result', 'content', 'data', 'response']
            
            for key in json_candidates:
                if key in parsed and isinstance(parsed[key], str):
                    extracted = safe_json_parse(parsed[key])
                    if extracted and isinstance(extracted, dict):
                        parsed = extracted
                        break
        else:
            # Unknown type, wrap and return
            return {'raw': str(parsed_raw) if parsed_raw is not None else ''}

        # Ensure parsed is a dictionary
        if not isinstance(parsed, dict):
            return {'raw': str(parsed)}

        def safe_get_string(keys):
            """Safely get a string value from multiple possible keys."""
            for key in keys:
                value = parsed.get(key)
                if value and isinstance(value, (str, int, float)):
                    result = str(value).strip()
                    if result:
                        return result
            return None

        def safe_get_list_of_strings(keys, default=None):
            """Safely get and normalize a list of strings from multiple possible keys."""
            if default is None:
                default = []
                
            for key in keys:
                value = parsed.get(key)
                if not value:
                    continue
                    
                if isinstance(value, list):
                    # Filter out empty and non-string items
                    result = []
                    for item in value:
                        if item and isinstance(item, (str, int, float)):
                            str_item = str(item).strip()
                            if str_item:
                                result.append(str_item)
                    if result:
                        return result
                elif isinstance(value, str) and value.strip():
                    # Split by common separators
                    parts = [s.strip() for s in re.split(r'[,\n;|•·]+', value) if s.strip()]
                    if parts:
                        return parts
                        
            return default

        # Normalize top-level simple fields with better validation
        out = {}
        out['name'] = safe_get_string(['name', 'full_name', 'fullName', 'full name'])
        out['email'] = safe_get_string(['email', 'email_address', 'emailAddress', 'email address'])
        out['phone'] = safe_get_string(['phone', 'telephone', 'phone_number', 'phoneNumber', 'phone number', 'mobile'])
        out['headline'] = safe_get_string(['headline', 'title', 'current_title', 'currentTitle', 'job_title', 'position'])
        out['location'] = safe_get_string(['location', 'city', 'location_city', 'address', 'place'])
        out['summary'] = safe_get_string(['summary', 'professional_summary', 'professionalSummary', 'about', 'bio', 'profile'])

        # Normalize skills with better parsing
        out['skills'] = safe_get_list_of_strings(['skills', 'skill', 'technical_skills', 'technicalSkills'])

        def _map_item(item, mapping):
            """Safely map item fields to standardized keys with null checks."""
            if not isinstance(item, dict):
                return {'raw': str(item) if item is not None else ''}
            
            out_item = {}
            for target, candidates in mapping.items():
                val = None
                
                # Try each candidate key
                for candidate in candidates:
                    if candidate in item:
                        raw_val = item[candidate]
                        if raw_val is not None and str(raw_val).strip():
                            val = str(raw_val).strip()
                        break
                
                # Try camelCase variants if not found
                if val is None:
                    for candidate in candidates:
                        if '_' in candidate:
                            camel_case = ''.join([candidate.split('_')[0]] + 
                                               [p.capitalize() for p in candidate.split('_')[1:]])
                            if camel_case in item:
                                raw_val = item[camel_case]
                                if raw_val is not None and str(raw_val).strip():
                                    val = str(raw_val).strip()
                            break
                
                out_item[target] = val
            return out_item

        def extract_date_range(text):
            """Extract start and end dates from text with improved patterns."""
            if not text or not isinstance(text, str):
                return (None, None)
            
            text = text.strip()
            if not text:
                return (None, None)
            
            # Pattern 1: Month Year - Month Year or Present
            month_year_pattern = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}'
            range_match = re.search(rf'({month_year_pattern})\s*(?:[-–—]|to|until)\s*({month_year_pattern}|Present|present|current)', text, re.IGNORECASE)
            if range_match:
                return (range_match.group(1).strip(), range_match.group(2).strip())
            
            # Pattern 2: Year - Year or Present
            year_range_match = re.search(r'(\d{4})\s*(?:[-–—]|to|until)\s*(\d{4}|Present|present|current)', text, re.IGNORECASE)
            if year_range_match:
                return (year_range_match.group(1).strip(), year_range_match.group(2).strip())
            
            # Pattern 3: Simple separators
            separator_parts = re.split(r'\s*(?:[-–—]|to|until)\s*', text, maxsplit=1, flags=re.IGNORECASE)
            if len(separator_parts) == 2:
                start = separator_parts[0].strip()
                end = separator_parts[1].strip()
                if start and end:
                    return (start, end)
            
            # Pattern 4: Single date (current position)
            single_date = re.search(rf'({month_year_pattern}|\d{{4}})', text)
            if single_date:
                return (single_date.group(1).strip(), None)
            
            return (None, None)

        # search free text for date-range or single date tokens (years or Month Year)
        def find_dates_in_text(s: str):
            if not s or not isinstance(s, str):
                return (None, None)
            # try Month Year - Month Year
            month_year = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}'
            patterns = [
                rf'({month_year})\s*(?:[-–—]|to|until)\s*({month_year}|Present|present)',
                r'(\d{4})\s*(?:[-–—]|to|until)\s*(\d{4}|Present|present)',
                rf'({month_year})',
                r'(\d{4})'
            ]
            for pat in patterns:
                m = re.search(pat, s)
                if m:
                    if m.lastindex >= 2 and m.group(2):
                        return (m.group(1).strip(), m.group(2).strip())
                    return (m.group(1).strip(), None)
            return (None, None)

        def _normalize_list(key, mapping, default_title_key='title'):
            """Normalize a list of items (dicts or strings) into standardized format."""
            vals = parsed.get(key)
            if not vals:
                return []
            
            result = []
            
            if isinstance(vals, list):
                for v in vals:
                    if not v:  # Skip None or empty values
                        continue
                        
                    if isinstance(v, dict):
                        mapped = _map_item(v, mapping)
                        if any(mapped.values()):  # Only add if it has some content
                            result.append(mapped)
                    elif isinstance(v, str):
                        v = v.strip()
                        if v:
                            # Try to split by common separators
                            parts = re.split(r'\s*[-—:]\s*|:\s*', v, maxsplit=1)
                            title = parts[0].strip() if parts[0] else None
                            desc = parts[1].strip() if len(parts) > 1 and parts[1] else None
                            
                            item = {default_title_key: title}
                            if desc:
                                item['description'] = desc
                            if title:  # Only add if we have at least a title
                                result.append(item)
                    else:
                        # Convert other types to string
                        str_val = str(v).strip()
                        if str_val:
                            result.append({default_title_key: str_val})
                            
            elif isinstance(vals, str) and vals.strip():
                # Handle newline or other separator-delimited lists
                lines = [l.strip() for l in re.split(r'\n+|;;', vals) if l.strip()]
                for line in lines:
                    parts = re.split(r'\s*[-—:]\s*|:\s*', line, maxsplit=1)
                    title = parts[0].strip() if parts[0] else None
                    desc = parts[1].strip() if len(parts) > 1 and parts[1] else None
                    
                    if title:
                        item = {default_title_key: title}
                        if desc:
                            item['description'] = desc
                        result.append(item)
                        
            return result

        # mappings for different sections
        work_map = {
            'title': ['title', 'position', 'role', 'name'],
            'company': ['company', 'employer', 'organization', 'org'],
            'start': ['start', 'start_date', 'from'],
            'end': ['end', 'end_date', 'to'],
            'description': ['description', 'summary', 'responsibilities', 'details']
        }

        edu_map = {
            'school': ['school', 'institution', 'university', 'college', 'organization'],
            'degree': ['degree', 'program', 'qualification'],
            'start': ['start', 'start_date', 'from'],
            'end': ['end', 'end_date', 'to'],
            'description': ['description', 'details', 'notes']
        }

        project_map = {
            'title': ['title', 'name'],
            'link': ['link', 'url'],
            'description': ['description', 'summary', 'details']
        }

        # Process work experience with enhanced date extraction
        work_items = _normalize_list('work_experience', work_map, default_title_key='title')
        processed_work = []
        
        for item in work_items:
            if not isinstance(item, dict):
                continue
                
            # Get the original item from parsed data for additional context
            orig_item = {}
            if isinstance(parsed.get('work_experience'), list):
                idx = len(processed_work)
                if idx < len(parsed['work_experience']):
                    orig_item = parsed['work_experience'][idx] if isinstance(parsed['work_experience'][idx], dict) else {}
            
            # Extract dates from multiple sources
            if not item.get('start') or not item.get('end'):
                # Try date-specific fields first
                date_fields = ['date', 'date_range', 'period', 'dates', 'duration', 'employment_period']
                for field in date_fields:
                    date_text = orig_item.get(field) or item.get(field)
                    if date_text and isinstance(date_text, str):
                        start, end = extract_date_range(date_text)
                        if start and not item.get('start'):
                            item['start'] = start
                        if end and not item.get('end'):
                            item['end'] = end
                        if start or end:
                            break
                
                # Try extracting from description if still missing
                if (not item.get('start') or not item.get('end')) and item.get('description'):
                    start, end = extract_date_range(item['description'])
                    if start and not item.get('start'):
                        item['start'] = start
                    if end and not item.get('end'):
                        item['end'] = end
            
            # Ensure description is properly formatted
            if item.get('description'):
                desc = item['description']
                if isinstance(desc, list):
                    item['description'] = '\n'.join(str(d) for d in desc if d)
                elif not isinstance(desc, str):
                    item['description'] = str(desc)
            
            processed_work.append(item)
        
        out['work_experience'] = processed_work

        # Process education with date extraction
        education_items = _normalize_list('education', edu_map, default_title_key='school')
        processed_education = []
        
        for item in education_items:
            if not isinstance(item, dict):
                continue
                
            # Extract dates if missing
            if not item.get('start') or not item.get('end'):
                date_fields = ['date', 'date_range', 'period', 'dates', 'graduation_date', 'year']
                for field in date_fields:
                    date_text = item.get(field)
                    if date_text and isinstance(date_text, str):
                        start, end = extract_date_range(date_text)
                        if start and not item.get('start'):
                            item['start'] = start
                        if end and not item.get('end'):
                            item['end'] = end
                        break
            
            # Ensure description is properly formatted
            if item.get('description'):
                desc = item['description']
                if isinstance(desc, list):
                    item['description'] = '\n'.join(str(d) for d in desc if d)
                elif not isinstance(desc, str):
                    item['description'] = str(desc)
                    
            processed_education.append(item)
        
        out['education'] = processed_education

        # Process projects with enhanced description handling
        project_items = _normalize_list('projects', project_map, default_title_key='title')
        processed_projects = []
        
        for item in project_items:
            if not isinstance(item, dict):
                continue
                
            # Enhanced description extraction from multiple sources
            if not item.get('description'):
                desc_candidates = ['desc', 'summary', 'details', 'about', 'overview', 'bullets', 'achievements', 'points']
                for field in desc_candidates:
                    value = item.get(field)
                    if value:
                        if isinstance(value, list):
                            item['description'] = '\n'.join(str(x) for x in value if x)
                        elif isinstance(value, str) and value.strip():
                            item['description'] = value.strip()
                        break
            
            # Ensure description is properly formatted
            if item.get('description'):
                desc = item['description']
                if isinstance(desc, list):
                    item['description'] = '\n'.join(str(d) for d in desc if d)
                elif not isinstance(desc, str):
                    item['description'] = str(desc)
                    
            processed_projects.append(item)
        
        out['projects'] = processed_projects

        # Process simple lists (certifications, languages, links)
        simple_list_keys = {
            'certifications': ['certifications', 'certificates', 'certs'],
            'languages': ['languages', 'language'],
            'links': ['links', 'urls', 'websites', 'portfolio'],
            # Preserve AI/external parser keyword lists when present
            'extracted_keywords': ['extracted_keywords', 'keywords', 'extractedKeywords', 'extracted_keywords_list']
        }
        
        for output_key, input_keys in simple_list_keys.items():
            out[output_key] = safe_get_list_of_strings(input_keys)

        return out