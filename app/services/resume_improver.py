"""
Resume/Profile Improvement Service

This service uses AI to analyze job descriptions and provide specific,
actionable recommendations to improve user resumes/profiles for better job matching.
"""

import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

# Import existing AI infrastructure
try:
    from app.agents.groq_provider import GroqProvider
except ImportError:
    GroqProvider = None

logger = logging.getLogger(__name__)


@dataclass
class ImprovementSuggestion:
    """Represents a specific improvement suggestion for a profile section"""
    section: str  # e.g., 'summary', 'skills', 'work_experience'
    priority: str  # 'high', 'medium', 'low'
    type: str  # 'add', 'modify', 'rewrite', 'remove'
    current_content: Optional[str]
    suggested_content: str
    reasoning: str
    impact_score: float  # 0.0 to 1.0


@dataclass
class ResumeAnalysis:
    """Complete analysis and improvement recommendations for a resume"""
    overall_match_score: float  # 0.0 to 1.0
    missing_skills: List[str]
    keyword_gaps: List[str]
    suggestions: List[ImprovementSuggestion]
    industry_alignment: str
    experience_level_match: str
    summary: str
    action_items: List[str]


class ResumeImprover:
    """AI-powered resume improvement service"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        """Initialize the resume improver with AI provider"""
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.provider = None
        
        if GroqProvider and self.api_key:
            try:
                self.provider = GroqProvider(api_key=self.api_key, model=self.model)
                logger.info(f"✓ ResumeImprover initialized with {self.model}")
            except Exception as e:
                logger.error(f"Failed to initialize AI provider: {e}")
                self.provider = None
        else:
            logger.warning("AI provider not available - ResumeImprover will use fallback methods")

    def analyze_and_improve(self, profile_data: Dict[str, Any], job_description: str) -> ResumeAnalysis:
        """
        Main method to analyze a profile against a job description and provide improvements
        
        Args:
            profile_data: Dictionary containing profile information (from Profile model)
            job_description: The target job description text
            
        Returns:
            ResumeAnalysis object with detailed improvement recommendations
        """
        if not self.provider:
            logger.warning("No AI provider available, using fallback")
            return self._fallback_analysis(profile_data, job_description)
        
        try:
            # Generate comprehensive analysis using AI
            analysis_prompt = self._build_analysis_prompt(profile_data, job_description)
            
            # Add retry logic for empty responses
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Get AI response with improved error handling
                    ai_response = None
                    
                    # Try the synchronous method first (most common case)
                    if hasattr(self.provider, '_generate_sync'):
                        try:
                            ai_response = self.provider._generate_sync(analysis_prompt, {
                                "temperature": 0.1,
                                "max_tokens": 4000,
                                "stop": ["\n\n##"]
                            })
                        except Exception as sync_e:
                            logger.warning(f"Sync method failed: {sync_e}")
                    
                    # Try async provider if sync failed or not available
                    if not ai_response and hasattr(self.provider, '__call__'):
                        try:
                            import asyncio
                            try:
                                loop = asyncio.get_event_loop()
                                ai_response = loop.run_until_complete(self.provider(analysis_prompt))
                            except RuntimeError:
                                # No event loop, create one
                                ai_response = asyncio.run(self.provider(analysis_prompt))
                        except Exception as async_e:
                            logger.warning(f"Async method failed: {async_e}")
                    
                    # Try direct call method as last resort
                    if not ai_response and hasattr(self.provider, 'generate'):
                        try:
                            ai_response = self.provider.generate(analysis_prompt)
                        except Exception as direct_e:
                            logger.warning(f"Direct call method failed: {direct_e}")
                    
                    # If still no response, try a simple call
                    if not ai_response:
                        try:
                            ai_response = str(self.provider(analysis_prompt))
                        except Exception as simple_e:
                            logger.warning(f"Simple call method failed: {simple_e}")
                    
                    # Check if response is empty or too short
                    if not ai_response or len(ai_response.strip()) < 10:
                        logger.warning(f"Empty AI response on attempt {attempt + 1}, retrying...")
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(2)  # Longer delay before retry
                            continue
                        else:
                            logger.warning("AI returned empty response after retries, using fallback")
                            return self._fallback_analysis(profile_data, job_description)
                    
                    # Log the raw response for debugging
                    logger.debug(f"Raw AI response (first 200 chars): {ai_response[:200]}")
                    
                    # Parse AI response into structured analysis
                    analysis = self._parse_ai_response(ai_response, profile_data, job_description)
                    if analysis:
                        return analysis
                    else:
                        logger.warning("Failed to parse AI response, using fallback")
                        return self._fallback_analysis(profile_data, job_description)
                    
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"AI call failed on attempt {attempt + 1}: {e}, retrying...")
                        import time
                        time.sleep(1)
                    else:
                        logger.error(f"AI call failed after {max_retries} attempts: {e}")
                        break
            
            # If all retries failed, use fallback
            logger.info("Using fallback analysis method after retries")
            return self._fallback_analysis(profile_data, job_description)
            
        except Exception as e:
            logger.error(f"Failed to analyze resume: {e}")
            return self._fallback_analysis(profile_data, job_description)

    def _build_analysis_prompt(self, profile_data: Dict[str, Any], job_description: str) -> str:
        """Build a comprehensive prompt for AI analysis"""
        
        # Extract profile information
        profile_summary = self._extract_profile_summary(profile_data)
        
        prompt = f"""
# RESUME IMPROVEMENT ANALYSIS

You are an expert career coach and ATS optimization specialist. Analyze the provided resume/profile against the target job description and provide specific, actionable improvement recommendations.

## TARGET JOB DESCRIPTION:
```
{job_description}
```

## CURRENT RESUME/PROFILE:
```
{profile_summary}
```

## ANALYSIS REQUIREMENTS:

Provide a comprehensive analysis in the following JSON format:

```json
{{
  "overall_match_score": 0.75,
  "missing_skills": ["skill1", "skill2"],
  "keyword_gaps": ["keyword1", "keyword2"],
  "industry_alignment": "strong|moderate|weak",
  "experience_level_match": "perfect|close|gap",
  "summary": "Brief overall assessment of profile strength and main gaps",
  "suggestions": [
    {{
      "section": "summary|skills|work_experience|education|projects|certifications",
      "priority": "high|medium|low",
      "type": "add|modify|rewrite|remove",
      "current_content": "existing content or null",
      "suggested_content": "specific improvement recommendation",
      "reasoning": "why this change will improve job matching",
      "impact_score": 0.8
    }}
  ],
  "action_items": [
    "Specific action item 1",
    "Specific action item 2"
  ]
}}
```

## ANALYSIS GUIDELINES:

### 1. KEYWORD ANALYSIS
- Identify critical keywords from job description that are missing from resume
- Look for industry-specific terminology, tools, technologies, methodologies
- Consider ATS optimization and keyword density

### 2. SKILLS GAP ANALYSIS
- Compare required skills vs. current skills
- Identify both hard skills (technical) and soft skills (leadership, communication)
- Prioritize skills by importance to the role

### 3. EXPERIENCE ALIGNMENT
- Assess how well current experience matches job requirements
- Identify relevant experience that should be highlighted better
- Suggest ways to reframe experience to match job language

### 4. CONTENT OPTIMIZATION
- Analyze professional summary for impact and relevance
- Review work descriptions for achievement-focused language
- Suggest quantifiable metrics and results where possible

### 5. ATS OPTIMIZATION
- Ensure critical keywords appear in appropriate sections
- Recommend formatting improvements for ATS parsing
- Suggest section organization improvements

### 6. INDUSTRY ALIGNMENT
- Assess how well the profile aligns with industry expectations
- Suggest industry-specific terminology and trends to include
- Recommend certifications or skills that are highly valued

## SPECIFIC FOCUS AREAS:

1. **Professional Summary**: Should be compelling and keyword-rich
2. **Skills Section**: Must include relevant technical and soft skills
3. **Work Experience**: Should use action verbs and quantifiable achievements
4. **Education/Certifications**: Highlight relevant credentials
5. **Projects**: Showcase relevant technical projects if applicable

## OUTPUT REQUIREMENTS:
- Provide specific, actionable suggestions
- Include exact text recommendations where possible
- Prioritize suggestions by impact on job matching
- Explain the reasoning behind each recommendation
- Focus on improvements that will increase ATS compatibility
- Consider both human recruiter and automated screening systems

Return only valid JSON with no additional formatting or text.
"""
        
        return prompt

    def _extract_profile_summary(self, profile_data: Dict[str, Any]) -> str:
        """Extract and format profile data for analysis"""
        summary_parts = []
        
        # Basic info
        if profile_data.get('name'):
            summary_parts.append(f"Name: {profile_data['name']}")
        if profile_data.get('headline'):
            summary_parts.append(f"Headline: {profile_data['headline']}")
        if profile_data.get('location'):
            summary_parts.append(f"Location: {profile_data['location']}")
        
        # Professional summary
        if profile_data.get('summary'):
            summary_parts.append(f"Professional Summary:\n{profile_data['summary']}")
        
        # Skills
        skills = profile_data.get('skills', [])
        if skills:
            summary_parts.append(f"Skills: {', '.join(skills)}")
        
        # Work experience
        work_exp = profile_data.get('work_experience', [])
        if work_exp:
            summary_parts.append("Work Experience:")
            for i, job in enumerate(work_exp[:3]):  # Limit to recent 3 jobs
                exp_text = f"  {i+1}. {job.get('title', 'N/A')} at {job.get('company', 'N/A')}"
                if job.get('start') or job.get('end'):
                    exp_text += f" ({job.get('start', '')} - {job.get('end', 'Present')})"
                if job.get('description'):
                    exp_text += f"\n     {job['description'][:200]}..."
                summary_parts.append(exp_text)
        
        # Education
        education = profile_data.get('education', [])
        if education:
            summary_parts.append("Education:")
            for edu in education[:2]:  # Limit to 2 most relevant
                edu_text = f"  • {edu.get('degree', 'N/A')} from {edu.get('school', 'N/A')}"
                if edu.get('end'):
                    edu_text += f" ({edu['end']})"
                summary_parts.append(edu_text)
        
        # Projects
        projects = profile_data.get('projects', [])
        if projects:
            summary_parts.append("Key Projects:")
            for proj in projects[:3]:  # Limit to 3 projects
                proj_text = f"  • {proj.get('title', 'N/A')}"
                if proj.get('description'):
                    proj_text += f": {proj['description'][:150]}..."
                summary_parts.append(proj_text)
        
        # Certifications
        certs = profile_data.get('certifications', [])
        if certs:
            summary_parts.append(f"Certifications: {', '.join(certs)}")
        
        # Languages
        languages = profile_data.get('languages', [])
        if languages:
            summary_parts.append(f"Languages: {', '.join(languages)}")
        
        return "\n\n".join(summary_parts)

    def _parse_ai_response(self, ai_response: str, profile_data: Dict[str, Any], job_description: str) -> Optional[ResumeAnalysis]:
        """Parse AI response into structured ResumeAnalysis object"""
        try:
            # Clean the response - sometimes AI adds extra text before/after JSON
            cleaned_response = ai_response.strip()
            
            # Try to extract JSON from the response
            json_start = cleaned_response.find('{')
            json_end = cleaned_response.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.warning("No JSON found in AI response")
                return None
                
            json_str = cleaned_response[json_start:json_end]
            
            # Try to parse JSON response
            response_data = json.loads(json_str)
            
            # Validate required fields
            if not isinstance(response_data, dict):
                logger.warning("AI response is not a valid dictionary")
                return None
            
            # Parse suggestions
            suggestions = []
            for sugg_data in response_data.get('suggestions', []):
                try:
                    suggestion = ImprovementSuggestion(
                        section=sugg_data.get('section', 'general'),
                        priority=sugg_data.get('priority', 'medium'),
                        type=sugg_data.get('type', 'modify'),
                        current_content=sugg_data.get('current_content'),
                        suggested_content=sugg_data.get('suggested_content', ''),
                        reasoning=sugg_data.get('reasoning', ''),
                        impact_score=float(sugg_data.get('impact_score', 0.5))
                    )
                    suggestions.append(suggestion)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Skipping invalid suggestion: {e}")
                    continue
            
            # Create analysis object with validation
            try:
                analysis = ResumeAnalysis(
                    overall_match_score=max(0.0, min(1.0, float(response_data.get('overall_match_score', 0.5)))),
                    missing_skills=response_data.get('missing_skills', []) if isinstance(response_data.get('missing_skills'), list) else [],
                    keyword_gaps=response_data.get('keyword_gaps', []) if isinstance(response_data.get('keyword_gaps'), list) else [],
                    suggestions=suggestions,
                    industry_alignment=response_data.get('industry_alignment', 'moderate'),
                    experience_level_match=response_data.get('experience_level_match', 'close'),
                    summary=response_data.get('summary', 'Analysis completed'),
                    action_items=response_data.get('action_items', []) if isinstance(response_data.get('action_items'), list) else []
                )
                
                logger.info(f"Successfully parsed AI response with {len(suggestions)} suggestions")
                return analysis
                
            except (ValueError, TypeError) as e:
                logger.error(f"Failed to create ResumeAnalysis object: {e}")
                return None
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse AI response: {e}")
            logger.debug(f"Raw AI response (first 500 chars): {ai_response[:500]}")
            return None

    def _fallback_analysis(self, profile_data: Dict[str, Any], job_description: str) -> ResumeAnalysis:
        """Provide basic analysis when AI is not available"""
        logger.info("Using fallback analysis method")
        
        # Basic keyword matching
        profile_text = json.dumps(profile_data, default=str).lower()
        job_text = job_description.lower()
        
        # Simple keyword extraction
        common_keywords = [
            'python', 'java', 'javascript', 'react', 'node.js', 'sql', 'aws', 'docker',
            'kubernetes', 'agile', 'scrum', 'leadership', 'management', 'communication',
            'problem-solving', 'teamwork', 'project management', 'data analysis'
        ]
        
        missing_skills = []
        for keyword in common_keywords:
            if keyword in job_text and keyword not in profile_text:
                missing_skills.append(keyword)
        
        # Basic suggestions
        suggestions = []
        
        if not profile_data.get('summary'):
            suggestions.append(ImprovementSuggestion(
                section='summary',
                priority='high',
                type='add',
                current_content=None,
                suggested_content='Add a compelling professional summary that highlights your key strengths and career objectives.',
                reasoning='A professional summary helps recruiters quickly understand your value proposition.',
                impact_score=0.8
            ))
        
        if missing_skills:
            suggestions.append(ImprovementSuggestion(
                section='skills',
                priority='high',
                type='add',
                current_content=json.dumps(profile_data.get('skills', [])),
                suggested_content=f"Consider adding these relevant skills: {', '.join(missing_skills[:5])}",
                reasoning='Adding relevant skills from the job description will improve ATS matching.',
                impact_score=0.7
            ))
        
        return ResumeAnalysis(
            overall_match_score=0.6,  # Conservative estimate
            missing_skills=missing_skills[:10],
            keyword_gaps=missing_skills[:5],
            suggestions=suggestions,
            industry_alignment='moderate',
            experience_level_match='close',
            summary='Basic analysis completed. Consider using AI-powered analysis for more detailed recommendations.',
            action_items=[
                'Review and update professional summary',
                'Add relevant skills from job description',
                'Quantify achievements in work experience',
                'Ensure keywords appear throughout resume'
            ]
        )

    def generate_improved_profile(self, profile_data: Dict[str, Any], analysis: ResumeAnalysis) -> Dict[str, Any]:
        """
        Generate an improved version of the profile based on analysis recommendations
        
        Args:
            profile_data: Original profile data
            analysis: ResumeAnalysis with improvement suggestions
            
        Returns:
            Dictionary with improved profile data (copy, original unchanged)
        """
        improved_profile = profile_data.copy()
        changes_applied = []
        
        logger.info(f"generate_improved_profile called with profile_data type: {type(profile_data)}")
        logger.info(f"profile_data content (first 200 chars): {str(profile_data)[:200]}")
        
        # Apply suggestions based on priority and impact
        for suggestion in analysis.suggestions:
            if suggestion.impact_score >= 0.6:  # Only apply high-impact suggestions
                
                if suggestion.section == 'summary':
                    if suggestion.type == 'add' and not improved_profile.get('summary'):
                        improved_profile['summary'] = suggestion.suggested_content
                        changes_applied.append(f"Added professional summary")
                    elif suggestion.type in ['modify', 'rewrite']:
                        improved_profile['summary'] = suggestion.suggested_content
                        changes_applied.append(f"Enhanced professional summary")
                
                elif suggestion.section == 'skills' and suggestion.type == 'add':
                    current_skills = improved_profile.get('skills', [])
                    # Extract new skills from suggested content
                    if 'Consider adding' in suggestion.suggested_content:
                        new_skills_text = suggestion.suggested_content.split(': ')[-1]
                        new_skills = [s.strip() for s in new_skills_text.split(',')]
                        improved_profile['skills'] = list(set(current_skills + new_skills))
                        changes_applied.append(f"Added {len(new_skills)} relevant skills")
                
                elif suggestion.section == 'headline' and suggestion.type in ['modify', 'rewrite']:
                    improved_profile['headline'] = suggestion.suggested_content
                    changes_applied.append(f"Updated professional headline")
        
        # Add top missing skills to improve matching
        current_skills = improved_profile.get('skills', [])
        top_missing_skills = analysis.missing_skills[:8]  # Add top 8 missing skills
        new_skills_added = [skill for skill in top_missing_skills if skill not in current_skills]
        
        if new_skills_added:
            improved_profile['skills'] = list(set(current_skills + new_skills_added))
            changes_applied.append(f"Added {len(new_skills_added)} job-relevant skills")
        
        # Store the changes made for display
        improved_profile['_changes_applied'] = changes_applied
        improved_profile['_improvement_score'] = analysis.overall_match_score
        
        logger.info(f"generate_improved_profile returning type: {type(improved_profile)}")
        logger.info(f"improved_profile content (first 200 chars): {str(improved_profile)[:200]}")
        
        return improved_profile

    def get_improvement_priority_list(self, analysis: ResumeAnalysis) -> List[Dict[str, Any]]:
        """
        Get a prioritized list of improvements for the UI
        
        Returns:
            List of improvement items sorted by priority and impact
        """
        priority_order = {'high': 3, 'medium': 2, 'low': 1}
        
        sorted_suggestions = sorted(
            analysis.suggestions,
            key=lambda x: (priority_order.get(x.priority, 0), x.impact_score),
            reverse=True
        )
        
        improvements = []
        for i, suggestion in enumerate(sorted_suggestions):
            improvements.append({
                'id': i + 1,
                'title': f"Improve {suggestion.section.replace('_', ' ').title()}",
                'priority': suggestion.priority,
                'type': suggestion.type,
                'description': suggestion.reasoning,
                'suggestion': suggestion.suggested_content,
                'impact_score': suggestion.impact_score,
                'section': suggestion.section
            })
        
        return improvements
