from mailersend import emails
import os
import re
from dotenv import load_dotenv
from email_validator import validate_email, EmailNotValidError
load_dotenv()

class EmailService:
    def __init__(self, api_key=''):
        # Set your API key
        self.api_key = os.getenv("MAILERSEND_API_KEY")
        self.default_from_email = os.getenv("MAILERSEND_SENDER_EMAIL")
        self.default_from_name = "CyberCrack Support"
        #print(self.api_key, self.default_from_email, self.default_from_name)
    
    def validate_email(self, email):
        """
        Validate email address format
        """
        # Basic email regex pattern
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        
        if not email or not isinstance(email, str):
            return False, "Email address is required"
        
        if not re.match(pattern, email):
            return False, "Invalid email format"
        
        # Additional checks
        if len(email) > 254:  # RFC 5321 limit
            return False, "Email address too long"
        
        # Check for common typos in domains
        common_domains = {
            'gmail.co': 'gmail.com',
            'gmail.cm': 'gmail.com',
            'yahooo.com': 'yahoo.com',
            'hotmial.com': 'hotmail.com',
            'gmial.com': 'gmail.com'
        }
        
        domain = email.split('@')[-1].lower()
        if domain in common_domains:
            return False, f"Did you mean {email.replace(domain, common_domains[domain])}?"
        
        return True, "Valid email"

    def validate_email_with_library(self, email):
        """
        Validate email using email-validator library
        """
        try:
            # Validate and get info about the email
            validation = validate_email(
                email,
                check_deliverability=True  # This checks if the domain can receive email
            )
            
            # The validated email address
            valid_email = validation.email
            
            return True, f"Valid email: {valid_email}"
            
        except EmailNotValidError as e:
            return False, str(e)

    def send_email(self, to_email, to_name, subject, text_content, html_content=None, from_email=None, from_name=None, reply_to=None):
        """
        Send an email using MailerSend
        """
        # Set default sender values if not provided
        from_email = from_email or self.default_from_email
        from_name = from_name or self.default_from_name

        mailer = emails.NewEmail(self.api_key)
        mail_body = {}

        # Required
        mailer.set_mail_from({"email": from_email, "name": from_name}, mail_body)
        mailer.set_mail_to([{"email": to_email, "name": to_name}], mail_body)
        mailer.set_subject(subject, mail_body)
        mailer.set_plaintext_content(text_content, mail_body)

        # Optional
        if html_content:
            mailer.set_html_content(html_content, mail_body)
        
        # Set reply-to if provided
        if reply_to:
            mailer.set_reply_to(reply_to, mail_body)

        try:
            response = mailer.send(mail_body)
            #print(response)
            return {
                "success": True,
                "response": response
            }
        except Exception as e:
            #print(f"Error sending email: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def send_license_email(self, to_email, to_name, license_key, order_id):
        """
        Send an email containing the license key after successful payment
        """
        # Validate email before sending
        is_valid, message = self.validate_email(to_email)
        if not is_valid:
            return {
                "success": False,
                "error": f"Email validation failed: {message}"
            }
        
        subject = "Your CyberCrack License Key"
        
        # Plain text version of the email
        text_content = f"""
Hello {to_name},

Thank you for purchasing CyberCrack! Your license key is ready.

License Key: {license_key}
Order ID: {order_id}

Installation Instructions:
1. Download the CyberCrack software from our website
2. Run the installer and follow the on-screen instructions
3. When prompted, enter your license key

Your license is valid for 30 days from today. If you have any questions or need assistance, please contact our support team at cybercrack@sbmtechpro.com.

Visit our website to download the software: https://getcybercrack.com/

Thank you for choosing CyberCrack!

Best regards,
The CyberCrack Team
"""
        
        # HTML version of the email
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #00b4d8; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; }}
        .license-key {{ background-color: #f0f0f0; padding: 15px; margin: 20px 0; font-family: monospace; font-size: 16px; word-break: break-all; }}
        .footer {{ background-color: #f0f0f0; padding: 10px; text-align: center; font-size: 12px; }}
        .button {{ 
            background-color: #00b4d8; 
            color: white; 
            padding: 12px 24px; 
            text-decoration: none; 
            border-radius: 5px; 
            display: inline-block;
            font-weight: bold;
            margin: 10px 0;
        }}
        .button:hover {{ background-color: #0099b8; }}
        .support-link {{ 
            color: #00b4d8; 
            text-decoration: none; 
            font-weight: bold;
        }}
        .support-link:hover {{ text-decoration: underline; }}
        .contact-section {{ 
            background-color: #f8f9fa; 
            padding: 15px; 
            margin: 20px 0; 
            border-radius: 5px; 
            border-left: 4px solid #00b4d8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>CyberCrack License Key</h1>
        </div>
        <div class="content">
            <h2>Hello {to_name},</h2>
            <p>Thank you for purchasing CyberCrack! Your license key is ready.</p>
            
            <h3>Your License Details</h3>
            <p><strong>Order ID:</strong> {order_id}</p>
            <div class="license-key">
                {license_key}
            </div>
            
            <h3>Installation Instructions:</h3>
            <ol>
                <li>Download the CyberCrack software from our website</li>
                <li>Run the installer and follow the on-screen instructions</li>
                <li>When prompted, enter your license key</li>
            </ol>
            
            <p>Your license is valid for 30 days from today.</p>
            
            <div class="contact-section">
                <p>If you have any questions or need assistance, please contact our support team at <a href="mailto:cybercrack@sbmtechpro.com" class="support-link">cybercrack@sbmtechpro.com</a>.</p>
            </div>
            
            <div style="text-align: center; margin: 20px 0;">
                <a href="https://getcybercrack.com/" class="button">Download Software</a>
            </div>
        </div>
        <div class="footer">
            <p>Thank you for choosing CyberCrack!</p>
            <p>&copy; 2025 CyberCrack. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""
        
        return self.send_email(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            text_content=text_content,
            html_content=html_content
        )
    
    def send_contact_email(self, from_email, from_name, message):
        """
        Send a contact form email to the support team using the inbound route
        """
        subject = f"CyberCrack Contact Form - {from_name}"
        
        # Plain text version of the email
        text_content = f"""
New Contact Form Submission from CyberCrack Website

From: {from_name}
Email: {from_email}

Message:
{message}

---
This email was sent from the CyberCrack contact form.
Reply directly to this email to respond to the customer.
"""
        
        # HTML version of the email
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #00b4d8; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; }}
        .contact-info {{ background-color: #f8f9fa; padding: 15px; margin: 20px 0; border-left: 4px solid #00b4d8; }}
        .message {{ background-color: #f0f0f0; padding: 15px; margin: 20px 0; border-radius: 5px; }}
        .footer {{ background-color: #f0f0f0; padding: 10px; text-align: center; font-size: 12px; color: #666; }}
        .reply-info {{ background-color: #e8f4fd; padding: 10px; margin: 20px 0; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>CyberCrack Contact Form</h1>
        </div>
        <div class="content">
            <h2>New Contact Form Submission</h2>
            
            <div class="contact-info">
                <h3>Customer Information</h3>
                <p><strong>Name:</strong> {from_name}</p>
                <p><strong>Email:</strong> {from_email}</p>
            </div>
            
            <h3>Message:</h3>
            <div class="message">
                {message.replace(chr(10), '<br>')}
            </div>
            
            <div class="reply-info">
                <p><strong>Note:</strong> Reply directly to this email to respond to the customer.</p>
            </div>
        </div>
        <div class="footer">
            <p>This email was sent from the CyberCrack contact form</p>
            <p>© 2025 CyberCrack. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Use the correct inbound email address from the configuration
        inbound_email = os.getenv("MAILERSEND_INBOUND_EMAIL")
        
        # Set reply-to to the customer's email
        reply_to = {"email": from_email, "name": from_name}
        
        return self.send_email(
            to_email=inbound_email,  # Send to inbound route
            to_name="CyberCrack Support",
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            reply_to=reply_to
        )