from mailersend import emails
import os
from dotenv import load_dotenv
load_dotenv()

class EmailService:
    def __init__(self, api_key=''):
        # Set your API key
        self.api_key = os.getenv("MAILERSEND_API_KEY")
        self.default_from_email = os.getenv("MAILERSEND_SENDER_EMAIL")
        self.default_from_name = "CyberCrack Support"
        print(self.api_key, self.default_from_email, self.default_from_name)
    
    def send_email(self, to_email, to_name, subject, text_content, html_content=None, from_email=None, from_name=None):
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

        try:
            response = mailer.send(mail_body)
            print(response)
            return {
                "success": True,
                "response": response
            }
        except Exception as e:
            print(f"Error sending email: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
            
    def send_license_email(self, to_email, to_name, license_key, order_id):
        """
        Send an email containing the license key after successful payment
        """
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

Your license is valid for 30 days from today. If you have any questions or need assistance, please contact our support team.

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
        .button {{ background-color: #00b4d8; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }}
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
            
            <p>If you have any questions or need assistance, please contact our support team.</p>
            
            <p><a href="#" class="button">Download Software</a></p>
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
        Send a contact form email to the support team
        """
        subject = "CyberCrack Contact Form Submission"
        
        # Plain text version of the email
        text_content = f"""
New Contact Form Submission

From: {from_name} ({from_email})

Message:
{message}
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
        .message {{ background-color: #f0f0f0; padding: 15px; margin: 20px 0; }}
        .footer {{ background-color: #f0f0f0; padding: 10px; text-align: center; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>CyberCrack Contact Form</h1>
        </div>
        <div class="content">
            <h2>New Contact Form Submission</h2>
            <p><strong>From:</strong> {from_name} ({from_email})</p>
            
            <h3>Message:</h3>
            <div class="message">
                {message}
            </div>
        </div>
        <div class="footer">
            <p>&copy; 2025 CyberCrack. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""
        
        # Send from our verified sender to our support email
        return self.send_email(
            to_email=self.default_from_email,  # Send to our support email
            to_name=self.default_from_name,    # Send to our support team
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            from_email=from_email,
            from_name=from_name
        )