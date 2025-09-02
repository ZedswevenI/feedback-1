import os
import cv2
import numpy as np
import tempfile
from pdf2image import convert_from_bytes

# ------------------ SUBJECT BLOCK PROCESSOR ------------------
def process_subject_block(gray, subject, y_start, y_end, x_positions, stars, expected_questions=20):
    results = {s: 0 for s in stars}
    debug_img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    y_start, y_end = max(0, y_start), min(gray.shape[0], y_end)
    block_gray = gray[y_start:y_end, :]
    if block_gray is None or block_gray.size == 0:
        return results, debug_img

    block_h = block_gray.shape[0]
    step = block_h // expected_questions if expected_questions > 0 else 1
    window = max(20, step // 2)

    # Normalize contrast
    block_gray = cv2.equalizeHist(block_gray)

    # Dual thresholding (Otsu + Adaptive)
    _, otsu = cv2.threshold(block_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adp = cv2.adaptiveThreshold(block_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 31, 7)
    th = cv2.bitwise_or(otsu, adp)
    th = cv2.medianBlur(th, 3)

    # Process each row (bubble line)
    for idx in range(expected_questions):
        y_q = int((idx + 0.5) * step)
        if y_q - window < 0 or y_q + window >= block_h:
            continue

        detected_star, max_area = None, 0
        for j, x in enumerate(x_positions):
            x1, x2 = x - window, x + window
            roi = th[y_q - window:y_q + window, x1:x2]
            if roi is None or roi.size == 0:
                continue

            contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                a = cv2.contourArea(c)
                if a > 10 and a > max_area:  # lower threshold
                    max_area = a
                    detected_star = j

        if detected_star is not None:
            results[stars[detected_star]] += 1
            cx, cy = x_positions[detected_star], y_start + y_q
            cv2.circle(debug_img, (cx, cy), 6, (0, 0, 255), 2)
            cv2.putText(debug_img, f"{subject[:3]}-{stars[detected_star][0]}",
                        (cx + 8, cy - 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 255, 0), 1, cv2.LINE_AA)

    return results, debug_img


# ------------------ FORM SPLITTER ------------------
def split_page_into_forms(page_gray, expected_forms=2):
    """Split a page vertically into multiple forms by intensity projection"""
    h, w = page_gray.shape[:2]
    proj = np.sum(255 - page_gray, axis=1)  # horizontal projection
    proj_smooth = cv2.blur(proj.astype(np.float32).reshape(-1, 1), (50, 1)).ravel()

    # Find valleys in projection (likely gaps between forms)
    thresh = np.percentile(proj_smooth, 30)
    form_boundaries = []
    inside = False
    for y, val in enumerate(proj_smooth):
        if val > thresh and not inside:
            start = y
            inside = True
        elif val <= thresh and inside:
            form_boundaries.append((start, y))
            inside = False
    if inside:
        form_boundaries.append((start, h))

    # If auto-detection fails, fall back to equal-splits
    if len(form_boundaries) < expected_forms:
        step = h // expected_forms
        form_boundaries = [(i * step, (i + 1) * step) for i in range(expected_forms)]

    return form_boundaries


# ------------------ PDF PARSER ------------------
def parse_omr_pdf_with_subject_blocks(omr_pdf_file, debug_dir="bubble_debug_images"):
    subject_y_fracs = {
        "Physics":   (0.12, 0.27),
        "Chemistry": (0.28, 0.42),
        "Maths":     (0.43, 0.58),
        "English":   (0.59, 0.74),
        "Computer":  (0.75, 0.94),
    }

    subject_x_positions = {
        "Physics":   [0.28, 0.45, 0.62],
        "Chemistry": [0.27, 0.44, 0.61],
        "Maths":     [0.28, 0.45, 0.62],
        "English":   [0.28, 0.45, 0.62],
        "Computer":  [0.26, 0.44, 0.605],
    }

    stars = ["5_star", "3_star", "1_star"]
    star_values = {"5_star": 5, "3_star": 3, "1_star": 1}
    os.makedirs(debug_dir, exist_ok=True)

    if isinstance(omr_pdf_file, str):
        with open(omr_pdf_file, "rb") as f:
            pdf_bytes = f.read()
    else:
        pdf_bytes = omr_pdf_file.read()

    images = convert_from_bytes(pdf_bytes)
    aggregated = {sub: {s: 0 for s in stars} for sub in subject_y_fracs}
    per_form, form_counter = [], 0

    for page_idx, pil_img in enumerate(images, start=1):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pil_img.save(tmp.name, "PNG")
            tmp_path = tmp.name

        page_gray = cv2.imread(tmp_path, cv2.IMREAD_GRAYSCALE)
        h, w = page_gray.shape[:2]
        os.remove(tmp_path)

        # --- split page into multiple forms ---
        form_boundaries = split_page_into_forms(page_gray, expected_forms=2)  # adjust if more forms/page

        for form_idx, (y_start_form, y_end_form) in enumerate(form_boundaries, start=1):
            form_gray = page_gray[y_start_form:y_end_form, :]
            debug_img = cv2.cvtColor(form_gray, cv2.COLOR_GRAY2BGR)
            form_counts = {}

            for subject, (f_start, f_end) in subject_y_fracs.items():
                y_start = int(form_gray.shape[0] * f_start)
                y_end = int(form_gray.shape[0] * f_end)
                x_positions = [int(w * xp) for xp in subject_x_positions[subject]]

                counts, dbg = process_subject_block(form_gray, subject, y_start, y_end,
                                                    x_positions, stars, expected_questions=20)
                form_counts[subject] = counts
                for s in stars:
                    aggregated[subject][s] += counts[s]

                debug_img = cv2.addWeighted(debug_img, 0.7, dbg, 0.3, 0)

            form_counter += 1
            per_form.append({"form_number": form_counter, "star_counts": form_counts})

            cv2.imwrite(os.path.join(debug_dir, f"page{page_idx}_form{form_idx}.png"), debug_img)

    # ------------------ Calculate percentages ------------------
    percentages = {}
    for subject, star_counts in aggregated.items():
        total_score = sum(star_counts[s] * star_values[s] for s in stars)
        max_score = 20 * 5   # 20 questions * max 5 points each
        percent = (total_score / max_score) * 100 if max_score > 0 else 0
        percentages[subject] = round(percent, 2)

    filtered = {sub: pct for sub, pct in percentages.items() if pct >= 75}

    return {
        "aggregated": aggregated,
        "percentages": percentages,
        "filtered_above_75": filtered,
        "per_form": per_form
    }
