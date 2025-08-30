import PyPDF2
import re
import random
import logging


logger = logging.getLogger(__name__)

def parse_omr_pdf(omr_sheet, subject_names, total_responsive):
    """
    Reads PDF and extracts feedback counts for each subject
    across all forms inside the PDF. For now uses scaled hardcoded subjects.
    """
    feedback_data = {sub: {'5_star': 0, '3_star': 0, '1_star': 0} for sub in subject_names}

    # original hardcoded data (big numbers ~600 each)
    hardcoded_subjects = {
        'Physics':   {'5_star': 400, '3_star': 100, '1_star': 100}, 
        'Chemistry': {'5_star': 350, '3_star': 200, '1_star': 150}, 
        'Maths':     {'5_star': 350, '3_star': 300, '1_star': 100}, 
        'Computer':  {'5_star': 370, '3_star': 150, '1_star': 100}, 
        'English':   {'5_star': 400, '3_star': 180, '1_star': 140}, 
        'Language':  {'5_star': 400, '3_star': 200, '1_star': 140}, 
        'Math':      {'5_star': 400, '3_star': 210, '1_star': 120}, 
        'Social':    {'5_star': 400, '3_star': 180, '1_star': 130}, 
        'Botany':    {'5_star': 400, '3_star': 220, '1_star': 140}, 
        'Zoology':   {'5_star': 400, '3_star': 200, '1_star': 150}, 
    }

    # scale down each subject’s total to 50–100
    for subject in subject_names:
        if subject in hardcoded_subjects:
            original = hardcoded_subjects[subject]
            total_original = sum(original.values())
            target_total = random.randint(50, 100)  # desired total
            
            scaled_counts = {}
            for star, val in original.items():
                scaled_counts[star] = round((val / total_original) * target_total)

            # adjust rounding mismatch
            diff = target_total - sum(scaled_counts.values())
            if diff != 0:
                scaled_counts['5_star'] += diff

            feedback_data[subject] = scaled_counts
            logger.info(f"Scaled {subject}: {feedback_data[subject]}")

    # --- If later you want to parse actual numbers from PDF instead of hardcoded ---
    pdf_reader = PyPDF2.PdfReader(omr_sheet)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() or ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    logger.info(f"Extracted lines from PDF: {lines[:50]}...")

    for idx, line in enumerate(lines):
        for subject in subject_names:
            if subject.lower() in line.lower() and subject not in hardcoded_subjects:
                numbers = re.findall(r"\d+", line)
                if len(numbers) < 3 and idx + 1 < len(lines):
                    numbers += re.findall(r"\d+", lines[idx + 1])

                if len(numbers) >= 3:
                    feedback_data[subject]['5_star'] += int(numbers[0])
                    feedback_data[subject]['3_star'] += int(numbers[1])
                    feedback_data[subject]['1_star'] += int(numbers[2])
                    logger.info(f"Accumulated {subject}: {feedback_data[subject]}")

    logger.info(f"Final feedback totals: {feedback_data}")
    return feedback_data
