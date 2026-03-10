"""Quick test for PDF and DOCX export functions."""
import sys, os, io
sys.path.insert(0, os.path.dirname(__file__))

from agents.analysis_agent import VisaReport, DocumentItem

mock = VisaReport(
    visa_type="UK Standard Visitor Visa",
    applicant_nationality="Filipino",
    country_of_residence="Singapore",
    destination_country="United Kingdom",
    purpose_of_visit="Tourism",
    schengen_main_country=None,
    fee="£115 per adult",
    processing_time="15 working days (standard)",
    max_stay="Up to 6 months",
    apply_url="https://www.gov.uk/standard-visitor/apply-standard-visitor-visa",
    mandatory_documents=[
        DocumentItem(id=1, document="Valid Passport", details="Must be valid for the duration of your stay.", mandatory=True),
        DocumentItem(id=2, document="Bank Statements", details="Last 3 months showing sufficient funds.", mandatory=True),
    ],
    optional_documents=[
        DocumentItem(id=3, document="Travel Insurance", details="Recommended but not mandatory.", mandatory=False),
    ],
    application_steps=[
        "Step 1: Create a UKVI account at gov.uk",
        "Step 2: Complete the online application form",
        "Step 3: Pay the visa fee",
        "Step 4: Book a biometric appointment",
    ],
    key_notes=["Ensure all documents are translated into English."],
    supplementary_notes=["Filipino nationals have a moderate visa approval rate."],
    sources=[{"title": "UK Visas and Immigration", "url": "https://www.gov.uk/standard-visitor"}],
    embassy_guidance=None,
    eta_eligible=False,
    eta_note=None,
    executive_summary="Filipino nationals residing in Singapore require a Standard Visitor Visa to enter the UK.",
)

# Test PDF
from app import _build_pdf, _build_docx
pdf = _build_pdf(mock)
assert len(pdf) > 1000, "PDF too small"
print(f"PDF OK — {len(pdf):,} bytes")

# Test DOCX
docx = _build_docx(mock)
assert len(docx) > 1000, "DOCX too small"
print(f"DOCX OK — {len(docx):,} bytes")

print("All export tests passed!")
