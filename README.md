# Flask Download Site

## Overview
This project is a web application built using Flask that allows users to download a Windows executable (.exe) file and purchase a license for it. The application includes features for license management and payment processing.

## Project Structure
```
flask-download-site
├── app
│   ├── __init__.py
│   ├── routes.py
│   ├── models.py
│   ├── forms.py
│   ├── static
│   │   ├── css
│   │   │   ├── main.css
│   │   │   └── styles.css
│   │   ├── js
│   │   │   ├── main.js
│   │   │   └── payment.js
│   │   └── downloads
│   │       └── .gitkeep
│   └── templates
│       ├── base.html
│       ├── index.html
│       ├── download.html
│       ├── purchase.html
│       └── license.html
├── config.py
├── requirements.txt
├── run.py
└── README.md
```

## Setup Instructions
1. **Clone the repository:**
   ```
   git clone <repository-url>
   cd flask-download-site
   ```

2. **Create a virtual environment:**
   ```
   python -m venv venv
   ```

3. **Activate the virtual environment:**
   - On Windows:
     ```
     venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```
     source venv/bin/activate
     ```

4. **Install the required dependencies:**
   ```
   pip install -r requirements.txt
   ```

5. **Configure the application:**
   Update `config.py` with your database connection details and secret keys.

6. **Run the application:**
   ```
   python run.py
   ```

## Usage
- Navigate to `http://localhost:5000` to access the homepage.
- Use the navigation links to download the .exe file or purchase a license.
- Follow the instructions on the respective pages for downloading and payment processing.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.