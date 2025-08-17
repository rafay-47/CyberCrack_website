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
    # Job Sites Dropdown
    job_sites = SelectField('Job Sites', 
                           choices=[
                               ('all_platforms', 'All Platforms'),
                               ('indeed', 'Indeed'),
                               ('linkedin', 'LinkedIn'),
                               ('glassdoor', 'Glassdoor'),
                               ('google', 'Google Jobs')
                           ],
                           default='all_platforms',
                           validators=[validators.DataRequired()])
    
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
    
    submit = SubmitField('Scrape Jobs')
    
    def __init__(self, *args, **kwargs):
        super(JobScrapingForm, self).__init__(*args, **kwargs)
    
    def get_selected_sites(self):
        """Return list of selected job sites"""
        if self.job_sites.data == 'all_platforms':
            return ['indeed', 'linkedin', 'glassdoor', 'google']
        else:
            return [self.job_sites.data]
    
    def validate(self, extra_validators=None):
        """Custom validation"""
        rv = FlaskForm.validate(self, extra_validators)
        if not rv:
            return False
        
        # Check if a job site is selected
        if not self.job_sites.data:
            self.job_sites.errors.append('Please select a job site.')
            return False
        
        return True