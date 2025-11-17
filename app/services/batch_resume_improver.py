"""
Batch Resume Improvement Service

This service handles batch processing of multiple jobs for resume improvement.
"""

import os
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from app.services.resume_improver import ResumeImprover
from app.services.latex_resume_generator import LaTeXResumeGenerator

logger = logging.getLogger(__name__)


class BatchResumeImprover:
    """Service for batch processing resume improvements against multiple job descriptions"""

    def __init__(self, resume_improver: Optional[ResumeImprover] = None,
                 latex_generator: Optional[LaTeXResumeGenerator] = None):
        """Initialize the batch resume improver"""
        self.resume_improver = resume_improver or ResumeImprover()
        self.latex_generator = latex_generator or LaTeXResumeGenerator()
        # Optimize for I/O bound operations (AI calls, PDF generation)
        # Use more threads than CPU cores since operations are mostly waiting
        self.max_workers = min(6, (os.cpu_count() or 2) + 2)  # More threads for I/O bound work

    def process_jobs_batch(self, profile_data: Dict[str, Any],
                          selected_jobs: List[Dict[str, Any]],
                          progress_callback: Optional[callable] = None) -> Dict[str, Any]:
        """
        Process multiple jobs in batch for resume improvement

        Args:
            profile_data: User's profile data
            selected_jobs: List of selected job dictionaries
            progress_callback: Optional callback for progress updates

        Returns:
            Dictionary containing batch processing results
        """
        batch_id = str(uuid.uuid4())
        results = {
            'batch_id': batch_id,
            'total_jobs': len(selected_jobs),
            'processed_jobs': 0,
            'successful_jobs': 0,
            'failed_jobs': 0,
            'job_results': [],
            'user_profile': profile_data,  # Store the user's profile data
            'created_at': datetime.utcnow().isoformat(),
            'status': 'processing'
        }

        logger.info(f"Starting batch processing for {len(selected_jobs)} jobs, batch_id: {batch_id}")

        # Process jobs concurrently
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all jobs for processing
            future_to_job = {}
            for i, job in enumerate(selected_jobs):
                # Create a clean job ID from URL or use index
                job_url = job.get('job_url', '')
                if job_url:
                    # Extract a clean identifier from URL
                    import re
                    job_id = re.sub(r'[^\w\-_]', '_', job_url.split('/')[-1])[:50]
                    if not job_id or job_id == '_':
                        job_id = f"job_{i}"
                else:
                    job_id = f"job_{i}"
                
                future = executor.submit(self._process_single_job,
                                       profile_data.copy(),
                                       job,
                                       job_id,
                                       batch_id)
                future_to_job[future] = (job, job_id, i)

            # Collect results as they complete
            for future in as_completed(future_to_job):
                job, job_id, job_index = future_to_job[future]
                results['processed_jobs'] += 1

                try:
                    job_result = future.result()
                    results['job_results'].append(job_result)

                    if job_result['status'] == 'success':
                        results['successful_jobs'] += 1
                    else:
                        results['failed_jobs'] += 1

                    logger.info(f"Completed job {job_index + 1}/{len(selected_jobs)}: {job_id}")

                except Exception as e:
                    logger.error(f"Failed to process job {job_id}: {e}")
                    results['failed_jobs'] += 1
                    results['job_results'].append({
                        'job_id': job_id,
                        'status': 'error',
                        'error': str(e),
                        'job_title': job.get('title', 'Unknown'),
                        'company': job.get('company', 'Unknown')
                    })

                # Update progress if callback provided
                if progress_callback:
                    progress = (results['processed_jobs'] / results['total_jobs']) * 100
                    progress_callback(progress, results)

        # Update final status
        results['status'] = 'completed' if results['failed_jobs'] == 0 else 'completed_with_errors'

        logger.info(f"Batch processing completed. Success: {results['successful_jobs']}, Failed: {results['failed_jobs']}")

        return results

    def _process_single_job(self, profile_data: Dict[str, Any],
                           job: Dict[str, Any],
                           job_id: str,
                           batch_id: str) -> Dict[str, Any]:
        """
        Process a single job for resume improvement

        Args:
            profile_data: User's profile data
            job: Job dictionary
            job_id: Unique job identifier
            batch_id: Batch processing identifier

        Returns:
            Dictionary containing job processing result
        """
        try:
            # Extract job description
            job_description = self._extract_job_description(job)

            if not job_description or len(job_description.strip()) < 50:
                raise ValueError("Job description is too short or missing")

            # Analyze and improve resume
            logger.info(f"Starting analysis for job {job_id}")
            analysis = self.resume_improver.analyze_and_improve(profile_data, job_description)
            
            if not analysis:
                raise ValueError("Failed to analyze resume - no analysis returned")

            # Generate improved profile
            logger.info(f"Generating improved profile for job {job_id}")
            improved_profile = self.resume_improver.generate_improved_profile(profile_data, analysis)
            
            if not improved_profile:
                raise ValueError("Failed to generate improved profile")

            # Generate PDF resume with robust error handling
            logger.info(f"Generating PDF resume for job {job_id}")
            
            try:
                pdf_path = self._generate_job_specific_resume(improved_profile, job, batch_id, job_id)
            except Exception as pdf_error:
                logger.error(f"PDF generation error for job {job_id}: {pdf_error}")
                raise ValueError(f"PDF generation failed: {pdf_error}")
            
            # Validate PDF generation
            if not pdf_path:
                raise ValueError("Failed to generate PDF resume file - no path returned")
            
            # Brief check to ensure file system operations are complete
            import time
            time.sleep(0.1)  # Reduced from 0.5s to 0.1s for better performance
            
            # Check if file exists and has reasonable size
            if not os.path.exists(pdf_path):
                # Try to list files in the directory to see what's actually there
                try:
                    pdf_dir = os.path.dirname(pdf_path)
                    if os.path.exists(pdf_dir):
                        files_in_dir = os.listdir(pdf_dir)
                        logger.info(f"Files in directory {pdf_dir}: {files_in_dir}")
                    else:
                        logger.error(f"Directory does not exist: {pdf_dir}")
                except Exception as e:
                    logger.error(f"Error listing directory: {e}")
                
                raise ValueError(f"Failed to generate PDF resume file - file not found at {pdf_path}")
            
            # Check if file has content (not empty)
            file_size = os.path.getsize(pdf_path)
            if file_size < 1024:  # Less than 1KB is probably an error
                raise ValueError(f"PDF file seems too small ({file_size} bytes) - possible generation error")
            
            logger.info(f"PDF generated successfully: {pdf_path} ({file_size} bytes)")

            # Create result
            result = {
                'job_id': job_id,
                'status': 'success',
                'job_title': job.get('title', 'Unknown'),
                'company': job.get('company', 'Unknown'),
                'job_url': job.get('job_url', ''),
                'improved_resume_path': pdf_path,
                'improved_profile': improved_profile,  # Include the improved profile data
                'analysis': {
                    'overall_match_score': analysis.overall_match_score,
                    'missing_skills': analysis.missing_skills,
                    'keyword_gaps': analysis.keyword_gaps,
                    'industry_alignment': analysis.industry_alignment,
                    'experience_level_match': analysis.experience_level_match,
                    'summary': analysis.summary,
                    'action_items': analysis.action_items
                },
                'improvements_count': len(analysis.suggestions),
                'processed_at': datetime.utcnow().isoformat()
            }

            return result

        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            return {
                'job_id': job_id,
                'status': 'error',
                'error': str(e),
                'job_title': job.get('title', 'Unknown'),
                'company': job.get('company', 'Unknown'),
                'job_url': job.get('job_url', ''),
                'processed_at': datetime.utcnow().isoformat()
            }

    def _extract_job_description(self, job: Dict[str, Any]) -> str:
        """Extract job description from job dictionary"""
        description = job.get('description', '')

        # If description is missing or too short, try to build from other fields
        if not description or len(description.strip()) < 100:
            title = job.get('title', '')
            company = job.get('company', '')
            requirements = job.get('requirements', '')
            responsibilities = job.get('responsibilities', '')

            description = f"""
            Job Title: {title}
            Company: {company}
            Requirements: {requirements}
            Responsibilities: {responsibilities}
            Description: {description}
            """.strip()

        return description

    def _generate_job_specific_resume(self, improved_profile: Dict[str, Any],
                                    job: Dict[str, Any],
                                    batch_id: str,
                                    job_id: str) -> str:
        """Generate a job-specific PDF resume"""
        try:
            # Create batch directory with absolute path
            batch_dir = Path.cwd() / "instance" / "tmp" / "job_applications" / batch_id
            batch_dir.mkdir(parents=True, exist_ok=True)

            # Generate safe filename
            import re
            company = job.get('company', 'Unknown')
            title = job.get('title', 'Unknown')
            
            # Clean company and title names for filename
            company = re.sub(r'[^\w\s\-_]', '', company).replace(' ', '_')[:30]
            title = re.sub(r'[^\w\s\-_]', '', title).replace(' ', '_')[:30]
            
            # Ensure we have valid names
            company = company if company else 'Company'
            title = title if title else 'Position'
            
            filename = f"improved_resume_{company}_{title}_{job_id[:8]}.pdf"
            output_path = batch_dir / filename

            # Generate PDF
            logger.info(f"Requesting PDF generation with output path: {output_path}")
            logger.info(f"improved_profile type: {type(improved_profile)}")
            logger.info(f"improved_profile content (first 200 chars): {str(improved_profile)[:200]}")
            pdf_path = self.latex_generator.generate_resume_pdf(improved_profile, str(output_path))
            
            logger.info(f"PDF generator returned path: {pdf_path}")
            
            # Verify the returned path exists
            if pdf_path and os.path.exists(pdf_path):
                logger.info(f"PDF file exists at returned path: {pdf_path}")
                return str(pdf_path)
            else:
                # Check if file exists at the original output path
                if os.path.exists(str(output_path)):
                    logger.info(f"PDF file found at original output path: {output_path}")
                    return str(output_path)
                else:
                    # Additional debugging
                    logger.error(f"PDF file not found at either returned path ({pdf_path}) or output path ({output_path})")
                    logger.error(f"Returned path exists check: {os.path.exists(pdf_path) if pdf_path else 'No path returned'}")
                    logger.error(f"Output path exists check: {os.path.exists(str(output_path))}")
                    logger.error(f"Current working directory: {os.getcwd()}")
                    
                    # Try to list the directory
                    try:
                        output_dir = os.path.dirname(str(output_path))
                        if os.path.exists(output_dir):
                            files = os.listdir(output_dir)
                            logger.error(f"Files in output directory {output_dir}: {files}")
                        else:
                            logger.error(f"Output directory does not exist: {output_dir}")
                    except Exception as e:
                        logger.error(f"Error checking output directory: {e}")
                    
                    raise RuntimeError(f"PDF generation failed - file not found at expected locations")

        except Exception as e:
            logger.error(f"Failed to generate PDF for job {job_id}: {e}")
            raise RuntimeError(f"PDF generation failed: {e}")

    def get_batch_results(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve batch processing results"""
        try:
            batch_dir = Path(f"instance/tmp/job_applications/{batch_id}")
            results_file = batch_dir / "batch_results.json"

            if results_file.exists():
                with open(results_file, 'r', encoding='utf-8') as f:
                    return json.load(f)

        except Exception as e:
            logger.error(f"Failed to load batch results for {batch_id}: {e}")

        return None

    def save_batch_results(self, batch_id: str, results: Dict[str, Any]):
        """Save batch processing results to file"""
        try:
            batch_dir = Path(f"instance/tmp/job_applications/{batch_id}")
            batch_dir.mkdir(parents=True, exist_ok=True)

            results_file = batch_dir / "batch_results.json"
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Failed to save batch results for {batch_id}: {e}")
            raise
