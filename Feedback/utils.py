import os
import cv2
import numpy as np
import fitz  # PyMuPDF

# ------------------ SUBJECT BLOCK PROCESSOR ------------------
def process_subject_block(
    gray, subject, y_start, y_end, x_positions, stars,
    expected_questions=20, area_boost=1.0, min_area=25
):
    results = {s: 0 for s in stars}
    debug_img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    y_start, y_end = max(0, y_start), min(gray.shape[0], y_end)
    block_gray = gray[y_start:y_end, :]
    if block_gray is None or block_gray.size == 0:
        return results, debug_img

    block_h = block_gray.shape[0]
    step = block_h // expected_questions if expected_questions > 0 else 1
    window = max(15, step // 2)

    # Normalize contrast
    block_gray = cv2.equalizeHist(block_gray)

    # Dual thresholding
    _, otsu = cv2.threshold(block_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    adp = cv2.adaptiveThreshold(block_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 31, 7)
    th = cv2.bitwise_or(otsu, adp)
    th = cv2.medianBlur(th, 3)

    # Extra boost for Computer: morphological close to merge faint marks
    if subject == "Computer":
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)

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
                a = cv2.contourArea(c) * area_boost

                # Subject-specific thresholds
                if subject == "Computer":
                    local_min_area = 18
                elif subject == "English":
                    local_min_area = 20
                else:
                    local_min_area = min_area

                if a > local_min_area and a > max_area:
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


# ------------------ PDF OR IMAGE READER (NO POPPLER) ------------------
def load_images(input_file: str) -> list:
    images = []
    if input_file.lower().endswith(".pdf"):
        try:
            pdf = fitz.open(input_file)
            for page_num in range(len(pdf)):
                page = pdf.load_page(page_num)
                pix = page.get_pixmap(dpi=300)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:  # RGBA → RGB
                    img = cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
                gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                images.append(gray)
        except Exception as e:
            print(f"[ERROR] Could not load PDF: {e}")
    else:
        img = cv2.imread(input_file, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            images.append(img)
        else:
            print(f"[ERROR] Could not load image: {input_file}")
    return images


# ------------------ MAIN PARSER ------------------
def parse_omr(input_file, debug_dir="bubble_debug_images", expected_questions=20):
    # Adjusted subject Y ranges
    subject_y_fracs = {
        "Physics":   (0.12, 0.27),
        "Chemistry": (0.28, 0.42),
        "Maths":     (0.43, 0.58),
        "English":   (0.59, 0.70),
        "Computer":  (0.71, 0.96),
    }

    subject_x_positions = {
        "Physics":   [0.28, 0.45, 0.62],
        "Chemistry": [0.27, 0.44, 0.61],
        "Maths":     [0.28, 0.45, 0.62],
        "English":   [0.28, 0.45, 0.62],
        "Computer":  [0.26, 0.45, 0.61],
    }

    subject_boosts = {
        "Physics": 1.0,
        "Chemistry": 1.0,
        "Maths": 1.0,
        "English": 1.0,   # 🔥 more sensitive
        "Computer": 1.0,  # 🔥 stronger boost
    }

    stars = ["5_star", "3_star", "1_star"]
    star_values = {"5_star": 5, "3_star": 3, "1_star": 1}
    os.makedirs(debug_dir, exist_ok=True)

    images = load_images(input_file)
    if not images:
        print(f"[ERROR] No images loaded from {input_file}")
        return [], {}, {}

    aggregated = {sub: {s: 0 for s in stars} for sub in subject_y_fracs}
    per_form = []

    for idx, page_gray in enumerate(images, start=1):
        h, w = page_gray.shape[:2]
        debug_img = cv2.cvtColor(page_gray, cv2.COLOR_GRAY2BGR)
        form_counts = {}

        for subject, (f_start, f_end) in subject_y_fracs.items():
            y_start = int(h * f_start)
            y_end = int(h * f_end)
            x_positions = [int(w * xp) for xp in subject_x_positions[subject]]

            counts, dbg = process_subject_block(
                page_gray, subject, y_start, y_end, x_positions,
                stars, expected_questions=expected_questions,
                area_boost=subject_boosts.get(subject, 1.0)
            )
            form_counts[subject] = counts
            for s in stars:
                aggregated[subject][s] += counts[s]

            debug_img = cv2.addWeighted(debug_img, 0.7, dbg, 0.3, 0)

            # Show raw count directly above each subject block
            total_count = sum(counts.values())
            y_text = max(30, y_start - 15)
            cv2.putText(debug_img, f"{subject} Count: {total_count}",
                        (50, y_text),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)

        per_form.append({"page_number": idx, "star_counts": form_counts})

        # ------------------ Show Percentages ------------------
        total_responses = len(per_form)
        for subject, (f_start, f_end) in subject_y_fracs.items():
            total_score = sum(aggregated[subject][s] * star_values[s] for s in stars)
            max_score = total_responses * expected_questions * 5
            raw_percent = (total_score / max_score) * 100 if max_score > 0 else 0

            text = f"{subject}: {raw_percent:.2f}%"
            y_text = max(50, int(h * f_start) - 40)
            cv2.putText(debug_img, text, (50, y_text),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2, cv2.LINE_AA)

        cv2.imwrite(os.path.join(debug_dir, f"debug_page{idx}.png"), debug_img)

    # ------------------ Final Yes/No ------------------
    results = {}
    total_responses = len(per_form)
    for subject, star_counts in aggregated.items():
        total_score = sum(star_counts[s] * star_values[s] for s in stars)
        max_score = total_responses * expected_questions * 5
        raw_percent = (total_score / max_score) * 100 if max_score > 0 else 0

        results[subject] = "Yes" if raw_percent >= 80 else "No"

    return per_form, aggregated, results


# ------------------ EXAMPLE RUN ------------------
if __name__ == "__main__":
    pdf_path = r"C:\Users\KAYAL\Documents\Github-2\feedback\uploads\Class12A1.pdf"
    forms, aggregated, results = parse_omr(pdf_path)

    print("Per Form:", forms)
    print("Aggregated:", aggregated)
    print("Results:", results)
