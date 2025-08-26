import spacy
from spacy.matcher import PhraseMatcher
from skillNer.general_params import SKILL_DB
from skillNer.skill_extractor_class import SkillExtractor
import pandas as pd
from collections import Counter, defaultdict, OrderedDict
import time
import re
import logging
import hashlib
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
import json
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ExtractedSkill:
    """Data class for extracted skills with validation"""
    name: str
    surface_form: str
    confidence: float
    skill_type: str
    source: str
    
    def __post_init__(self):
        """Validate skill data"""
        self.confidence = max(0.0, min(1.0, float(self.confidence)))  # Clamp between 0-1
        self.name = self.name.strip()
        self.surface_form = self.surface_form.strip()

@dataclass
class ExtractedEntity:
    """Data class for extracted entities with validation"""
    text: str
    label: str
    description: str
    confidence: float
    start: int
    end: int
    
    def __post_init__(self):
        """Validate entity data"""
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.text = self.text.strip()

@dataclass
class JobAnalysisResult:
    """Data class for job analysis results with metadata"""
    job_id: str
    skills: List[ExtractedSkill] = field(default_factory=list)
    entities: List[ExtractedEntity] = field(default_factory=list)
    keywords: List[Dict[str, Any]] = field(default_factory=list)
    requirements_sections: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0
    cache_hit: bool = False

class OptimizedJobAnalyzer:
    """High-performance, production-ready job posting analyzer"""
    
    def __init__(self, 
                 spacy_model: str = 'en_core_web_sm',
                 confidence_threshold: float = 0.35,
                 max_skills_per_job: int = 50,
                 fast_mode: bool = False,
                 cache_size: int = 512,
                 enable_threading: bool = False,
                 max_workers: int = 4):
        """
        Initialize the analyzer with advanced performance settings
        
        Args:
            spacy_model: spaCy model name
            confidence_threshold: Minimum confidence for skill extraction
            max_skills_per_job: Maximum skills to extract per job
            fast_mode: Enable fast processing (reduces accuracy slightly)
            cache_size: Maximum number of cached results
            enable_threading: Enable parallel processing for batch jobs
            max_workers: Number of worker threads for parallel processing
        """
        self.confidence_threshold = confidence_threshold
        self.max_skills_per_job = max_skills_per_job
        self.fast_mode = bool(fast_mode)
        self.cache_size = int(cache_size) if cache_size and cache_size > 0 else 512
        self.enable_threading = enable_threading
        self.max_workers = max_workers
        
        # Thread-safe cache with hash-based keys
        self._cache_lock = threading.RLock()
        self._result_cache = OrderedDict()
        self._cache_stats = {'hits': 0, 'misses': 0, 'evictions': 0}
        
        # Performance monitoring
        self._performance_stats = {
            'total_jobs': 0,
            'total_time': 0.0,
            'skillner_time': 0.0,
            'spacy_time': 0.0,
            'fallback_time': 0.0
        }
        
        # Load configurations
        self.skill_name_mapping = self._load_skill_mapping()
        self._init_skill_patterns()
        
        # Initialize models
        self.nlp = self._init_spacy(spacy_model, fast_mode=self.fast_mode)
        self.skill_extractor = None if self.fast_mode else self._init_skillner()
        
        # Precompile common regex patterns for better performance
        self._precompile_patterns()
        
        logger.info(f"✓ Analyzer initialized - Model: {spacy_model}, Fast: {self.fast_mode}, Cache: {self.cache_size}")

    def _init_spacy(self, model_name: str, fast_mode: bool = False):
        """Initialize spaCy with optimal configuration"""
        try:
            if fast_mode:
                # In fast mode, disable heavy components and use smaller model
                disabled_components = ['parser', 'textcat']
                try:
                    nlp = spacy.load('en_core_web_sm', disable=disabled_components)
                    logger.info("✓ Fast mode: Using en_core_web_sm with minimal components")
                except OSError:
                    nlp = spacy.load(model_name, disable=disabled_components)
                    logger.info(f"✓ Fast mode: Using {model_name} with disabled components")
            else:
                # Normal mode: use full model but optimize pipeline
                nlp = spacy.load(model_name)
                # Add custom extensions if needed
                if not spacy.tokens.Token.has_extension("is_tech_term"):
                    spacy.tokens.Token.set_extension("is_tech_term", default=False)
                logger.info(f"✓ Full mode: Using {model_name} with all components")
            
            return nlp
        except OSError as e:
            logger.error(f"Failed to load spaCy model {model_name}: {e}")
            # Emergency fallback
            try:
                nlp = spacy.load('en_core_web_sm')
                logger.warning("Emergency fallback to en_core_web_sm")
                return nlp
            except OSError:
                raise RuntimeError(
                    "No spaCy model available. Install with: "
                    "python -m spacy download en_core_web_sm"
                )

    def _init_skillner(self):
        """Initialize skillNER with error handling and retries"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                skill_extractor = SkillExtractor(
                    self.nlp, 
                    SKILL_DB, 
                    phraseMatcher=PhraseMatcher
                )
                logger.info("✓ skillNER initialized successfully")
                return skill_extractor
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"skillNER init attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(0.5)  # Brief delay before retry
                else:
                    logger.error(f"skillNER initialization failed after {max_retries} attempts: {e}")
                    return None

    def _load_skill_mapping(self) -> Dict[str, str]:
        """Load and cache skill ID mappings with error handling"""
        mapping = {}
        try:
            for skill_id, skill_data in SKILL_DB.items():
                if isinstance(skill_data, dict):
                    skill_name = (
                        skill_data.get('skill_name') or 
                        (skill_data.get('surface_forms', [''])[0] if skill_data.get('surface_forms') else '') or
                        skill_id
                    )
                    mapping[skill_id] = skill_name
                else:
                    mapping[skill_id] = str(skill_data)
            
            logger.info(f"✓ Loaded {len(mapping)} skill mappings")
            return mapping
        except Exception as e:
            logger.warning(f"Failed to load skill mapping: {e}")
            return {}

    def _init_skill_patterns(self):
        """Initialize comprehensive, curated skill patterns"""
        self.tech_skills_patterns = {
            'Programming Languages': [
                'python', 'java', 'javascript', 'typescript', 'c++', 'c#', 'go', 'rust',
                'kotlin', 'swift', 'ruby', 'php', 'scala', 'r', 'matlab', 'perl', 'dart',
                'objective-c', 'shell', 'bash', 'powershell', 'sql'
            ],
            'Web Technologies': [
                'html', 'css', 'html5', 'css3', 'sass', 'less', 'bootstrap', 'tailwind',
                'jquery', 'ajax', 'json', 'xml', 'rest api', 'graphql', 'websocket'
            ],
            'Frameworks & Libraries': [
                'react', 'angular', 'vue.js', 'django', 'flask', 'fastapi', 'spring boot',
                'express.js', 'node.js', 'next.js', 'nuxt.js', 'svelte', 'ember.js',
                'laravel', 'symfony', 'codeigniter', '.net', 'asp.net'
            ],
            'Databases': [
                'mysql', 'postgresql', 'mongodb', 'redis', 'elasticsearch', 'cassandra',
                'oracle', 'sql server', 'sqlite', 'neo4j', 'dynamodb', 'firebase',
                'mariadb', 'couchdb', 'influxdb'
            ],
            'Cloud & DevOps': [
                'aws', 'azure', 'google cloud platform', 'gcp', 'heroku', 'digitalocean',
                'kubernetes', 'docker', 'terraform', 'ansible', 'jenkins', 'gitlab ci',
                'github actions', 'circleci', 'travis ci'
            ],
            'Data Science & ML': [
                'pandas', 'numpy', 'scikit-learn', 'tensorflow', 'pytorch', 'keras',
                'matplotlib', 'seaborn', 'plotly', 'jupyter', 'apache spark', 'hadoop',
                'tableau', 'power bi', 'excel', 'r studio'
            ],
            'Mobile Development': [
                'android', 'ios', 'react native', 'flutter', 'xamarin', 'cordova',
                'ionic', 'swift', 'kotlin', 'objective-c'
            ],
            'Tools & Platforms': [
                'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence',
                'slack', 'teams', 'figma', 'sketch', 'adobe xd', 'photoshop'
            ]
        }

    def _precompile_patterns(self):
        """Precompile regex patterns for performance"""
        self._compiled_patterns = {}
        # Always compile patterns; in fast_mode we use simpler, faster patterns
        for category, skills in self.tech_skills_patterns.items():
            try:
                if self.fast_mode:
                    # Simple OR pattern with word boundaries (faster to compile and execute)
                    simple = r'\b(?:' + '|'.join(re.escape(s) for s in skills) + r')\b'
                    self._compiled_patterns[category] = re.compile(simple, re.IGNORECASE)
                else:
                    # More precise patterns to reduce false positives
                    patterns = []
                    for skill in skills:
                        escaped = re.escape(skill)
                        if ' ' in skill:
                            pattern = escaped.replace(r'\ ', r'\s+')
                        else:
                            pattern = escaped
                        patterns.append(pattern)
                    combined = r'\b(?:' + '|'.join(patterns) + r')\b'
                    self._compiled_patterns[category] = re.compile(combined, re.IGNORECASE)
            except re.error as e:
                logger.warning(f"Failed to compile regex for {category}: {e}")
                continue

    def _get_cache_key(self, text: str) -> str:
        """Generate efficient cache key using hash"""
        # Use first 100 chars + hash of full text for balance of uniqueness and speed
        prefix = text[:100]
        hash_suffix = hashlib.md5(text.encode()).hexdigest()[:8]
        return f"{len(text)}_{prefix}_{hash_suffix}"

    def _cache_get(self, key: str) -> Optional[JobAnalysisResult]:
        """Thread-safe cache retrieval"""
        with self._cache_lock:
            if key in self._result_cache:
                # Move to end (mark as recently used)
                result = self._result_cache.pop(key)
                self._result_cache[key] = result
                self._cache_stats['hits'] += 1
                return result
            else:
                self._cache_stats['misses'] += 1
                return None

    def _cache_put(self, key: str, result: JobAnalysisResult):
        """Thread-safe cache storage with LRU eviction"""
        with self._cache_lock:
            # Remove oldest entries if cache is full
            while len(self._result_cache) >= self.cache_size:
                self._result_cache.popitem(last=False)
                self._cache_stats['evictions'] += 1
            
            self._result_cache[key] = result

    def clean_and_validate_text(self, text: str) -> str:
        """Enhanced text cleaning with validation"""
        if not isinstance(text, str):
            raise ValueError("Input must be a string")
        
        text = text.strip()
        if len(text) < 10:
            logger.warning("Text too short for meaningful analysis")
            return text
        
        # More sophisticated cleaning
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove or replace problematic characters while preserving structure
        text = re.sub(r'[^\w\s\-\+\#\.\(\)\[\]/:,;!?&@]', ' ', text)
        
        # Handle common abbreviations and formats
        text = re.sub(r'\b(\d+)\+\s*years?\b', r'\1+ years', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(\w+)\.js\b', r'\1.js', text, flags=re.IGNORECASE)
        
        # Final cleanup
        text = re.sub(r'\s{2,}', ' ', text).strip()
        
        return text

    def extract_skills_skillner(self, text: str) -> Tuple[List[ExtractedSkill], float]:
        """Enhanced skillNER extraction with timing"""
        if not self.skill_extractor:
            return [], 0.0
        
        start_time = time.time()
        try:
            annotations = self.skill_extractor.annotate(text)
            skills_found = []
            
            results = annotations.get('results', {}) if isinstance(annotations, dict) else {}
            full_matches = results.get('full_matches', []) if isinstance(results, dict) else []
            
            for skill_data in full_matches[:self.max_skills_per_job]:
                try:
                    # Extract skill information with robust fallbacks
                    skill_id = (
                        skill_data.get('skill_id') or 
                        skill_data.get('skill') or 
                        skill_data.get('id') or ''
                    )
                    
                    if not skill_id:
                        continue
                    
                    # Get readable name with better fallback logic
                    skill_name = self.skill_name_mapping.get(skill_id)
                    if not skill_name:
                        # Try to extract from surface forms
                        surface_forms = skill_data.get('surface_forms', [])
                        if surface_forms and isinstance(surface_forms, list):
                            skill_name = surface_forms[0].get('surface_form', skill_id)
                        else:
                            skill_name = skill_id
                    
                    # Extract surface form with better handling
                    surface_form = ''
                    if isinstance(skill_data.get('surface_forms'), list) and skill_data['surface_forms']:
                        sf = skill_data['surface_forms'][0]
                        surface_form = (
                            sf.get('surface_form') or 
                            sf.get('surface') or 
                            sf.get('text') or skill_name
                        )
                    else:
                        surface_form = (
                            skill_data.get('surface_form') or 
                            skill_data.get('surface') or 
                            skill_data.get('text') or skill_name
                        )
                    
                    # Extract and validate confidence
                    confidence = 0.0
                    for conf_key in ['confidence_score', 'score', 'confidence']:
                        if conf_key in skill_data:
                            try:
                                confidence = float(skill_data[conf_key])
                                break
                            except (TypeError, ValueError):
                                continue
                    
                    # Apply confidence threshold
                    if confidence < self.confidence_threshold:
                        continue
                    
                    skill_type = skill_data.get('skill_type') or skill_data.get('type') or 'Technical'
                    
                    # Validate we have meaningful data
                    if skill_name and surface_form and len(skill_name.strip()) > 0:
                        skills_found.append(ExtractedSkill(
                            name=skill_name,
                            surface_form=surface_form,
                            confidence=confidence,
                            skill_type=skill_type,
                            source='skillNER'
                        ))
                
                except Exception as e:
                    logger.warning(f"Error processing skill data: {e}")
                    continue
            
            processing_time = time.time() - start_time
            logger.debug(f"skillNER extracted {len(skills_found)} skills in {processing_time:.3f}s")
            return skills_found, processing_time
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"skillNER extraction failed: {e}")
            return [], processing_time

    def extract_skills_fallback(self, text: str) -> Tuple[List[ExtractedSkill], float]:
        """Optimized fallback skill extraction"""
        start_time = time.time()
        skills_found = []
        
        try:
            # Use precompiled patterns for better performance
            for category, pattern in self._compiled_patterns.items():
                matches = pattern.finditer(text)
                for match in matches:
                    matched_text = match.group(0)
                    # Normalize the matched text
                    normalized = matched_text.lower().strip()
                    
                    # Skip very short matches or numbers
                    if len(normalized) < 2 or normalized.isdigit():
                        continue
                    
                    skills_found.append(ExtractedSkill(
                        name=matched_text.title(),
                        surface_form=matched_text,
                        confidence=0.85,
                        skill_type=category,
                        source='fallback'
                    ))
            
            # Remove duplicates more efficiently
            seen_skills = set()
            unique_skills = []
            for skill in skills_found:
                key = skill.name.lower().strip()
                if key not in seen_skills:
                    seen_skills.add(key)
                    unique_skills.append(skill)
            
            processing_time = time.time() - start_time
            logger.debug(f"Fallback extracted {len(unique_skills)} skills in {processing_time:.3f}s")
            return unique_skills, processing_time
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Fallback extraction failed: {e}")
            return [], processing_time

    def extract_entities_fast(self, text: str) -> Tuple[List[ExtractedEntity], float]:
        """Fast entity extraction with caching and filtering"""
        start_time = time.time()
        
        try:
            doc = self.nlp(text)
            entities = []
            
            # Predefined sets for faster lookup
            relevant_labels = {'ORG', 'PRODUCT', 'WORK_OF_ART', 'EVENT', 'LAW', 'LANGUAGE', 'MONEY', 'PERCENT'}
            tech_terms_lower = {
                'python', 'java', 'javascript', 'react', 'angular', 'aws', 'docker',
                'kubernetes', 'tensorflow', 'pytorch', 'mongodb', 'postgresql'
            }
            
            for ent in doc.ents:
                ent_lower = ent.text.lower().strip()
                
                # Skip misclassified tech terms
                if (ent_lower in tech_terms_lower and 
                    ent.label_ in {'PERSON', 'LOC', 'GPE'}):
                    continue
                
                # Skip very short entities unless they're organizations
                if len(ent.text.strip()) < 2 and ent.label_ != 'ORG':
                    continue
                
                # Include relevant entities
                if ent.label_ in relevant_labels or len(ent.text.strip()) > 3:
                    entities.append(ExtractedEntity(
                        text=ent.text,
                        label=ent.label_,
                        description=spacy.explain(ent.label_) or ent.label_,
                        confidence=1.0,
                        start=ent.start_char,
                        end=ent.end_char
                    ))
            
            processing_time = time.time() - start_time
            return entities, processing_time
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Entity extraction failed: {e}")
            return [], processing_time

    def extract_keywords_optimized(self, text: str) -> Tuple[List[Dict[str, Any]], float]:
        """Optimized keyword extraction with better scoring"""
        start_time = time.time()
        
        try:
            doc = self.nlp(text)
            keyword_freq = defaultdict(int)
            keyword_info = {}
            
            # Process tokens efficiently
            for token in doc:
                if (token.is_stop or token.is_punct or token.is_space or 
                    len(token.text) < 3 or token.text.isdigit() or 
                    token.text.lower() in {'year', 'years', 'experience'}):
                    continue
                
                # Focus on meaningful POS tags
                if token.pos_ in ['NOUN', 'ADJ', 'PROPN', 'VERB']:
                    lemma = token.lemma_.lower()
                    keyword_freq[lemma] += 1
                    
                    if lemma not in keyword_info:
                        keyword_info[lemma] = {
                            'text': lemma,
                            'pos': token.pos_,
                            'original_forms': set(),
                            'is_technical': False
                        }
                    
                    keyword_info[lemma]['original_forms'].add(token.text)
                    
                    # Mark as technical if it appears in our patterns
                    if not keyword_info[lemma]['is_technical']:
                        for skills in self.tech_skills_patterns.values():
                            if lemma in [s.lower() for s in skills]:
                                keyword_info[lemma]['is_technical'] = True
                                break
            
            # Build keyword list with enhanced scoring
            keywords = []
            for lemma, freq in keyword_freq.items():
                if freq >= 1:
                    info = keyword_info[lemma]
                    
                    # Enhanced importance scoring
                    base_score = freq
                    if info['pos'] in ['NOUN', 'PROPN']:
                        base_score *= 1.5
                    if info['is_technical']:
                        base_score *= 2.0
                    if freq > 2:  # Bonus for frequently mentioned terms
                        base_score *= 1.2
                    
                    keywords.append({
                        'text': lemma,
                        'pos': info['pos'],
                        'frequency': freq,
                        'original_forms': list(info['original_forms']),
                        'importance_score': round(base_score, 2),
                        'is_technical': info['is_technical']
                    })
            
            # Sort by importance and limit results
            keywords.sort(key=lambda x: x['importance_score'], reverse=True)
            keywords = keywords[:50]
            
            processing_time = time.time() - start_time
            return keywords, processing_time
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Keyword extraction failed: {e}")
            return [], processing_time

    def analyze_job_posting(self, text: str, job_id: str = None) -> JobAnalysisResult:
        """Main analysis method with comprehensive error handling and performance monitoring"""
        start_time = time.time()
        
        try:
            # Generate job ID if not provided
            if job_id is None:
                job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # Clean and validate input
            clean_text = self.clean_and_validate_text(text)
            
            # Check cache first
            cache_key = self._get_cache_key(clean_text)
            cached_result = self._cache_get(cache_key)
            if cached_result:
                cached_result.cache_hit = True
                cached_result.job_id = job_id  # Update job ID
                return cached_result
            
            # Extract skills using available methods
            skillner_skills, skillner_time = [], 0.0
            fallback_skills, fallback_time = [], 0.0
            
            if not self.fast_mode and self.skill_extractor:
                skillner_skills, skillner_time = self.extract_skills_skillner(clean_text)
            
            fallback_skills, fallback_time = self.extract_skills_fallback(clean_text)
            
            # Combine and deduplicate skills
            all_skills = skillner_skills + fallback_skills
            unique_skills = self._deduplicate_skills_advanced(all_skills)
            
            # Extract other information (skip in ultra-fast mode)
            entities, entity_time = [], 0.0
            keywords, keyword_time = [], 0.0
            
            if not self.fast_mode or len(unique_skills) < 5:  # Extract more info if few skills found
                entities, entity_time = self.extract_entities_fast(clean_text)
                keywords, keyword_time = self.extract_keywords_optimized(clean_text)
            
            # Calculate processing time
            total_time = time.time() - start_time
            
            # Build comprehensive metadata
            metadata = {
                'original_length': len(text),
                'cleaned_length': len(clean_text),
                'word_count': len(clean_text.split()),
                'skillner_skills_count': len(skillner_skills),
                'fallback_skills_count': len(fallback_skills),
                'total_unique_skills': len(unique_skills),
                'entities_count': len(entities),
                'keywords_count': len(keywords),
                'processing_times': {
                    'total': round(total_time, 4),
                    'skillner': round(skillner_time, 4),
                    'fallback': round(fallback_time, 4),
                    'entities': round(entity_time, 4),
                    'keywords': round(keyword_time, 4)
                },
                'fast_mode': self.fast_mode,
                'confidence_threshold': self.confidence_threshold,
                'processing_timestamp': datetime.now().isoformat()
            }
            
            # Create result
            result = JobAnalysisResult(
                job_id=job_id,
                skills=unique_skills,
                entities=entities,
                keywords=keywords,
                requirements_sections=[],
                metadata=metadata,
                processing_time=total_time,
                cache_hit=False
            )
            
            # Cache the result
            try:
                self._cache_put(cache_key, result)
            except Exception as e:
                logger.warning(f"Failed to cache result: {e}")
            
            # Update performance stats
            self._update_performance_stats(total_time, skillner_time, entity_time + keyword_time, fallback_time)
            
            return result
            
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"Error analyzing job posting {job_id}: {e}")
            
            # Return minimal result rather than failing
            return JobAnalysisResult(
                job_id=job_id or "error_job",
                skills=[],
                entities=[],
                keywords=[],
                requirements_sections=[],
                metadata={
                    'error': str(e),
                    'processing_time': total_time,
                    'processing_timestamp': datetime.now().isoformat()
                },
                processing_time=total_time
            )

    def _deduplicate_skills_advanced(self, skills: List[ExtractedSkill]) -> List[ExtractedSkill]:
        """Advanced skill deduplication with similarity checking"""
        if not skills:
            return []
        
        skill_groups = defaultdict(list)
        
        # Group similar skills
        for skill in skills:
            key = skill.name.lower().strip()
            # Handle common variations
            key = key.replace('.js', 'js').replace('_', ' ').replace('-', ' ')
            skill_groups[key].append(skill)
        
        # Select best skill from each group
        deduplicated = []
        for group in skill_groups.values():
            # Prefer skillNER over fallback, then by confidence
            best_skill = max(group, key=lambda s: (
                s.source == 'skillNER',  # Prefer skillNER
                s.confidence,  # Then by confidence
                -len(s.surface_form)  # Then by shorter surface form (more precise)
            ))
            deduplicated.append(best_skill)
        
        # Sort by confidence and limit
        result = sorted(deduplicated, key=lambda x: x.confidence, reverse=True)
        return result[:self.max_skills_per_job]

    def _update_performance_stats(self, total_time: float, skillner_time: float, 
                                 spacy_time: float, fallback_time: float):
        """Update performance statistics"""
        self._performance_stats['total_jobs'] += 1
        self._performance_stats['total_time'] += total_time
        self._performance_stats['skillner_time'] += skillner_time
        self._performance_stats['spacy_time'] += spacy_time
        self._performance_stats['fallback_time'] += fallback_time

    def analyze_multiple_postings(self, job_postings: List[str], job_ids: List[str] = None) -> Dict[str, Any]:
        """Analyze multiple job postings with optional parallel processing"""
        if job_ids is None:
            job_ids = [f"job_{i+1:03d}" for i in range(len(job_postings))]
        
        if len(job_ids) != len(job_postings):
            raise ValueError("Number of job_ids must match number of job_postings")
        
        start_time = time.time()
        results = []
        failed_jobs = []
        
        if self.enable_threading and len(job_postings) > 2:
            # Parallel processing for large batches
            logger.info(f"Processing {len(job_postings)} jobs in parallel with {self.max_workers} workers")
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all jobs
                future_to_job = {
                    executor.submit(self.analyze_job_posting, posting, job_id): (posting, job_id)
                    for posting, job_id in zip(job_postings, job_ids)
                }
                
                # Collect results as they complete
                for i, future in enumerate(as_completed(future_to_job)):
                    posting, job_id = future_to_job[future]
                    try:
                        result = future.result(timeout=30)  # 30 second timeout per job
                        results.append(result)
                        if (i + 1) % 10 == 0:  # Progress logging every 10 jobs
                            logger.info(f"Completed {i + 1}/{len(job_postings)} jobs")
                    except Exception as e:
                        logger.error(f"Failed to analyze job {job_id}: {e}")
                        failed_jobs.append({'job_id': job_id, 'error': str(e)})
        else:
            # Sequential processing
            logger.info(f"Processing {len(job_postings)} jobs sequentially")
            for i, (posting, job_id) in enumerate(zip(job_postings, job_ids)):
                try:
                    result = self.analyze_job_posting(posting, job_id)
                    results.append(result)
                    if (i + 1) % 5 == 0:  # Progress logging every 5 jobs
                        logger.info(f"Completed {i + 1}/{len(job_postings)} jobs")
                except Exception as e:
                    logger.error(f"Failed to analyze job {job_id}: {e}")
                    failed_jobs.append({'job_id': job_id, 'error': str(e)})
        
        total_processing_time = time.time() - start_time
        logger.info(f"Batch processing completed in {total_processing_time:.2f}s")
        
        return self._aggregate_results_enhanced(results, failed_jobs, total_processing_time)

    def _aggregate_results_enhanced(self, results: List[JobAnalysisResult], 
                                  failed_jobs: List[Dict], total_time: float) -> Dict[str, Any]:
        """Enhanced result aggregation with detailed analytics"""
        if not results:
            return {
                'error': 'No jobs successfully analyzed',
                'failed_jobs': failed_jobs,
                'processing_time': total_time
            }
        
        # Collect comprehensive statistics
        all_skills = []
        all_entities = []
        all_keywords = []
        skill_types = defaultdict(list)
        skill_sources = defaultdict(list)
        processing_times = []
        cache_hits = 0
        
        for result in results:
            # Skills analysis
            for skill in result.skills:
                all_skills.append(skill.name)
                skill_types[skill.skill_type].append(skill.name)
                skill_sources[skill.source].append(skill.name)
            
            # Entities and keywords
            for entity in result.entities:
                all_entities.append(entity.text.lower())
            
            for keyword in result.keywords:
                all_keywords.extend([keyword['text']] * keyword['frequency'])
            
            # Performance metrics
            processing_times.append(result.processing_time)
            if result.cache_hit:
                cache_hits += 1
        
        # Calculate advanced statistics
        total_jobs = len(results)
        avg_skills_per_job = sum(len(r.skills) for r in results) / total_jobs if total_jobs > 0 else 0
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        cache_hit_rate = cache_hits / total_jobs if total_jobs > 0 else 0
        
        # Skill diversity metrics
        unique_skills = set(all_skills)
        skill_diversity = len(unique_skills) / len(all_skills) if all_skills else 0
        
        return {
            'summary': {
                'total_jobs_analyzed': total_jobs,
                'failed_jobs_count': len(failed_jobs),
                'success_rate': total_jobs / (total_jobs + len(failed_jobs)) if (total_jobs + len(failed_jobs)) > 0 else 0,
                'avg_skills_per_job': round(avg_skills_per_job, 2),
                'avg_processing_time': round(avg_processing_time, 4),
                'total_processing_time': round(total_time, 2),
                'cache_hit_rate': round(cache_hit_rate, 3),
                'skill_diversity': round(skill_diversity, 3),
                'total_unique_skills': len(unique_skills),
                'total_unique_entities': len(set(all_entities)),
                'processing_timestamp': datetime.now().isoformat()
            },
            'skills_analysis': {
                'top_skills': Counter(all_skills).most_common(25),
                'skills_by_type': {k: Counter(v).most_common(15) for k, v in skill_types.items()},
                'skills_by_source': {k: Counter(v).most_common(15) for k, v in skill_sources.items()},
                'skill_frequency_distribution': self._get_frequency_distribution(all_skills)
            },
            'entities_analysis': {
                'top_entities': Counter(all_entities).most_common(20),
                'entity_frequency_distribution': self._get_frequency_distribution(all_entities)
            },
            'keywords_analysis': {
                'top_keywords': Counter(all_keywords).most_common(25),
                'keyword_frequency_distribution': self._get_frequency_distribution(all_keywords)
            },
            'performance_metrics': {
                'processing_times': {
                    'min': min(processing_times) if processing_times else 0,
                    'max': max(processing_times) if processing_times else 0,
                    'avg': avg_processing_time,
                    'median': sorted(processing_times)[len(processing_times)//2] if processing_times else 0
                },
                'cache_performance': {
                    'hit_rate': cache_hit_rate,
                    'total_hits': cache_hits,
                    'cache_stats': self._cache_stats.copy()
                },
                'overall_stats': self._performance_stats.copy()
            },
            'individual_results': [self._result_to_dict_enhanced(r) for r in results],
            'failed_jobs': failed_jobs,
            'export_timestamp': datetime.now().isoformat()
        }

    def _get_frequency_distribution(self, items: List[str]) -> Dict[str, int]:
        """Calculate frequency distribution ranges"""
        if not items:
            return {}
        
        counter = Counter(items)
        freq_counts = Counter(counter.values())
        
        return {
            'single_occurrence': freq_counts.get(1, 0),
            'low_frequency_2_5': sum(freq_counts.get(i, 0) for i in range(2, 6)),
            'medium_frequency_6_10': sum(freq_counts.get(i, 0) for i in range(6, 11)),
            'high_frequency_11_plus': sum(freq_counts.get(i, 0) for i in range(11, max(freq_counts.keys()) + 1)) if freq_counts else 0
        }

    def _result_to_dict_enhanced(self, result: JobAnalysisResult) -> Dict[str, Any]:
        """Enhanced result serialization with more metadata"""
        return {
            'job_id': result.job_id,
            'processing_time': result.processing_time,
            'cache_hit': result.cache_hit,
            'skills': [
                {
                    'name': s.name,
                    'surface_form': s.surface_form,
                    'confidence': round(s.confidence, 3),
                    'type': s.skill_type,
                    'source': s.source
                } for s in result.skills
            ],
            'entities': [
                {
                    'text': e.text,
                    'label': e.label,
                    'description': e.description,
                    'confidence': round(e.confidence, 3),
                    'position': {'start': e.start, 'end': e.end}
                } for e in result.entities
            ],
            'keywords': result.keywords,
            'metadata': result.metadata
        }

    def export_results_enhanced(self, results: Dict[str, Any], 
                               filename: str = None, 
                               format_type: str = 'json') -> str:
        """Enhanced export with multiple format support"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'job_analysis_results_{timestamp}.{format_type}'
        
        try:
            if format_type.lower() == 'json':
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
            
            elif format_type.lower() == 'csv':
                # Export summary data to CSV
                summary_data = []
                for result in results.get('individual_results', []):
                    row = {
                        'job_id': result['job_id'],
                        'processing_time': result['processing_time'],
                        'cache_hit': result['cache_hit'],
                        'skills_count': len(result['skills']),
                        'entities_count': len(result['entities']),
                        'keywords_count': len(result['keywords']),
                        'top_skills': ', '.join([s['name'] for s in result['skills'][:5]])
                    }
                    summary_data.append(row)
                
                df = pd.DataFrame(summary_data)
                df.to_csv(filename, index=False, encoding='utf-8')
            
            else:
                raise ValueError(f"Unsupported format: {format_type}")
            
            logger.info(f"Results exported to {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"Failed to export results: {e}")
            raise

    def get_performance_report(self) -> Dict[str, Any]:
        """Generate detailed performance report"""
        stats = self._performance_stats.copy()
        if stats['total_jobs'] > 0:
            stats['avg_time_per_job'] = stats['total_time'] / stats['total_jobs']
            stats['avg_skillner_time'] = stats['skillner_time'] / stats['total_jobs']
            stats['avg_spacy_time'] = stats['spacy_time'] / stats['total_jobs']
            stats['avg_fallback_time'] = stats['fallback_time'] / stats['total_jobs']
        
        return {
            'performance_stats': stats,
            'cache_stats': self._cache_stats.copy(),
            'configuration': {
                'fast_mode': self.fast_mode,
                'confidence_threshold': self.confidence_threshold,
                'max_skills_per_job': self.max_skills_per_job,
                'cache_size': self.cache_size,
                'enable_threading': self.enable_threading,
                'max_workers': self.max_workers
            },
            'report_timestamp': datetime.now().isoformat()
        }

    def clear_cache(self):
        """Clear the result cache"""
        with self._cache_lock:
            self._result_cache.clear()
            self._cache_stats = {'hits': 0, 'misses': 0, 'evictions': 0}
        logger.info("Cache cleared")

    def optimize_for_batch_processing(self, expected_batch_size: int):
        """Optimize settings for batch processing"""
        if expected_batch_size > 100:
            self.enable_threading = True
            self.max_workers = min(8, expected_batch_size // 10)
            self.cache_size = min(1024, expected_batch_size * 2)
        elif expected_batch_size > 20:
            self.enable_threading = True
            self.max_workers = 4
        
        logger.info(f"Optimized for batch size {expected_batch_size}: "
                   f"threading={self.enable_threading}, workers={self.max_workers}")