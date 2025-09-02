import os
import cv2
import numpy as np
import tempfile
from pdf2image import convert_from_bytes

# ------------------ SUBJECT BLOCK PROCESSOR ------------------
def process_subject_block(gray, w, subject, y_start, y_end, x_positions, stars, question_count=20):
    """
    Process a subject block in the OMR sheet to count marked bubbles.
    
    Args:
        gray: Grayscale image of the OMR page.
        w: Width of the image.
        subject: Subject name (e.g., Physics, Maths).
        y_start, y_end: Y-coordinates for the subject block.
        x_positions: X-coordinates for bubble columns.
        stars: List of star ratings (e.g., ["5_star", "3_star", "1_star"]).
        question_count: Number of questions per subject (default: 20).
    
    Returns:
        results: Dictionary with counts for each star rating.
        debug_img: Debug image with marked circles and labels.
    """
    results = {s: 0 for s in stars}
    debug_img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Ensure valid y-coordinates
    y_start = max(0, y_start)
    y_end = min(gray.shape[0], y_end)
    block_gray = gray[y_start:y_end, :]
    
    if block_gray is None or block_gray.size == 0:
        print(f"Warning: Empty block for {subject} (y_start={y_start}, y_end={y_end})")
        return results, debug_img

    block_h = block_gray.shape[0]
    if block_h <= 0 or question_count <= 0:
        print(f"Warning: Invalid block height ({block_h}) or question count ({question_count}) for {subject}")
        return results, debug_img

    # Calculate step size and window for bubble detection
    step = max(1, block_h // question_count)
    window = max(20, step // 2) if subject in ["Physics", "Maths", "Computer"] else max(15, step // 2)

    # Apply adaptive thresholding and morphological operations
    th = cv2.adaptiveThreshold(block_gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                               cv2.THRESH_BINARY_INV, 25, 5)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

    for idx in range(question_count):
        y_q = int((idx + 0.5) * step)
        if y_q - window < 0 or y_q + window >= block_h:
            continue

        detected_star = None
        max_area = 0

        for j, x in enumerate(x_positions):
            x1, x2 = x - window, x + window
            if x1 < 0 or x2 >= w:
                continue

            roi = th[y_q - window:y_q + window, x1:x2]
            if roi is None or roi.size == 0:
                continue

            contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            area_thr = max(5, int(0.02 * (2 * window) * (2 * window)))

            for c in contours:
                a = cv2.contourArea(c)
                if a > area_thr and a > max_area:
                    max_area = a
                    detected_star = j

        if detected_star is not None:
            results[stars[detected_star]] += 1
            cx = x_positions[detected_star]
            cy = y_start + y_q
            cv2.circle(debug_img, (cx, cy), max(6, window // 2), (0, 0, 255), 2)
            cv2.putText(debug_img, f"{subject[:3]}-{stars[detected_star][0]}",
                        (cx + 8, cy - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 255, 0), 1, cv2.LINE_AA)

    return results, debug_img

# ------------------ PDF PARSER ------------------
def parse_omr_pdf_with_subject_blocks(omr_pdf_file, debug_dir="bubble_debug_images"):
    """
    Parse an OMR PDF to count marked bubbles for each subject and calculate pass/fail status.
    
    Args:
        omr_pdf_file: Path to PDF file or file-like object.
        debug_dir: Directory to save debug images.
    
    Returns:
        Dictionary with aggregated counts, percentages, per-form results, and pass/fail status.
    """
    # Subject block y-coordinate fractions
    subject_y_fracs = {
        "Physics":   (0.12, 0.27),
        "Chemistry": (0.28, 0.42),
        "Maths":     (0.43, 0.58),
        "English":   (0.59, 0.74),
        "Computer":  (0.75, 0.94),
    }

    # X-coordinates for bubble columns
    subject_x_positions = {
        "Physics":   [0.28, 0.45, 0.62],
        "Chemistry": [0.27, 0.44, 0.61],
        "Maths":     [0.28, 0.45, 0.62],
        "English":   [0.28, 0.45, 0.62],
        "Computer":  [0.26, 0.44, 0.605],
    }

    stars = ["5_star", "3_star", "1_star"]

    # Ensure debug_dir is a valid string path
    if not isinstance(debug_dir, str):
        debug_dir = "bubble_debug_images"
    os.makedirs(debug_dir, exist_ok=True)

    # Read PDF file
    try:
        if isinstance(omr_pdf_file, str):
            with open(omr_pdf_file, "rb") as f:
                pdf_bytes = f.read()
        else:
            pdf_bytes = omr_pdf_file.read()
    except Exception as e:
        print(f"Error reading PDF file: {e}")
        return {}

    # Convert PDF to images
    try:
        images = convert_from_bytes(pdf_bytes)
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return {}

    aggregated = {sub: {s: 0 for s in stars} for sub in subject_y_fracs}
    per_form, form_counter = [], 0

    for page_idx, pil_img in enumerate(images, start=1):
        # Save PIL image to temporary file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            try:
                pil_img.save(tmp.name, "PNG")
                tmp_path = tmp.name
            except Exception as e:
                print(f"Error saving temporary image for page {page_idx}: {e}")
                continue

        # Read image in grayscale
        page_gray = cv2.imread(tmp_path, cv2.IMREAD_GRAYSCALE)
        if page_gray is None or page_gray.size == 0:
            print(f"Warning: Could not read image for page {page_idx}")
            os.remove(tmp_path)
            continue

        h, w = page_gray.shape[:2]
        form_counts = {}
        debug_img = cv2.cvtColor(page_gray, cv2.COLOR_GRAY2BGR)

        # Process each subject block
        for subject, (f_start, f_end) in subject_y_fracs.items():
            y_start = int(h * f_start)
            y_end = int(h * f_end)
            x_positions = [int(w * xp) for xp in subject_x_positions[subject]]
            counts, dbg = process_subject_block(page_gray, w, subject, y_start, y_end, x_positions, stars, question_count=20)
            form_counts[subject] = counts
            for s in stars:
                aggregated[subject][s] += counts[s]
            debug_img = cv2.addWeighted(debug_img, 0.7, dbg, 0.3, 0)

        # Calculate percentages and pass/fail status
        percentages = {}
        pass_fail = {}
        for sub, cnts in form_counts.items():
            total_marked = sum(cnts.values())
            percentages[sub] = {s: round((cnts[s] / total_marked * 100), 2) if total_marked else 0 for s in stars}
            # Pass if at least 80% of questions (16/20) are marked for Physics, Maths, Computer
            if sub in ["Physics", "Maths", "Computer"]:
                pass_fail[sub] = "Pass" if total_marked >= 16 else f"Fail (only {total_marked}/20 marked)"
            else:
                pass_fail[sub] = "Pass" if total_marked >= 16 else "Fail"

        form_counter += 1
        per_form.append({
            "form_number": form_counter,
            "star_counts": form_counts,
            "percentages": percentages,
            "pass_fail": pass_fail
        })

        # Save debug image
        debug_path = os.path.join(debug_dir, f"page{page_idx}_form{form_counter}.png")
        cv2.imwrite(debug_path, debug_img)
        os.remove(tmp_path)

    # Calculate aggregated percentages and pass/fail
    aggregated_percentages = {}
    aggregated_pass_fail = {}
    for sub, counts in aggregated.items():
        total = sum(counts.values())
        total_questions = 20 * form_counter
        marked_percentage = round((total / total_questions * 100), 2) if total_questions else 0
        aggregated_percentages[sub] = {
            "star_percentages": {s: round((counts[s] / total * 100), 2) if total else 0 for s in stars},
            "total_marked_percentage": marked_percentage
        }
        # For Physics, Maths, Computer: Pass only if >= 80% questions marked
        if sub in ["Physics", "Maths", "Computer"]:
            aggregated_pass_fail[sub] = "Pass" if total >= 16 * form_counter else f"Fail (only {total}/{total_questions} marked, {marked_percentage}%)"
        else:
            aggregated_pass_fail[sub] = "Pass" if total >= 16 * form_counter else "Fail"

    return {
        "aggregated": aggregated,
        "percentages": aggregated_percentages,
        "per_form": per_form,
        "aggregated_pass_fail": aggregated_pass_fail
    }
    

