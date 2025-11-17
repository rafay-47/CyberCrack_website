from jobspy import scrape_jobs

def fetch_jobs_from_jobspy(site_names, search_term, location, results_wanted, job_type=None, work_type=None, hours_old=None, distance=None, **kwargs):
    """
    Fetch jobs using jobspy for the given platforms and parameters.
    :param site_names: list of platform names (e.g., ['indeed', 'linkedin', ...])
    :param search_term: job search term
    :param location: job location
    :param results_wanted: number of results to fetch
    :param job_type: job type filter (fulltime, parttime, internship, contract)
    :param work_type: work type filter (remote, onsite, hybrid) - maps to is_remote
    :param hours_old: filter jobs by hours since posted
    :param distance: search distance in miles (default 50)
    :param kwargs: additional jobspy parameters
    :return: DataFrame of jobs
    """
    # Build jobspy parameters
    jobspy_params = {
        'site_name': site_names,
        'search_term': search_term,
        'location': location,
        'results_wanted': results_wanted,
        'linkedin_fetch_description': True,
        'description_format': 'markdown',
        'verbose': 1  # Show errors and warnings only
    }
    
    # Apply job type filter if specified
    if job_type and job_type.strip():
        # Map form values to jobspy values
        job_type_mapping = {
            'fulltime': 'fulltime',
            'parttime': 'parttime', 
            'internship': 'internship',
            'contract': 'contract'
        }
        if job_type in job_type_mapping:
            jobspy_params['job_type'] = job_type_mapping[job_type]
    
    # Apply work type filter (remote/hybrid/onsite) if specified
    if work_type and work_type.strip():
        if work_type in ['remote', 'hybrid']:
            jobspy_params['is_remote'] = True
        elif work_type == 'onsite':
            jobspy_params['is_remote'] = False
    
    # Apply hours_old filter if specified
    if hours_old and isinstance(hours_old, int) and hours_old > 0:
        jobspy_params['hours_old'] = hours_old
    
    # Apply distance filter if specified
    if distance and isinstance(distance, int) and distance > 0:
        jobspy_params['distance'] = distance
    
    # Add any additional parameters passed through kwargs
    # This allows for future extensibility without changing the function signature
    for key, value in kwargs.items():
        if key not in jobspy_params and value is not None:
            jobspy_params[key] = value
    
    
    return scrape_jobs(**jobspy_params)
