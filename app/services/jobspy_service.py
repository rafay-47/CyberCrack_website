from jobspy import scrape_jobs

def fetch_jobs_from_jobspy(site_names, search_term, location, results_wanted):
    """
    Fetch jobs using jobspy for the given platforms and parameters.
    :param site_names: list of platform names (e.g., ['indeed', 'linkedin', ...])
    :param search_term: job search term
    :param location: job location
    :param results_wanted: number of results to fetch
    :return: DataFrame of jobs
    """
    return scrape_jobs(
        site_name=site_names,
        search_term=search_term,
        location=location,
        results_wanted=results_wanted,
        linkedin_fetch_description=True
    )
