"""Build tests/fixtures/bulletin_sample.pdf, a synthetic bulletin laid out like the State Department PDF.

The dates are made up. Run with: python tests/make_sample_pdf.py (needs reportlab).
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from sample_data import DF_EMP, DF_FAM, EMP_HEADER, FA_EMP, FA_FAM, FAM_HEADER

styles = getSampleStyleSheet()
small = styles["BodyText"]


def table(header, rows):
    data = [[Paragraph(h, small) for h in header]] + [[Paragraph(r[0], small)] + r[1:] for r in rows]
    return Table(data, colWidths=[110, 110, 70, 60, 60, 80])


def build(path):
    story = [Paragraph("Visa Bulletin For December 2026", styles["Title"]),
             Paragraph("Number 99 Volume XI Washington, D.C", small),
             Paragraph("A. STATUTORY NUMBERS. Applicants should use the Final Action Dates chart unless "
                       "USCIS indicates otherwise. 1. FAMILY-SPONSORED PREFERENCES", small), Spacer(1, 8),
             Paragraph("A. FINAL ACTION DATES FOR FAMILY-SPONSORED PREFERENCE CASES", styles["Heading4"]),
             Paragraph("On the chart below, the listed date for each qualified category is the final action date.",
                       small), table(FAM_HEADER, FA_FAM), Spacer(1, 8),
             Paragraph("B. DATES FOR FILING FAMILY-SPONSORED VISA APPLICATIONS", styles["Heading4"]),
             Paragraph("The chart below reflects dates for filing visa applications within a timeframe justifying "
                       "immediate action. Visit www.uscis.gov/visabulletininfo.", small),
             table(FAM_HEADER, DF_FAM), Spacer(1, 8),
             Paragraph("A. FINAL ACTION DATES FOR EMPLOYMENT-BASED PREFERENCE CASES", styles["Heading4"]),
             table(EMP_HEADER, FA_EMP), Spacer(1, 8),
             Paragraph("B. DATES FOR FILING OF EMPLOYMENT-BASED VISA APPLICATIONS", styles["Heading4"]),
             table(EMP_HEADER, DF_EMP), Spacer(1, 8),
             Paragraph("C. THE DIVERSITY (DV) IMMIGRANT CATEGORY. Region: AFRICA 45,000", small)]
    SimpleDocTemplate(str(path), pagesize=letter).build(story)


if __name__ == "__main__":
    build(Path(__file__).parent / "fixtures" / "bulletin_sample.pdf")
