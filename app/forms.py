from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, DecimalField, TextAreaField, SelectField, HiddenField, validators, IntegerField, SelectMultipleField, BooleanField

class PurchaseForm(FlaskForm):
    name = StringField('Name', [validators.DataRequired()])
    email = StringField('Email', [validators.DataRequired(), validators.Email()])
    license_duration = SelectField('Usage Hours', 
                                  choices=[
                                      ('1', '1 Hour Usage - $9.99'),
                                      ('2', '2 Hours Usage - $19.99'),
                                      ('3', '3 Hours Usage - $29.99'),
                                      ('4', '4 Hours Usage - $37.00'),
                                      ('5', '5 Hours Usage - $45.00')
                                  ],
                                  validators=[validators.DataRequired()])
    amount = HiddenField('Amount')
    submit = SubmitField('Purchase License')

class ContactForm(FlaskForm):
    name = StringField('Name', [validators.DataRequired()])
    email = StringField('Email', [validators.DataRequired(), validators.Email()])
    message = TextAreaField('Message', [validators.DataRequired()])
    submit = SubmitField('Send Message')

class JobScrapingForm(FlaskForm):
    # Mandatory Fields - Job Sites
    indeed = BooleanField('Indeed')
    linkedin = BooleanField('LinkedIn')
    glassdoor = BooleanField('Glassdoor')
    google = BooleanField('Google Jobs')
    
    # Mandatory Search Parameters
    search_term = StringField('Search Term', 
                             default='software engineer',
                             validators=[validators.DataRequired()],
                             render_kw={'placeholder': 'e.g., software engineer, data scientist'})
    
    location = StringField('Location', 
                          default='Singapore',
                          validators=[validators.DataRequired()],
                          render_kw={'placeholder': 'e.g., Singapore, New York, London'})
    
    results_wanted = IntegerField('Number of Results', 
                                 default=50,
                                 validators=[validators.DataRequired(), validators.NumberRange(min=1, max=500)],
                                 render_kw={'placeholder': '1-500'})
    
    # Optional Basic Fields
    google_search_term = StringField('Google Search Term (Optional)', 
                                   default='',
                                   render_kw={'placeholder': 'Custom search term for Google Jobs only'})
    
    distance = IntegerField('Distance (miles)', 
                           default=50,
                           validators=[validators.Optional(), validators.NumberRange(min=1, max=200)],
                           render_kw={'placeholder': 'Default: 50 miles'})
    
    # Optional Advanced Fields
    job_type = SelectField('Job Type', 
                          choices=[
                              ('', 'Any'),
                              ('fulltime', 'Full-time'),
                              ('parttime', 'Part-time'),
                              ('internship', 'Internship'),
                              ('contract', 'Contract')
                          ],
                          default='')
    
    is_remote = BooleanField('Remote Jobs Only', default=False)
    
    hours_old = IntegerField('Max Hours Old', 
                            default=168,
                            validators=[validators.Optional(), validators.NumberRange(min=1, max=720)],
                            render_kw={'placeholder': 'Default: 168 (1 week)'})
    
    easy_apply = BooleanField('Easy Apply Only', default=False)
    
    description_format = SelectField('Description Format',
                                   choices=[
                                       ('markdown', 'Markdown'),
                                       ('html', 'HTML')
                                   ],
                                   default='markdown')
    
    offset = IntegerField('Results Offset',
                         default=0,
                         validators=[validators.Optional(), validators.NumberRange(min=0, max=1000)],
                         render_kw={'placeholder': 'Start from result number (default: 0)'})
    
    verbose = SelectField('Logging Level',
                         choices=[
                             ('0', 'Errors Only'),
                             ('1', 'Errors + Warnings'),
                             ('2', 'All Logs')
                         ],
                         default='2')
    
    # LinkedIn Specific
    linkedin_fetch_description = BooleanField('LinkedIn: Fetch Full Description', default=False)
    linkedin_company_ids = StringField('LinkedIn: Company IDs',
                                     render_kw={'placeholder': 'Comma-separated company IDs (e.g., 1441, 2382)'})
    
    # Country for Indeed/Glassdoor
    country_indeed = StringField('Country (Indeed/Glassdoor)', 
                                default='',
                                render_kw={'placeholder': 'e.g., Singapore, United States, United Kingdom'})
    
    # Salary options
    enforce_annual_salary = BooleanField('Convert to Annual Salary', default=False)
    
    # Proxy settings
    proxies = TextAreaField('Proxy List (Optional)',
                          render_kw={'placeholder': 'One proxy per line in format: user:pass@host:port or host:port',
                                   'rows': 3})
    
    user_agent = StringField('Custom User Agent',
                           render_kw={'placeholder': 'Override default user agent (optional)'})
    
    submit = SubmitField('Scrape Jobs')
    
    def __init__(self, *args, **kwargs):
        super(JobScrapingForm, self).__init__(*args, **kwargs)
    
    def get_selected_sites(self):
        """Return list of selected job sites"""
        sites = []
        if self.indeed.data:
            sites.append('indeed')
        if self.linkedin.data:
            sites.append('linkedin')
        if self.glassdoor.data:
            sites.append('glassdoor')
        if self.google.data:
            sites.append('google')
        return sites
    
    def validate(self, extra_validators=None):
        """Custom validation with JobSpy limitations"""
        rv = FlaskForm.validate(self, extra_validators)
        if not rv:
            return False
        
        # Check if at least one job site is selected
        selected_sites = self.get_selected_sites()
        if not selected_sites:
            self.indeed.errors.append('Please select at least one job site.')
            return False
        
        # Indeed limitations validation
        if 'indeed' in selected_sites:
            indeed_exclusive_params = [
                bool(self.hours_old.data and self.hours_old.data != 168),  # non-default hours_old
                bool(self.job_type.data or self.is_remote.data),  # job_type or is_remote
                bool(self.easy_apply.data)  # easy_apply
            ]
            if sum(indeed_exclusive_params) > 1:
                self.hours_old.errors.append('Indeed: Only one of hours_old, job_type/is_remote, or easy_apply can be used.')
                return False
        
        # LinkedIn limitations validation
        if 'linkedin' in selected_sites:
            linkedin_exclusive_params = [
                bool(self.hours_old.data and self.hours_old.data != 168),  # non-default hours_old
                bool(self.easy_apply.data)  # easy_apply
            ]
            if sum(linkedin_exclusive_params) > 1:
                self.hours_old.errors.append('LinkedIn: Only one of hours_old or easy_apply can be used.')
                return False
        
        return True