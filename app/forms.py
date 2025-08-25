from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, DecimalField, TextAreaField, SelectField, HiddenField, validators, IntegerField, SelectMultipleField, BooleanField
from wtforms import PasswordField

class LoginForm(FlaskForm):
    email = StringField('Email', [validators.DataRequired(), validators.Email()])
    password = PasswordField('Password', [validators.DataRequired()])
    submit = SubmitField('Login')


class SignupForm(FlaskForm):
    username = StringField('Username', [validators.DataRequired()])
    email = StringField('Email', [validators.DataRequired(), validators.Email()])
    password = PasswordField('Password', [validators.DataRequired(), validators.Length(min=6)])
    submit = SubmitField('Sign Up')

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
    
    # No custom validation or site selection logic needed for dropdown