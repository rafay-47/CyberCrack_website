"""AI resume parser service using a configurable GROQ-compatible HTTP API.

This module provides a parse_text(text) function that will:
- If GROQ_API_URL and GROQ_API_KEY are configured in the environment, POST the resume text to that endpoint and return its JSON response (expected to be parsed resume JSON).
- If the API is not configured or the request fails, fall back to the local heuristic parser in app.services.resume_parser.parse_resume_text_fallback.

Notes:
- Do not hardcode any API shape; this wrapper expects the remote API to accept JSON {"text": "..."} and to return JSON. Adjust request payload/headers if your provider requires a different shape.
- Configure these environment variables: GROQ_API_URL (full URL), GROQ_API_KEY (Bearer token or API key). Optionally set GROQ_TIMEOUT_SECONDS.
"""

import os
import json
import logging
from typing import Any, Dict

import requests

from pathlib import Path

# Try to use the internal GroqProvider if present
GroqProvider = None
try:
    from app.agents.groq_provider import GroqProvider
except Exception:
    GroqProvider = None

# Local fallback parser (heuristic) reused
try:
    from app.services.resume_parser import parse_resume as local_parse_resume
except Exception:
    local_parse_resume = None

LOGGER = logging.getLogger(__name__)


def _safe_json_parse(text_data):
    """Safely parse JSON from various text formats with multiple fallback strategies."""
    if not isinstance(text_data, str) or not text_data.strip():
        return {'raw': text_data if text_data else ''}
    
    text_data = text_data.strip()
    
    # Strategy 1: Direct JSON parsing
    try:
        return json.loads(text_data)
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Strategy 2: Extract from code blocks
    import re
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
    
    return {'raw': text_data}


# Support two config modes:
# 1) Use internal GroqProvider (recommended): set GROQ_API_KEY env var
# 2) Use external HTTP endpoint: set GROQ_API_URL and optionally GROQ_API_KEY
GROQ_API_URL = os.environ.get('GROQ_API_URL')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
GROQ_TIMEOUT = float(os.environ.get('GROQ_TIMEOUT_SECONDS', '15'))


def parse_text_via_groq_http(text: str) -> Dict[str, Any]:
    if not GROQ_API_URL:
        raise RuntimeError('GROQ_API_URL not configured')

    headers = {
        'Content-Type': 'application/json'
    }
    if GROQ_API_KEY:
        if GROQ_API_KEY.lower().startswith('bearer '):
            headers['Authorization'] = GROQ_API_KEY
        else:
            headers['Authorization'] = f'Bearer {GROQ_API_KEY}'

    payload = {'text': text}
    resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=GROQ_TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return {'raw': resp.text}


def parse_text(text: str) -> Dict[str, Any]:
    """Parse resume text using AI providers with robust error handling and fallbacks."""
    if not text or not isinstance(text, str):
        return {'raw': str(text) if text else ''}
    
    text = text.strip()
    if not text:
        return {'raw': ''}
    
    # Prefer internal GroqProvider if available and API key present
    if GroqProvider is not None and (GROQ_API_KEY or os.environ.get('GROQ_API_KEY')):
        try:
            provider = GroqProvider(api_key=GROQ_API_KEY)
            
            # Create a detailed prompt for better results
            prompt = f"""Parse this resume text into a JSON object with the following structure:
{{
  "name": "full name",
  "email": "email address", 
  "phone": "phone number",
  "headline": "job title or professional headline",
  "location": "city, state/country",
  "summary": "professional summary text",
  "skills": ["skill1", "skill2", "skill3"],
  "work_experience": [
    {{
      "title": "job title",
      "company": "company name", 
      "start": "start date",
      "end": "end date or Present",
      "description": "job responsibilities and achievements"
    }}
  ],
  "education": [
    {{
      "school": "school name",
      "degree": "degree name",
      "start": "start year", 
      "end": "end year",
      "description": "additional details"
    }}
  ],
  "projects": [
    {{
      "title": "project name",
      "link": "project url if available",
      "description": "project description"
    }}
  ],
  "certifications": ["cert1", "cert2"],
  "languages": ["language1", "language2"], 
  "links": ["url1", "url2"],
  "extracted_keywords": ["keyword1", "keyword2"]
}}

Resume text:
{text}

Return only valid JSON, no additional text or formatting."""

            # Handle async provider call safely
            result = provider(prompt)
            print(result)
            
            if hasattr(result, '__await__'):
                import asyncio
                try:
                    # Check if we're already in an event loop
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an event loop, create a new thread to run the coroutine
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, result)
                            raw = future.result(timeout=30)  # 30 second timeout
                    except RuntimeError:
                        # No event loop running, safe to use asyncio.run
                        raw = asyncio.run(result)
                except Exception as async_exc:
                    LOGGER.error(f'Async execution failed: {async_exc}')
                    raise
            else:
                raw = result
            
            # Parse the result
            if isinstance(raw, dict):
                return raw
            elif isinstance(raw, str):
                return _safe_json_parse(raw)
            else:
                return {'raw': str(raw)}
                
        except Exception as exc:
            LOGGER.warning(f'Internal GroqProvider failed: {exc}', exc_info=True)

    # Next prefer HTTP GROQ endpoint if set
    if GROQ_API_URL:
        try:
            return parse_text_via_groq_http(text)
        except Exception as exc:
            LOGGER.exception('GROQ HTTP API call failed, falling back to local parser: %s', exc)

    # Local fallback to heuristic parser
    if local_parse_resume is not None:
        try:
            from tempfile import NamedTemporaryFile
            import os
            
            # Create temporary file with proper cleanup
            with NamedTemporaryFile('w', encoding='utf-8', delete=False, suffix='.txt') as tmp:
                tmp.write(text)
                tmp_path = tmp.name
            
            try:
                parsed = local_parse_resume(tmp_path)
                LOGGER.info("Used local parser fallback")
                return parsed
            finally:
                # Ensure cleanup
                try:
                    os.unlink(tmp_path)
                except (OSError, FileNotFoundError):
                    pass
                    
        except Exception as local_exc:
            LOGGER.warning(f'Local parser fallback failed: {local_exc}', exc_info=True)

    # Final fallback - return raw text
    LOGGER.warning('All parsing methods failed, returning raw text')
    return {'raw': text}


if __name__ == '__main__':
    sample = 'John Doe\nSoftware Engineer\nSummary: Experienced software engineer...\nSkills: Python, Flask, SQL\nProjects:\n- Project A: built X\n- Project B: built Y\n'
    print(json.dumps(parse_text(sample), indent=2))
