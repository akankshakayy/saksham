"""Create synthetic test document images for testing.

These are synthetic images with text rendered onto them to simulate
PAN cards and GST certificates for testing purposes only.
"""
import os
from PIL import Image, ImageDraw, ImageFont


def create_synthetic_pan_card(output_path: str) -> str:
    """Create a synthetic PAN card-like image with test data."""
    img = Image.new("RGB", (800, 400), "white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_large = font

    # Header
    draw.text((50, 30), "INCOME TAX DEPARTMENT", fill="black", font=font_large)
    draw.text((50, 60), "GOVERNMENT OF INDIA", fill="black", font=font)

    # PAN details
    draw.text((50, 120), "Permanent Account Number Card", fill="black", font=font)
    draw.text((50, 160), "Name: SAKSHAM TEST PVT LTD", fill="black", font=font)
    draw.text((50, 200), "Date of Birth: 15/01/1990", fill="black", font=font)
    draw.text((50, 240), "PAN: ABCDE1234F", fill="black", font=font_large)

    # Father's name
    draw.text((50, 300), "Father's Name: TEST PERSON", fill="black", font=font)

    img.save(output_path, "PNG")
    return output_path


def create_synthetic_gst_certificate(output_path: str) -> str:
    """Create a synthetic GST certificate-like image with test data."""
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_large = font

    # Header
    draw.text((50, 30), "GOODS AND SERVICES TAX", fill="black", font=font_large)
    draw.text((50, 60), "GST REGISTRATION CERTIFICATE", fill="black", font=font_large)

    # GST details
    draw.text((50, 120), "Legal Name of Business: SAKSHAM TEST ENTERPRISES", fill="black", font=font)
    draw.text((50, 160), "Trade Name: SAKSHAM TEST", fill="black", font=font)
    draw.text((50, 200), "GSTIN: 27AABCT1234D1Z5", fill="black", font=font_large)
    draw.text((50, 240), "PAN: AABCT1234D", fill="black", font=font)

    # Address
    draw.text((50, 300), "Principal Place of Business:", fill="black", font=font)
    draw.text((50, 330), "123 Test Street, Mumbai", fill="black", font=font)
    draw.text((50, 360), "Maharashtra, 400001", fill="black", font=font)

    # Contact
    draw.text((50, 420), "Phone: 9876543210", fill="black", font=font)
    draw.text((50, 450), "Email: test@saksham.com", fill="black", font=font)

    img.save(output_path, "PNG")
    return output_path


def create_synthetic_image_with_text(output_path: str, text: str, width: int = 800, height: int = 400) -> str:
    """Create a simple image with custom text for testing."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except (OSError, IOError):
        font = ImageFont.load_default()

    y = 30
    for line in text.split("\n"):
        draw.text((50, y), line, fill="black", font=font)
        y += 30

    img.save(output_path, "PNG")
    return output_path


if __name__ == "__main__":
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)

    pan_path = os.path.join(fixtures_dir, "synthetic_pan_card.png")
    create_synthetic_pan_card(pan_path)
    print(f"Created: {pan_path}")

    gst_path = os.path.join(fixtures_dir, "synthetic_gst_certificate.png")
    create_synthetic_gst_certificate(gst_path)
    print(f"Created: {gst_path}")
