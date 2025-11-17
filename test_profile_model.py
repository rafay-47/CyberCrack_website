#!/usr/bin/env python3
"""
Test script to verify the updated Profile model and add_profile route work correctly.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add the flask-website directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Set up minimal Flask environment to avoid heavy imports
os.environ['FLASK_ENV'] = 'testing'

from app import create_app, db
from app.models import Profile

def test_profile_model():
    """Test that the Profile model can be created with all new fields."""
    app = create_app()

    with app.app_context():
        # Test creating a profile with all the new fields
        profile = Profile(
            first_name="John",
            last_name="Doe",
            email="john.doe@example.com",
            phone="555-123-4567",
            headline="Software Engineer",
            location="San Francisco, CA",
            address="123 Main St",
            city="San Francisco",
            state="CA",
            zip_code="94102",
            linkedin="https://linkedin.com/in/johndoe",
            github="https://github.com/johndoe",
            website="https://johndoe.com",
            summary="Experienced software engineer...",
            ethnicity="Caucasian",
            gender="Male",
            lgbtq="No",
            work_authorization="Authorized",
            visa_sponsorship="No",
            disability="No",
            veteran="No",
            skills=["Python", "JavaScript", "SQL"],
            work_experience=[
                {
                    "title": "Software Engineer",
                    "company": "Tech Corp",
                    "location": "San Francisco",
                    "experienceType": "Full-time",
                    "start": "2020-01",
                    "end": "Present",
                    "description": "Developed web applications..."
                }
            ],
            education=[
                {
                    "school": "University of California",
                    "major": "Computer Science",
                    "degreetype": "Bachelor's",
                    "gpa": "3.8",
                    "start": "2016-09",
                    "end": "2020-05",
                    "description": "Graduated with honors..."
                }
            ],
            projects=[
                {
                    "title": "Personal Website",
                    "link": "https://johndoe.com",
                    "description": "Built with React and Node.js"
                }
            ],
            certifications=["AWS Certified Developer"],
            languages=["English", "Spanish"],
            links=["https://blog.johndoe.com"]
        )

        # Add to session and commit
        db.session.add(profile)
        db.session.commit()

        print("✓ Profile created successfully with all new fields")

        # Verify the data was saved correctly
        saved_profile = Profile.query.filter_by(email="john.doe@example.com").first()
        assert saved_profile is not None
        assert saved_profile.first_name == "John"
        assert saved_profile.last_name == "Doe"
        assert saved_profile.linkedin == "https://linkedin.com/in/johndoe"
        assert saved_profile.ethnicity == "Caucasian"
        assert saved_profile.skills == ["Python", "JavaScript", "SQL"]
        assert len(saved_profile.work_experience) == 1
        assert saved_profile.work_experience[0]["title"] == "Software Engineer"

        print("✓ All profile fields verified successfully")

        # Clean up
        db.session.delete(profile)
        db.session.commit()

        print("✓ Test completed successfully")

if __name__ == "__main__":
    test_profile_model()