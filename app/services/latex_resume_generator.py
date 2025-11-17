"""
LaTeX Resume Generator Service

This service converts profile data into a professional resume PDF using LaTeX.
"""

import os
import subprocess
import tempfile
import logging
import json
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime

# Try to import ReportLab for fallback PDF generation
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

from .latex_templates import (
    RESUME_LATEX_TEMPLATE,
    HEADER_LINKS_TEMPLATE,
    PROFESSIONAL_SUMMARY_TEMPLATE,
    EXPERIENCE_TEMPLATE,
    EXPERIENCE_ITEM_TEMPLATE,
    TECHNICAL_SKILLS_TEMPLATE,
    SKILLS_ITEM_TEMPLATE,
    PROJECTS_TEMPLATE,
    PROJECT_ITEM_TEMPLATE,
    CERTIFICATIONS_TEMPLATE,
    CERTIFICATION_ITEM_TEMPLATE,
    EDUCATION_TEMPLATE,
    EDUCATION_ITEM_TEMPLATE
)

logger = logging.getLogger(__name__)


class LaTeXResumeGenerator:
    """Service for generating professional resumes in PDF format using LaTeX"""
    
    def __init__(self):
        """Initialize the LaTeX resume generator"""
        self.temp_dir = None
        
    def generate_resume_pdf(self, profile_data: Dict[str, Any], output_path: Optional[str] = None) -> str:
        """
        Generate a professional resume PDF from profile data
        
        Args:
            profile_data: Dictionary containing profile information
            output_path: Optional path for output file
            
        Returns:
            Path to generated PDF file
        """
        # Handle case where profile_data is passed as JSON string
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
                logger.warning("profile_data was passed as JSON string, parsed it successfully")
            except json.JSONDecodeError as e:
                logger.error(f"profile_data is a string but not valid JSON: {profile_data[:100]}...")
                raise ValueError(f"profile_data must be a dict or valid JSON string: {e}")
        
        if not isinstance(profile_data, dict):
            logger.error(f"Invalid profile_data type: {type(profile_data)}, value: {str(profile_data)[:100]}")
            raise ValueError(f"profile_data must be a dict, got {type(profile_data)}")
        
        try:
            # Create temporary directory for LaTeX processing
            temp_dir = tempfile.mkdtemp()
            self.temp_dir = temp_dir
            
            try:
                # Generate LaTeX content
                logger.info(f"About to generate LaTeX content. profile_data type: {type(profile_data)}")
                latex_content = self._generate_latex_content(profile_data)
                logger.info("LaTeX content generated successfully")
                
                # Write LaTeX file
                tex_file = Path(temp_dir) / "resume.tex"
                with open(tex_file, 'w', encoding='utf-8') as f:
                    f.write(latex_content)
                
                # Compile LaTeX to PDF
                pdf_path = self._compile_latex_to_pdf(tex_file, output_path, profile_data)
                
                return pdf_path
                
            finally:
                # Clean up temporary directory
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                
        except Exception as e:
            logger.error(f"Failed to generate resume PDF: {e}")
            raise RuntimeError(f"PDF generation failed: {e}")
    
    def _generate_latex_content(self, profile_data: Dict[str, Any]) -> str:
        """Generate LaTeX content from profile data using professional templates"""

        # Handle case where profile_data is passed as JSON string
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
                logger.warning("profile_data was passed as JSON string in _generate_latex_content, parsed it successfully")
            except json.JSONDecodeError as e:
                logger.error(f"profile_data is a string but not valid JSON in _generate_latex_content: {profile_data[:100]}...")
                raise ValueError(f"profile_data must be a dict or valid JSON string: {e}")
        
        if not isinstance(profile_data, dict):
            logger.error(f"Invalid profile_data type in _generate_latex_content: {type(profile_data)}, value: {str(profile_data)[:100]}")
            raise ValueError(f"profile_data must be a dict, got {type(profile_data)}")

        # Extract profile information
        name = profile_data.get('name', 'Your Name')
        email = profile_data.get('email', '')
        phone = profile_data.get('phone', '')
        location = profile_data.get('location', '')
        headline = profile_data.get('headline', 'Professional Title')
        summary = profile_data.get('summary', '')
        skills = profile_data.get('skills', [])
        work_experience = profile_data.get('work_experience', [])
        education = profile_data.get('education', [])
        projects = profile_data.get('projects', [])
        certifications = profile_data.get('certifications', [])
        languages = profile_data.get('languages', [])
        links = profile_data.get('links', [])

        # Ensure list fields are actually lists and log any issues
        def ensure_list(field_value, field_name):
            if not isinstance(field_value, list):
                logger.warning(f"{field_name} is not a list (type: {type(field_value)}), converting to empty list")
                return []
            return field_value
        
        skills = ensure_list(skills, 'skills')
        work_experience = ensure_list(work_experience, 'work_experience') 
        education = ensure_list(education, 'education')
        projects = ensure_list(projects, 'projects')
        certifications = ensure_list(certifications, 'certifications')
        languages = ensure_list(languages, 'languages')
        links = ensure_list(links, 'links')

        # Build sections in the exact order from the example
        sections = []

        # Professional Summary (always include if available)
        if summary:
            sections.append(PROFESSIONAL_SUMMARY_TEMPLATE.format(
                summary=self._escape_latex(summary)
            ))

        # Experience section
        if work_experience:
            experience_items = []
            for job in work_experience[:5]:  # Limit to 5 most recent jobs
                # Handle case where job is a string instead of dict
                if isinstance(job, str):
                    logger.warning(f"Found string in work_experience instead of dict: {job[:100]}")
                    continue
                if not isinstance(job, dict):
                    logger.warning(f"Found non-dict in work_experience: {type(job)}")
                    continue
                    
                title = job.get('title', 'Position')
                company = job.get('company', 'Company')
                start_date = job.get('start', '')
                end_date = job.get('end', 'Present')

                # Format date range exactly like the example
                date_range = f"{start_date} -- {end_date}" if start_date else end_date

                # Generate bullet points from description
                description = job.get('description', '')
                bullet_points = ""
                if description:
                    points = self._split_into_bullet_points(description)
                    valid_points = []
                    for point in points[:5]:  # Limit to 5 bullet points
                        clean_point = point.strip()
                        # Ensure proper capitalization and punctuation
                        if clean_point:
                            # Capitalize first letter
                            if clean_point[0].islower():
                                clean_point = clean_point[0].upper() + clean_point[1:]
                            # Add period if not ending with punctuation
                            if not clean_point.endswith(('.', '!', '?', ';', ':')):
                                clean_point += '.'
                            valid_points.append(f"    \\item {self._escape_latex(clean_point)}\n")
                    
                    bullet_points = "".join(valid_points) if valid_points else ""

                # Always add experience but ensure we have at least one bullet point
                if not bullet_points:
                    bullet_points = "    \\item Professional experience details available upon request.\n"
                
                experience_items.append(EXPERIENCE_ITEM_TEMPLATE.format(
                    title=self._escape_latex(title),
                    company=self._escape_latex(company),
                    date_range=self._escape_latex(date_range),
                    bullet_points=bullet_points
                ))

            sections.append(EXPERIENCE_TEMPLATE.format(
                experience_items="".join(experience_items)
            ))

        # Technical Skills section 
        if skills:
            skills_items = self._generate_skills_items(skills)
            if skills_items:  # Only add if we have actual skill items
                sections.append(TECHNICAL_SKILLS_TEMPLATE.format(
                    skills_items="".join(skills_items)
                ))

        # Projects section (only include if user has projects in their profile)
        if projects:
            project_items = []
            for project in projects[:5]:  # Limit to 5 projects
                # Handle case where project is a string instead of dict
                if isinstance(project, str):
                    logger.warning(f"Found string in projects instead of dict: {project[:100]}")
                    continue
                if not isinstance(project, dict):
                    logger.warning(f"Found non-dict in projects: {type(project)}")
                    continue
                    
                title = project.get('title', 'Project')
                tech_stack = project.get('tech_stack', '')
                description = project.get('description', '')

                # Format tech stack exactly like the example
                tech_display = f"({tech_stack})" if tech_stack else ""

                # Generate bullet points
                bullet_points = ""
                if description:
                    points = self._split_into_bullet_points(description)
                    valid_points = []
                    for point in points[:5]:  # Limit to 5 bullet points
                        clean_point = point.strip()
                        # Ensure proper capitalization and punctuation
                        if clean_point:
                            # Capitalize first letter
                            if clean_point[0].islower():
                                clean_point = clean_point[0].upper() + clean_point[1:]
                            # Add period if not ending with punctuation
                            if not clean_point.endswith(('.', '!', '?', ';', ':')):
                                clean_point += '.'
                            valid_points.append(f"    \\item {self._escape_latex(clean_point)}\n")
                    
                    bullet_points = "".join(valid_points) if valid_points else ""

                # Always add project but ensure we have at least one bullet point
                if not bullet_points:
                    bullet_points = "    \\item Project details available upon request.\n"
                
                project_items.append(PROJECT_ITEM_TEMPLATE.format(
                    title=self._escape_latex(title),
                    tech_stack=tech_display,
                    bullet_points=bullet_points
                ))

            sections.append(PROJECTS_TEMPLATE.format(
                project_items="".join(project_items)
            ))

        # Certifications section (only include if user has certifications)
        if certifications:
            certification_items = []
            for cert in certifications[:8]:  # Limit to 8 certifications
                # Handle case where cert is a string instead of dict
                if isinstance(cert, str):
                    logger.warning(f"Found string in certifications instead of dict: {cert[:100]}")
                    # Convert string to a basic certification dict
                    cert = {
                        'name': cert.strip(),
                        'date': '',
                        'issuer': '',
                        'link': ''
                    }
                elif not isinstance(cert, dict):
                    logger.warning(f"Found non-dict in certifications: {type(cert)}")
                    continue
                    
                name = cert.get('name', 'Certification')
                issuer = cert.get('issuer', '')
                date = cert.get('date', '')
                link = cert.get('link', '')

                if link:
                    certification_items.append(CERTIFICATION_ITEM_TEMPLATE.format(
                        name=self._escape_latex(name),
                        date=self._escape_latex(date),
                        link=link,
                        issuer=self._escape_latex(issuer)
                    ))
                else:
                    # Create a proper item format
                    cert_text = self._escape_latex(name)
                    if date:
                        cert_text += f" ({self._escape_latex(date)})"
                    if issuer:
                        cert_text += f" {self._escape_latex(issuer)}"
                    certification_items.append(f"\\item {cert_text}")

            if certification_items:  # Only add if we have actual certification items
                sections.append(CERTIFICATIONS_TEMPLATE.format(
                    certification_items="".join(certification_items)
                ))

        # Education section (always include if available)
        if education:
            education_items = []
            for edu in education[:3]:  # Limit to 3 education entries
                # Handle case where edu is a string instead of dict
                if isinstance(edu, str):
                    logger.warning(f"Found string in education instead of dict: {edu[:100]}")
                    continue
                if not isinstance(edu, dict):
                    logger.warning(f"Found non-dict in education: {type(edu)}")
                    continue
                    
                degree = edu.get('degree', 'Degree')
                school = edu.get('school', 'Institution')
                start_date = edu.get('start', '')
                end_date = edu.get('end', '')

                # Format date range exactly like the example
                date_range = f"{start_date}-{end_date}" if start_date and end_date else (end_date or start_date)

                education_items.append(EDUCATION_ITEM_TEMPLATE.format(
                    school=self._escape_latex(school),
                    date_range=self._escape_latex(date_range),
                    degree=self._escape_latex(degree)
                ))

            sections.append(EDUCATION_TEMPLATE.format(
                education_items="".join(education_items)
            ))

        # Generate links section
        links_section = ""
        if links:
            link_items = []
            for link in links[:4]:  # Limit to 4 links
                # Handle case where link is a string instead of dict
                if isinstance(link, str):
                    logger.warning(f"Found string in links instead of dict: {link[:100]}")
                    # Convert string URL to a basic link dict
                    url = link.strip()
                    if url.startswith('mailto:'):
                        name = 'Email'
                        url = url
                    elif 'linkedin.com' in url:
                        name = 'LinkedIn'
                    elif 'github.com' in url:
                        name = 'GitHub'
                    elif url.startswith('http'):
                        name = 'Website'
                    else:
                        name = 'Link'
                    
                    link = {'name': name, 'url': url}
                elif not isinstance(link, dict):
                    logger.warning(f"Found non-dict in links: {type(link)}")
                    continue
                    
                name = link.get('name', '')
                url = link.get('url', '')
                if name and url:
                    link_items.append(f"~\\href{{{url}}}{{{self._escape_latex(name)}}}")

            if link_items:
                # Use simple format without table to avoid alignment issues
                links_text = " | ".join(link_items)
                links_section = HEADER_LINKS_TEMPLATE.format(
                    links=links_text
                )

        # Generate final LaTeX content
        latex_content = RESUME_LATEX_TEMPLATE.substitute(
            name=self._escape_latex(name),
            headline=self._escape_latex(headline),
            phone=self._escape_latex(phone),
            email=self._escape_latex(email),
            location=self._escape_latex(location),
            links_section=links_section,
            sections="\n\n".join(sections)
        )

        return latex_content

    def _generate_skills_items(self, skills: list) -> list:
        """Generate categorized skills items for the professional template"""
        if not skills:
            return []

        # Define skill categories with keywords
        categories = {
            'Programming Languages': [
                'python', 'java', 'javascript', 'c++', 'c#', 'php', 'ruby', 'go', 'rust',
                'swift', 'kotlin', 'typescript', 'scala', 'perl', 'r', 'matlab', 'dart', 'sql'
            ],
            'Frameworks \\& Libraries': [
                'react', 'angular', 'vue', 'node.js', 'express', 'django', 'flask', 'spring',
                'asp.net', 'laravel', 'rails', 'fastapi', 'next.js', 'nest.js', 'flutter',
                'tensorflow', 'pytorch', 'pandas', 'numpy', 'scikit-learn', 'html', 'css',
                'bootstrap', 'tailwind', 'jquery', 'redux', 'graphql', 'apollo', 'razor pages',
                'core', 'blazor'
            ],
            'Tools \\& Platforms': [
                'git', 'github', 'gitlab', 'docker', 'kubernetes', 'jenkins', 'travis',
                'circleci', 'aws', 'azure', 'gcp', 'heroku', 'vercel', 'netlify', 'linux',
                'windows', 'macos', 'visual studio', 'vscode', 'intellij', 'eclipse',
                'postman', 'swagger', 'jira', 'confluence', 'slack', 'discord'
            ],
            'Databases \\& Cloud Storage': [
                'sql server', 'mysql', 'postgresql', 'mongodb', 'redis', 'elasticsearch',
                'oracle', 'sqlite', 'dynamodb', 'firebase', 'firestore', 'supabase', 'aws s3',
                'azure blob', 'google cloud storage', 'cassandra', 'neo4j'
            ]
        }

        # Categorize skills
        categorized = {cat: [] for cat in categories}
        uncategorized = []

        for skill in skills:
            skill_lower = skill.lower().strip()
            found = False
            for category, keywords in categories.items():
                if any(keyword in skill_lower for keyword in keywords):
                    categorized[category].append(skill)
                    found = True
                    break
            if not found:
                uncategorized.append(skill)

        # Generate skill items
        skill_items = []
        for category, skill_list in categorized.items():
            if skill_list:
                skills_text = ', '.join([self._escape_latex(s) for s in skill_list[:12]])  # Limit per category
                skill_items.append(SKILLS_ITEM_TEMPLATE.format(
                    category=category,
                    skills=skills_text
                ))

        # Add uncategorized skills if any
        if uncategorized:
            skills_text = ', '.join([self._escape_latex(s) for s in uncategorized[:10]])
            skill_items.append(SKILLS_ITEM_TEMPLATE.format(
                category='Other Skills',
                skills=skills_text
            ))

        return skill_items
    
    def _generate_header_section(self, name: str, email: str, phone: str, location: str, headline: str) -> str:
        """Generate header section with personal information"""
        header = f"\\begin{{center}}\n"
        header += f"{{\\Huge \\textbf{{{self._escape_latex(name)}}}}} \\\\\n"
        
        if headline:
            header += f"{{\\large \\color{{secondarycolor}} {self._escape_latex(headline)}}} \\\\\n"
        
        header += "\\vspace{8pt}\n"
        
        # Contact information
        contact_info = []
        if email:
            contact_info.append(f"\\href{{mailto:{email}}}{{\\faEnvelope\\ {self._escape_latex(email)}}}")
        if phone:
            contact_info.append(f"\\faPhone\\ {self._escape_latex(phone)}")
        if location:
            contact_info.append(f"\\faMapMarker\\ {self._escape_latex(location)}")
        
        if contact_info:
            header += " | ".join(contact_info) + " \\\\\n"
        
        header += "\\end{center}\n\\vspace{10pt}\n\n"
        
        return header
    
    def _generate_summary_section(self, summary: str) -> str:
        """Generate professional summary section"""
        content = "\\section{Professional Summary}\n"
        content += f"\\small {self._escape_latex(summary)}\n\\vspace{{8pt}}\n\n"
        return content
    
    def _generate_skills_section(self, skills: list) -> str:
        """Generate skills section"""
        if not skills:
            return ""
        
        content = "\\section{Technical Skills}\n"
        
        # Group skills into categories (basic categorization)
        programming_keywords = ['python', 'java', 'javascript', 'c++', 'c#', 'php', 'ruby', 'go', 'rust', 'swift', 'kotlin']
        web_keywords = ['html', 'css', 'react', 'angular', 'vue', 'node.js', 'express', 'django', 'flask', 'spring']
        database_keywords = ['sql', 'mysql', 'postgresql', 'mongodb', 'redis', 'elasticsearch', 'oracle']
        cloud_keywords = ['aws', 'azure', 'gcp', 'docker', 'kubernetes', 'terraform', 'jenkins']
        
        programming = [s for s in skills if any(kw in s.lower() for kw in programming_keywords)]
        web_tech = [s for s in skills if any(kw in s.lower() for kw in web_keywords)]
        databases = [s for s in skills if any(kw in s.lower() for kw in database_keywords)]
        cloud_tools = [s for s in skills if any(kw in s.lower() for kw in cloud_keywords)]
        other_skills = [s for s in skills if s not in programming + web_tech + databases + cloud_tools]
        
        if programming:
            content += f"\\textbf{{Programming Languages:}} {', '.join([self._escape_latex(s) for s in programming[:8]])} \\\\\n"
        if web_tech:
            content += f"\\textbf{{Web Technologies:}} {', '.join([self._escape_latex(s) for s in web_tech[:8]])} \\\\\n"
        if databases:
            content += f"\\textbf{{Databases:}} {', '.join([self._escape_latex(s) for s in databases[:6]])} \\\\\n"
        if cloud_tools:
            content += f"\\textbf{{Cloud \\& DevOps:}} {', '.join([self._escape_latex(s) for s in cloud_tools[:6]])} \\\\\n"
        if other_skills:
            content += f"\\textbf{{Other Skills:}} {', '.join([self._escape_latex(s) for s in other_skills[:10]])} \\\\\n"
        
        content += "\\vspace{8pt}\n\n"
        return content
    
    def _generate_experience_section(self, work_experience: list) -> str:
        """Generate work experience section"""
        if not work_experience:
            return ""
        
        content = "\\section{Professional Experience}\n"
        
        for job in work_experience[:5]:  # Limit to 5 most recent jobs
            title = job.get('title', 'Position')
            company = job.get('company', 'Company')
            start_date = job.get('start', '')
            end_date = job.get('end', 'Present')
            description = job.get('description', '')
            
            # Format date range
            date_range = f"{start_date} -- {end_date}" if start_date else end_date
            
            content += f"\\resumeSubheading{{{self._escape_latex(title)}}}{{{self._escape_latex(date_range)}}}\n"
            content += f"{{{self._escape_latex(company)}}}{{}}\n"
            
            if description:
                content += "\\begin{itemize}[leftmargin=*]\n"
                # Split description into bullet points
                points = self._split_into_bullet_points(description)
                for point in points[:4]:  # Limit to 4 bullet points
                    content += f"\\resumeItem{{{self._escape_latex(point.strip())}}}\n"
                content += "\\end{itemize}\n"
            
            content += "\\vspace{4pt}\n"
        
        content += "\\vspace{8pt}\n\n"
        return content
    
    def _generate_education_section(self, education: list) -> str:
        """Generate education section"""
        if not education:
            return ""
        
        content = "\\section{Education}\n"
        
        for edu in education[:3]:  # Limit to 3 entries
            degree = edu.get('degree', 'Degree')
            school = edu.get('school', 'Institution')
            start_date = edu.get('start', '')
            end_date = edu.get('end', '')
            description = edu.get('description', '')
            
            # Format date range
            date_range = f"{start_date} -- {end_date}" if start_date and end_date else (end_date or start_date)
            
            content += f"\\resumeSubheading{{{self._escape_latex(degree)}}}{{{self._escape_latex(date_range)}}}\n"
            content += f"{{{self._escape_latex(school)}}}{{}}\n"
            
            if description:
                content += f"\\textit{{\\small {self._escape_latex(description)}}}\n"
            
            content += "\\vspace{4pt}\n"
        
        content += "\\vspace{8pt}\n\n"
        return content
    
    def _generate_projects_section(self, projects: list) -> str:
        """Generate projects section"""
        if not projects:
            return ""
        
        content = "\\section{Key Projects}\n"
        
        for project in projects[:4]:  # Limit to 4 projects
            title = project.get('title', 'Project')
            link = project.get('link', '')
            description = project.get('description', '')
            
            if link:
                content += f"\\textbf{{\\href{{{link}}}{{{self._escape_latex(title)}}}}} \\\\\n"
            else:
                content += f"\\textbf{{{self._escape_latex(title)}}} \\\\\n"
            
            if description:
                content += f"\\small {self._escape_latex(description[:200])}{'...' if len(description) > 200 else ''} \\\\\n"
            
            content += "\\vspace{4pt}\n"
        
        content += "\\vspace{8pt}\n\n"
        return content
    
    def _generate_certifications_section(self, certifications: list) -> str:
        """Generate certifications section"""
        if not certifications:
            return ""
        
        content = "\\section{Certifications}\n"
        content += "\\begin{itemize}[leftmargin=*]\n"
        
        for cert in certifications[:6]:  # Limit to 6 certifications
            content += f"\\resumeItem{{{self._escape_latex(cert)}}}\n"
        
        content += "\\end{itemize}\n\\vspace{8pt}\n\n"
        return content
    
    def _generate_languages_section(self, languages: list) -> str:
        """Generate languages section"""
        if not languages:
            return ""
        
        content = "\\section{Languages}\n"
        content += f"\\textbf{{Languages:}} {', '.join([self._escape_latex(lang) for lang in languages[:5]])} \\\\\n"
        content += "\\vspace{8pt}\n\n"
        return content
    
    def _generate_links_section(self, links: list) -> str:
        """Generate links section"""
        if not links:
            return ""
        
        content = "\\section{Links}\n"
        content += "\\begin{itemize}[leftmargin=*]\n"
        
        for link in links[:4]:  # Limit to 4 links
            content += f"\\resumeItem{{\\href{{{link}}}{{{self._escape_latex(link)}}}}}\n"
        
        content += "\\end{itemize}\n\\vspace{8pt}\n\n"
        return content
    
    def _split_into_bullet_points(self, text: str) -> list:
        """Split description text into professional bullet points"""
        # Split by common separators
        points = []
        
        # Try different separators in order of preference
        if '•' in text:
            points = text.split('•')
        elif '\n-' in text:
            points = text.split('\n-')
        elif '\n•' in text:
            points = text.split('\n•')
        elif '\n*' in text:
            points = text.split('\n*')
        elif ';' in text and text.count(';') > 1:
            points = text.split(';')
        elif '. ' in text and len(text.split('. ')) > 2:
            points = text.split('. ')
        elif ',' in text and len(text.split(',')) > 3 and len(text) > 200:
            # For longer text with multiple commas, split by commas
            points = text.split(',')
        else:
            # If no clear separators, try to create logical breaks based on length
            if len(text) > 300:
                # Split long text into sentences and group them
                sentences = text.split('. ')
                points = []
                current_point = ""
                for sentence in sentences:
                    if len(current_point + sentence) < 140:  # Slightly shorter for better readability
                        current_point += sentence + ". "
                    else:
                        if current_point:
                            points.append(current_point.strip())
                        current_point = sentence + ". "
                if current_point:
                    points.append(current_point.strip())
            else:
                points = [text]
        
        # Clean up points and make them more impactful
        cleaned_points = []
        for point in points:
            point = point.strip().strip('-').strip('*').strip('•').strip()
            if point and len(point) > 20:  # Slightly longer minimum for more meaningful points
                # Capitalize first letter
                if point and point[0].islower():
                    point = point[0].upper() + point[1:]
                
                # Make bullet points more action-oriented and professional
                point = self._enhance_bullet_point(point)
                
                # Ensure point ends with proper punctuation
                if not point.endswith(('.', '!', '?')):
                    point += '.'
                    
                cleaned_points.append(point)
        
        # Ensure we always return at least one point if we have any text
        result = cleaned_points[:5]  # Limit to 5 bullet points for better readability
        
        # If we have no valid points but we have text, create a basic bullet point
        if not result and text and text.strip():
            # Use the original text as a single bullet point
            clean_text = text.strip()
            if clean_text[0].islower():
                clean_text = clean_text[0].upper() + clean_text[1:]
            if not clean_text.endswith(('.', '!', '?')):
                clean_text += '.'
            result = [clean_text]
        
        return result
    
    def _enhance_bullet_point(self, point: str) -> str:
        """Enhance bullet points to be more action-oriented and professional"""
        # Common action verbs for professional resumes
        action_verbs = [
            'achieved', 'developed', 'implemented', 'created', 'designed', 'built', 'improved',
            'optimized', 'increased', 'reduced', 'managed', 'led', 'collaborated', 'delivered',
            'established', 'enhanced', 'streamlined', 'automated', 'maintained', 'configured',
            'integrated', 'analyzed', 'researched', 'coordinated', 'facilitated', 'executed',
            'generated', 'initiated', 'launched', 'monitored', 'operated', 'organized',
            'planned', 'presented', 'produced', 'provided', 'resolved', 'supervised',
            'supported', 'tested', 'trained', 'utilized', 'validated', 'verified'
        ]
        
        # Check if the point already starts with an action verb
        first_word = point.split()[0].lower() if point.split() else ""
        
        # If it doesn't start with an action verb, try to improve it
        if first_word not in action_verbs:
            # Look for common patterns and enhance them
            if 'worked on' in point.lower():
                point = point.replace('worked on', 'developed', 1)
                point = point.replace('Worked on', 'Developed', 1)
            elif 'was responsible for' in point.lower():
                point = point.replace('was responsible for', 'managed', 1)
                point = point.replace('Was responsible for', 'Managed', 1)
            elif 'helped' in point.lower() and point.lower().startswith('helped'):
                point = point.replace('helped', 'assisted in', 1)
                point = point.replace('Helped', 'Assisted in', 1)
            elif 'did' in point.lower() and point.lower().startswith('did'):
                point = point.replace('did', 'performed', 1)
                point = point.replace('Did', 'Performed', 1)
            elif 'made' in point.lower() and point.lower().startswith('made'):
                point = point.replace('made', 'created', 1)
                point = point.replace('Made', 'Created', 1)
        
        return point
    
    def _escape_latex(self, text: str) -> str:
        """Escape special LaTeX characters in text"""
        if not text:
            return ""
        
        # LaTeX special characters that need escaping
        # Order matters - do backslash first, then others
        replacements = [
            ('\\', '\\textbackslash{}'),
            ('&', '\\&'),
            ('%', '\\%'),
            ('$', '\\$'),
            ('#', '\\#'),
            ('^', '\\textasciicircum{}'),
            ('_', '\\_'),
            ('{', '\\{'),
            ('}', '\\}'),
            ('~', '\\textasciitilde{}')
        ]
        
        escaped = text
        for char, replacement in replacements:
            escaped = escaped.replace(char, replacement)
        
        return escaped
    
    def _compile_latex_to_pdf(self, tex_file: Path, output_path: Optional[str] = None, profile_data: Optional[Dict[str, Any]] = None) -> str:
        """Compile LaTeX file to PDF with fallback to ReportLab"""
        try:
            # Check if pdflatex is available
            try:
                subprocess.run(['pdflatex', '--version'], capture_output=True, check=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                logger.warning("pdflatex is not installed or not available in PATH. Using ReportLab fallback.")
                return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
            
            # Change to temp directory for compilation
            original_cwd = os.getcwd()
            os.chdir(tex_file.parent)
            
            # Set environment variables to handle MiKTeX issues
            env = os.environ.copy()
            env['MIKTEX_AUTOINSTALL'] = 'no'  # Disable auto-install to avoid permission issues
            env['MIKTEX_ENABLE_INSTALLER'] = 'no'
            env['max_print_line'] = '10000'  # Prevent line wrapping in error messages
            
            # Run pdflatex command with increased timeout and better error handling
            cmd = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', '-file-line-error', tex_file.name]
            
            # Run twice to resolve references
            for i in range(2):
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
                    
                    # Check for specific MiKTeX errors
                    if result.returncode != 0:
                        error_msg = result.stderr or result.stdout
                        
                        # Log the full error message for debugging
                        logger.error(f"LaTeX compilation failed (run {i+1}):")
                        logger.error(f"Return code: {result.returncode}")
                        logger.error(f"STDOUT: {result.stdout}")
                        logger.error(f"STDERR: {result.stderr}")
                        
                        # Handle MiKTeX administrator update issue
                        if "administrator has checked for updates" in error_msg:
                            logger.warning("MiKTeX administrator update issue detected. Using ReportLab fallback.")
                            os.chdir(original_cwd)
                            return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
                        
                        # Handle package installation issues
                        if ("not found" in error_msg.lower() or 
                            "unknown" in error_msg.lower() or
                            "Emergency stop" in error_msg or
                            "! I can't find file" in error_msg):
                            logger.warning(f"LaTeX package/file issue detected")
                            if i == 0:  # Try once more with basic packages only
                                logger.info("Attempting simplified LaTeX compilation...")
                                self._create_simplified_latex(tex_file, profile_data)
                                continue
                            else:
                                logger.warning("LaTeX compilation failed even with simplified template. Using ReportLab fallback.")
                                os.chdir(original_cwd)
                                return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
                        
                        # If first run failed, try simplified version
                        if i == 0:
                            logger.info("First LaTeX compilation failed, trying simplified version...")
                            self._create_simplified_latex(tex_file, profile_data)
                            continue
                        else:
                            logger.warning("LaTeX compilation failed after retry. Using ReportLab fallback.")
                            os.chdir(original_cwd)
                            return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
                    else:
                        logger.info(f"LaTeX compilation successful on run {i+1}")
                        break  # Success, no need to run again
                        
                except subprocess.TimeoutExpired:
                    logger.warning(f"LaTeX compilation timed out (run {i+1})")
                    if i == 0:  # Try once more
                        continue
                    else:
                        logger.warning("LaTeX compilation timed out. Using ReportLab fallback.")
                        os.chdir(original_cwd)
                        return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
            
            # Move back to original directory
            os.chdir(original_cwd)
            
            # Get the generated PDF path
            pdf_file = tex_file.with_suffix('.pdf')
            
            if not pdf_file.exists():
                logger.warning("PDF file was not generated by LaTeX. Using ReportLab fallback.")
                return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
            
            # Copy to output path if specified
            if output_path:
                final_path = Path(output_path)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(pdf_file, final_path)
                return str(final_path)
            else:
                # Copy to a permanent location
                try:
                    from flask import current_app
                    output_dir = Path(current_app.static_folder) / 'downloads'
                except (ImportError, RuntimeError):
                    # Fallback if Flask context is not available
                    output_dir = Path("static/downloads")
                
                # Ensure the directory exists and is writable
                try:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    # Test write permissions
                    test_file = output_dir / '.test_write'
                    test_file.touch()
                    test_file.unlink()
                except Exception as e:
                    raise RuntimeError(f"Cannot create or write to downloads directory {output_dir}: {e}")
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                final_path = output_dir / f"resume_{timestamp}.pdf"
                
                import shutil
                shutil.copy2(pdf_file, final_path)
                
                # Verify the copy was successful
                if not final_path.exists():
                    raise RuntimeError(f"Failed to copy PDF to final location: {final_path}")
                
                return str(final_path)
                
        except subprocess.TimeoutExpired:
            logger.warning("LaTeX compilation timed out. Using ReportLab fallback.")
            os.chdir(original_cwd)
            return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)
        except Exception as e:
            logger.error(f"PDF compilation error: {e}")
            logger.warning("LaTeX compilation failed. Using ReportLab fallback.")
            os.chdir(original_cwd)
            return self._generate_pdf_with_reportlab(tex_file.parent, output_path, profile_data)

    def _generate_pdf_with_reportlab(self, temp_dir: Path, output_path: Optional[str] = None, profile_data: Optional[Dict[str, Any]] = None) -> str:
        """Generate PDF using ReportLab as fallback with professional design matching LaTeX template"""
        if not REPORTLAB_AVAILABLE:
            raise RuntimeError("Both LaTeX and ReportLab are unavailable. Cannot generate PDF.")
        
        # Handle case where profile_data is passed as JSON string
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
                logger.warning("profile_data was passed as JSON string in ReportLab fallback, parsed it successfully")
            except json.JSONDecodeError as e:
                logger.error(f"profile_data is a string but not valid JSON in ReportLab: {profile_data[:100]}...")
                profile_data = None  # Fall back to None
        
        try:
            if output_path:
                final_path = Path(output_path).resolve()  # Resolve to absolute path
                final_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info(f"ReportLab will create PDF at: {final_path}")
            else:
                try:
                    from flask import current_app
                    output_dir = Path(current_app.static_folder) / 'downloads'
                except (ImportError, RuntimeError):
                    # Fallback if Flask context is not available
                    output_dir = Path("static/downloads")
                
                output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                final_path = output_dir / f"resume_fallback_{timestamp}.pdf"
            
            # Create professional PDF with ReportLab matching LaTeX design
            doc = SimpleDocTemplate(str(final_path), pagesize=letter, 
                                  topMargin=0.55*inch, bottomMargin=0.55*inch,
                                  leftMargin=0.55*inch, rightMargin=0.55*inch)
            
            # Define professional color scheme (matching LaTeX template)
            primary_color = colors.Color(0, 0, 102/255)  # RGB(0, 0, 102)
            secondary_color = colors.Color(64/255, 64/255, 64/255)  # RGB(64, 64, 64)
            
            # Create professional styles matching LaTeX template
            styles = self._create_professional_reportlab_styles(primary_color, secondary_color)
            
            # Build the PDF content
            content = []
            
            # Add profile data if available
            if profile_data:
                # Header Section - Professional and Clean (matching LaTeX)
                content.extend(self._create_reportlab_header(profile_data, styles))
                
                # Professional Summary
                if profile_data.get('summary'):
                    content.extend(self._create_reportlab_summary(profile_data, styles))
                
                # Experience section
                if profile_data.get('work_experience'):
                    content.extend(self._create_reportlab_experience(profile_data, styles))
                
                # Technical Skills section 
                if profile_data.get('skills'):
                    content.extend(self._create_reportlab_skills(profile_data, styles))
                
                # Projects section
                if profile_data.get('projects'):
                    content.extend(self._create_reportlab_projects(profile_data, styles))
                
                # Certifications section
                if profile_data.get('certifications'):
                    content.extend(self._create_reportlab_certifications(profile_data, styles))
                
                # Education section
                if profile_data.get('education'):
                    content.extend(self._create_reportlab_education(profile_data, styles))
            else:
                # Default content when no profile data
                content.append(Paragraph("Professional Resume", styles['title']))
                content.append(Spacer(1, 12))
                content.append(Paragraph("Resume content would be displayed here.", styles['normal']))
            
            # Build the PDF
            doc.build(content)
            
            # Verify the file was created
            if final_path.exists():
                file_size = final_path.stat().st_size
                logger.info(f"Professional fallback PDF generated successfully: {final_path} ({file_size} bytes)")
                return str(final_path)
            else:
                logger.error(f"ReportLab failed to create PDF file at: {final_path}")
                raise RuntimeError(f"ReportLab failed to create PDF file at: {final_path}")
            
        except Exception as e:
            logger.error(f"ReportLab fallback failed: {e}")
            raise RuntimeError(f"Both LaTeX and ReportLab PDF generation failed: {e}")
    
    def _create_professional_reportlab_styles(self, primary_color, secondary_color):
        """Create professional styles for ReportLab that match the LaTeX template"""
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
        
        styles = {}
        base_styles = getSampleStyleSheet()
        
        # Title style (Name)
        styles['title'] = ParagraphStyle(
            'ProfessionalTitle',
            parent=base_styles['Heading1'],
            fontSize=18,
            textColor=colors.black,
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        # Headline style
        styles['headline'] = ParagraphStyle(
            'Headline',
            parent=base_styles['Normal'],
            fontSize=11,
            textColor=secondary_color,
            spaceAfter=12,
            alignment=TA_CENTER,
            fontName='Helvetica'
        )
        
        # Contact info style
        styles['contact'] = ParagraphStyle(
            'Contact',
            parent=base_styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        # Links style
        styles['links'] = ParagraphStyle(
            'Links',
            parent=base_styles['Normal'],
            fontSize=10,
            textColor=primary_color,
            spaceAfter=18,
            alignment=TA_CENTER,
            fontName='Helvetica'
        )
        
        # Section heading style
        styles['section_heading'] = ParagraphStyle(
            'SectionHeading',
            parent=base_styles['Heading2'],
            fontSize=12,
            textColor=primary_color,
            spaceAfter=8,
            spaceBefore=14,
            fontName='Helvetica-Bold'
        )
        
        # Normal text style
        styles['normal'] = ParagraphStyle(
            'ProfessionalNormal',
            parent=base_styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
            fontName='Helvetica'
        )
        
        # Job/Project title style
        styles['job_title'] = ParagraphStyle(
            'JobTitle',
            parent=base_styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=4,
            fontName='Helvetica-Bold'
        )
        
        # Bullet point style
        styles['bullet'] = ParagraphStyle(
            'Bullet',
            parent=base_styles['Normal'],
            fontSize=9,
            textColor=colors.black,
            spaceAfter=2,
            leftIndent=15,
            bulletIndent=8,
            fontName='Helvetica'
        )
        
        return styles
    
    def _create_reportlab_header(self, profile_data, styles):
        """Create professional header section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.enums import TA_CENTER
        
        content = []
        
        # Name
        name = profile_data.get('name', 'Your Name')
        content.append(Paragraph(f"<b>{name}</b>", styles['title']))
        
        # Headline
        headline = profile_data.get('headline', '')
        if headline:
            content.append(Paragraph(headline, styles['headline']))
        
        # Contact information in table format (matching LaTeX)
        contact_data = []
        phone = profile_data.get('phone', '')
        email = profile_data.get('email', '')
        location = profile_data.get('location', '')
        
        if phone or email or location:
            contact_row = []
            if phone:
                contact_row.append(f"<b>{phone}</b>")
            if email:
                contact_row.append(f'<link href="mailto:{email}">{email}</link>')
            if location:
                contact_row.append(f"<b>{location}</b>")
            
            if contact_row:
                contact_data.append(contact_row)
                
                # Create table for contact info
                contact_table = Table(contact_data, colWidths=[2*inch, 2*inch, 2*inch])
                contact_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                ]))
                content.append(contact_table)
        
        # Links section
        links = profile_data.get('links', [])
        if links:
            link_items = []
            for link in links[:4]:  # Limit to 4 links
                if isinstance(link, dict):
                    name = link.get('name', '')
                    url = link.get('url', '')
                    if name and url:
                        link_items.append(f'<link href="{url}">{name}</link>')
            
            if link_items:
                links_text = " | ".join(link_items)
                content.append(Spacer(1, 6))
                content.append(Paragraph(links_text, styles['links']))
        
        content.append(Spacer(1, 6))
        return content
    
    def _create_reportlab_summary(self, profile_data, styles):
        """Create professional summary section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer
        
        content = []
        summary = profile_data.get('summary', '')
        
        content.append(Paragraph("<b>Professional Summary</b>", styles['section_heading']))
        content.append(self._create_section_line())
        content.append(Paragraph(summary, styles['normal']))
        content.append(Spacer(1, 12))
        
        return content
    
    def _create_reportlab_experience(self, profile_data, styles):
        """Create experience section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        
        content = []
        work_experience = profile_data.get('work_experience', [])
        
        content.append(Paragraph("<b>Experience</b>", styles['section_heading']))
        content.append(self._create_section_line())
        
        for job in work_experience[:5]:  # Limit to 5 most recent jobs
            if not isinstance(job, dict):
                continue
                
            title = job.get('title', 'Position')
            company = job.get('company', 'Company')
            start_date = job.get('start', '')
            end_date = job.get('end', 'Present')
            description = job.get('description', '')
            
            # Format date range
            date_range = f"{start_date} -- {end_date}" if start_date else end_date
            
            # Job header (title, company, dates)
            job_header = f"<b>{title}</b>, {company}"
            job_data = [[job_header, f"<b>{date_range}</b>"]]
            
            job_table = Table(job_data, colWidths=[4.5*inch, 2*inch])
            job_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
            ]))
            
            content.append(job_table)
            
            # Job description bullet points
            if description:
                points = self._split_into_bullet_points(description)
                for point in points[:5]:  # Limit to 5 bullet points
                    clean_point = point.strip()
                    if clean_point:
                        # Ensure proper capitalization and punctuation
                        if clean_point[0].islower():
                            clean_point = clean_point[0].upper() + clean_point[1:]
                        if not clean_point.endswith(('.', '!', '?', ';', ':')):
                            clean_point += '.'
                        clean_point = self._enhance_bullet_point(clean_point)
                        content.append(Paragraph(f"• {clean_point}", styles['bullet']))
            
            content.append(Spacer(1, 8))
        
        return content
    
    def _create_reportlab_skills(self, profile_data, styles):
        """Create technical skills section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer
        
        content = []
        skills = profile_data.get('skills', [])
        
        if not skills:
            return content
        
        content.append(Paragraph("<b>Technical Skills</b>", styles['section_heading']))
        content.append(self._create_section_line())
        
        # Generate categorized skills
        skills_items = self._generate_skills_items(skills)
        
        for skill_item in skills_items:
            # Extract category and skills from the template format
            # skill_item format: "\\item \\textbf{category:} skills"
            if "\\textbf{" in skill_item and "}:" in skill_item:
                category_start = skill_item.find("\\textbf{") + 8
                category_end = skill_item.find("}:")
                skills_start = skill_item.find("}: ") + 3
                
                if category_start > 7 and category_end > category_start and skills_start > 2:
                    category = skill_item[category_start:category_end]
                    skills_text = skill_item[skills_start:].strip()
                    
                    content.append(Paragraph(f"• <b>{category}:</b> {skills_text}", styles['bullet']))
        
        content.append(Spacer(1, 12))
        return content
    
    def _create_reportlab_projects(self, profile_data, styles):
        """Create projects section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer
        
        content = []
        projects = profile_data.get('projects', [])
        
        if not projects:
            return content
        
        content.append(Paragraph("<b>Projects</b>", styles['section_heading']))
        content.append(self._create_section_line())
        
        for project in projects[:5]:  # Limit to 5 projects
            if not isinstance(project, dict):
                continue
                
            title = project.get('title', 'Project')
            tech_stack = project.get('tech_stack', '')
            description = project.get('description', '')
            
            # Project title with tech stack
            tech_display = f" ({tech_stack})" if tech_stack else ""
            project_header = f"<b>{title}</b>{tech_display}"
            content.append(Paragraph(project_header, styles['job_title']))
            
            # Project description bullet points
            if description:
                points = self._split_into_bullet_points(description)
                for point in points[:5]:  # Limit to 5 bullet points
                    clean_point = point.strip()
                    if clean_point:
                        # Ensure proper capitalization and punctuation
                        if clean_point[0].islower():
                            clean_point = clean_point[0].upper() + clean_point[1:]
                        if not clean_point.endswith(('.', '!', '?', ';', ':')):
                            clean_point += '.'
                        clean_point = self._enhance_bullet_point(clean_point)
                        content.append(Paragraph(f"• {clean_point}", styles['bullet']))
            
            content.append(Spacer(1, 6))
        
        return content
    
    def _create_reportlab_certifications(self, profile_data, styles):
        """Create certifications section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer
        
        content = []
        certifications = profile_data.get('certifications', [])
        
        if not certifications:
            return content
        
        content.append(Paragraph("<b>Online Courses & Certifications</b>", styles['section_heading']))
        content.append(self._create_section_line())
        
        for cert in certifications[:8]:  # Limit to 8 certifications
            if not isinstance(cert, dict):
                continue
                
            name = cert.get('name', 'Certification')
            issuer = cert.get('issuer', '')
            date = cert.get('date', '')
            link = cert.get('link', '')
            
            cert_text = f"• {name}"
            if date:
                cert_text += f" ({date})"
            if issuer:
                if link:
                    cert_text += f' <link href="{link}">{issuer}</link>'
                else:
                    cert_text += f" {issuer}"
            
            content.append(Paragraph(cert_text, styles['bullet']))
        
        content.append(Spacer(1, 12))
        return content
    
    def _create_reportlab_education(self, profile_data, styles):
        """Create education section for ReportLab"""
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
        
        content = []
        education = profile_data.get('education', [])
        
        if not education:
            return content
        
        content.append(Paragraph("<b>Education</b>", styles['section_heading']))
        content.append(self._create_section_line())
        
        for edu in education[:3]:  # Limit to 3 education entries
            if not isinstance(edu, dict):
                continue
                
            degree = edu.get('degree', 'Degree')
            school = edu.get('school', 'Institution')
            start_date = edu.get('start', '')
            end_date = edu.get('end', '')
            
            # Format date range
            date_range = f"{start_date}-{end_date}" if start_date and end_date else (end_date or start_date)
            
            # Education header (school and dates)
            edu_header = f"<b>{school}</b>"
            edu_data = [[edu_header, f"<b>{date_range}</b>"]]
            
            edu_table = Table(edu_data, colWidths=[4.5*inch, 2*inch])
            edu_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
            ]))
            
            content.append(edu_table)
            content.append(Paragraph(degree, styles['normal']))
            content.append(Spacer(1, 6))
        
        return content
    
    def _create_section_line(self):
        """Create a section divider line matching LaTeX template"""
        from reportlab.platypus import Spacer
        from reportlab.graphics.shapes import Drawing, Line
        from reportlab.graphics import renderPDF
        
        # Create a simple line drawing
        drawing = Drawing(6.5*inch, 1)
        line = Line(0, 0.5, 6.5*inch, 0.5)
        line.strokeColor = colors.Color(0, 0, 102/255)  # Primary color
        line.strokeWidth = 0.8
        drawing.add(line)
        
        return drawing
    
    def _create_simplified_latex(self, tex_file: Path, profile_data: Dict[str, Any]):
        """Create a simplified LaTeX file with minimal packages for better compatibility"""
        # Handle case where profile_data is passed as JSON string
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
                logger.warning("profile_data was passed as JSON string in simplified LaTeX, parsed it successfully")
            except json.JSONDecodeError as e:
                logger.error(f"profile_data is a string but not valid JSON in simplified LaTeX: {profile_data[:100]}...")
                profile_data = {}  # Fall back to empty dict
        
        simplified_content = self._get_simplified_document_header()
        
        # Add personal information
        name = profile_data.get('name', 'Your Name')
        email = profile_data.get('email', '')
        phone = profile_data.get('phone', '')
        location = profile_data.get('location', '')
        
        simplified_content += f"""
\\begin{{center}}
{{\\Large \\textbf{{{self._escape_latex(name)}}}}} \\\\
\\vspace{{5pt}}
"""
        
        # Contact information
        contact_info = []
        if email:
            contact_info.append(self._escape_latex(email))
        if phone:
            contact_info.append(self._escape_latex(phone))
        if location:
            contact_info.append(self._escape_latex(location))
        
        if contact_info:
            simplified_content += " | ".join(contact_info) + " \\\\\n"
        
        simplified_content += "\\end{center}\n\\vspace{10pt}\n\n"
        
        # Add basic sections
        if profile_data.get('summary'):
            simplified_content += f"""
\\textbf{{Professional Summary}}
\\vspace{{5pt}}

{self._escape_latex(profile_data['summary'])}
\\vspace{{10pt}}

"""
        
        if profile_data.get('skills'):
            skills = profile_data['skills']
            if isinstance(skills, list):
                skills_text = ', '.join([self._escape_latex(skill) for skill in skills[:15] if isinstance(skill, str)])
                simplified_content += f"""
\\textbf{{Skills}}
\\vspace{{5pt}}

{skills_text}
\\vspace{{10pt}}

"""
        
        # Work experience
        if profile_data.get('work_experience'):
            simplified_content += "\\textbf{Work Experience}\n\\vspace{5pt}\n\n"
            work_experience = profile_data['work_experience']
            if isinstance(work_experience, list):
                for exp in work_experience[:3]:
                    # Handle case where exp is a string instead of dict
                    if isinstance(exp, str):
                        logger.warning(f"Found string in work_experience instead of dict: {exp[:100]}")
                        continue
                    if not isinstance(exp, dict):
                        logger.warning(f"Found non-dict in work_experience: {type(exp)}")
                        continue
                        
                    title = self._escape_latex(exp.get('title', 'Position'))
                    company = self._escape_latex(exp.get('company', 'Company'))
                    dates = f"{exp.get('start', '')} - {exp.get('end', 'Present')}"
                
                simplified_content += f"""
\\textbf{{{title}}} at {company} ({self._escape_latex(dates)})
\\vspace{{3pt}}

"""
                if exp.get('description'):
                    desc = self._escape_latex(exp['description'][:300])
                    simplified_content += f"{desc}\n\\vspace{{8pt}}\n\n"
        
        simplified_content += "\n\\end{document}\n"
        
        # Write the simplified content
        with open(tex_file, 'w', encoding='utf-8') as f:
            f.write(simplified_content)
        
        logger.info("Created simplified LaTeX file for compatibility")
    
    def _get_simplified_document_header(self) -> str:
        """Get simplified LaTeX document header with minimal packages"""
        return """\\documentclass[11pt,a4paper]{article}
\\usepackage[utf8]{inputenc}
\\usepackage[margin=0.75in]{geometry}

% Remove page numbers
\\pagestyle{empty}

\\begin{document}

"""
