from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, DecimalField, TextAreaField, SelectField, HiddenField, validators

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