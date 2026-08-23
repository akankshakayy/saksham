
from app.models.domain import OnboardingApplication
from app.tools.validation import validate_application


def test_valid_application():
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
    )
    result = validate_application(app)
    assert result.is_valid is True
    assert len(result.missing_fields) == 0
    assert len(result.invalid_fields) == 0


def test_missing_required_fields():
    app = OnboardingApplication(
        applicant_name=None,
        business_name=None,
        pan_number=None,
        phone=None,
    )
    result = validate_application(app)
    assert result.is_valid is False
    assert "applicant_name" in result.missing_fields
    assert "business_name" in result.missing_fields
    assert "pan_number" in result.missing_fields
    assert "phone" in result.missing_fields


def test_invalid_pan_format():
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="INVALID",
        phone="9876543210",
    )
    result = validate_application(app)
    assert result.is_valid is False
    assert "pan_number" in result.invalid_fields


def test_valid_pan_formats():
    for pan in ["ABCDE1234F", "AAAAA0000A", "ZZZZZ9999Z"]:
        app = OnboardingApplication(
            applicant_name="John Doe",
            business_name="Doe Enterprises",
            pan_number=pan,
            phone="9876543210",
        )
        result = validate_application(app)
        assert result.is_valid is True, f"PAN {pan} should be valid"


def test_invalid_email():
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="not-an-email",
    )
    result = validate_application(app)
    assert result.is_valid is False
    assert "email" in result.invalid_fields


def test_valid_gst():
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
        pan_number="ABCDE1234F",
        gst_number="22AAAAA0000A1Z5",
        phone="9876543210",
    )
    result = validate_application(app)
    assert result.is_valid is True


def test_partial_application():
    app = OnboardingApplication(
        applicant_name="John Doe",
        business_name="Doe Enterprises",
    )
    result = validate_application(app)
    assert result.is_valid is False
    assert "pan_number" in result.missing_fields
    assert "phone" in result.missing_fields
