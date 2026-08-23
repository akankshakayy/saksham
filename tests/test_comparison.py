
from app.models.domain import (
    ExtractedDocumentData,
    OnboardingApplication,
)
from app.tools.comparison import compare_information


def test_perfect_match():
    app = OnboardingApplication(
        applicant_name="John Doe",
        pan_number="ABCDE1234F",
        phone="9876543210",
        email="john@example.com",
        address="123 Main St",
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
                "email": "john@example.com",
                "address": "123 Main St",
            },
            confidence=0.95,
        )
    ]

    result = compare_information(app, extracted)
    assert result.overall_match is True
    assert len(result.inconsistencies) == 0


def test_pan_mismatch():
    app = OnboardingApplication(
        applicant_name="John Doe",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={
                "pan_number": "FFFFF9999F",
                "phone": "9876543210",
            },
            confidence=0.9,
        )
    ]

    result = compare_information(app, extracted)
    assert result.overall_match is False
    assert len(result.inconsistencies) > 0
    assert any("pan_number" in inc for inc in result.inconsistencies)


def test_phone_mismatch():
    app = OnboardingApplication(
        applicant_name="John Doe",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={
                "pan_number": "ABCDE1234F",
                "phone": "1111111111",
            },
            confidence=0.9,
        )
    ]

    result = compare_information(app, extracted)
    assert result.overall_match is False
    assert any("phone" in inc for inc in result.inconsistencies)


def test_no_extracted_data():
    app = OnboardingApplication(
        applicant_name="John Doe",
        pan_number="ABCDE1234F",
        phone="9876543210",
    )

    result = compare_information(app, [])
    assert result.overall_match is True


def test_case_insensitive_comparison():
    app = OnboardingApplication(
        applicant_name="John Doe",
        pan_number="abcde1234f",
        phone="9876543210",
    )
    extracted = [
        ExtractedDocumentData(
            document_id="doc1",
            document_type="pan_card",
            extracted_fields={
                "pan_number": "ABCDE1234F",
                "phone": "9876543210",
            },
            confidence=0.9,
        )
    ]

    result = compare_information(app, extracted)
    assert result.overall_match is True
