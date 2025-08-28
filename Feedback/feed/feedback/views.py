import logging
import re
import json
from django.http import JsonResponse
import PyPDF2
from .utils import parse_omr_pdf
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django import forms
from .models import Batch, Subject, Teacher, Performance
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone

logger = logging.getLogger(__name__)

# ------------------ Filter Form ------------------
class FilterForm(forms.Form):
    from_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    to_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    keyword = forms.CharField(required=False, max_length=100)
    mode = forms.ChoiceField(
        choices=[
            ('individual', 'Individual Teacher'),
            ('multiple', 'Multiple Teachers'),
            ('batch', 'Batch Codes')
        ],
        required=False
    )
    teacher = forms.ModelChoiceField(queryset=Teacher.objects.none(), required=False, empty_label="Select a teacher")
    teachers = forms.ModelMultipleChoiceField(queryset=Teacher.objects.none(), required=False,
                                              widget=forms.CheckboxSelectMultiple)
    batch_codes = forms.ModelMultipleChoiceField(queryset=Batch.objects.none(), required=False,
                                                 widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].queryset = Teacher.objects.all()
        self.fields['teachers'].queryset = Teacher.objects.all()
        self.fields['batch_codes'].queryset = Batch.objects.all()


# ------------------ Parse OMR PDF ------------------
def parse_omr_pdf(omr_sheet, subject_names, total_responsive):
    """
    Reads PDF and extracts feedback counts for each subject
    across all forms inside the PDF. Uses some hardcoded subjects for testing.
    """
    feedback_data = {sub: {'5_star': 0, '3_star': 0, '1_star': 0} for sub in subject_names}

    hardcoded_subjects = {
        'Physics':   {'5_star': 400, '3_star': 100, '1_star': 100},  # 600
        'Chemistry': {'5_star': 350, '3_star': 200, '1_star': 150},  # 600
        'Maths':     {'5_star': 300, '3_star': 300, '1_star': 100},  # 600
        'Computer':  {'5_star': 350, '3_star': 150, '1_star': 100},  # 600
        'English':   {'5_star': 390, '3_star': 180, '1_star': 140},  # 600
        'Language':  {'5_star': 400, '3_star': 200, '1_star': 140},  # 600
        'Math':      {'5_star': 300, '3_star': 210, '1_star': 120},  # 600
        'Social':    {'5_star': 300, '3_star': 180, '1_star': 130},  # 600
        'Botany':    {'5_star': 300, '3_star': 220, '1_star': 140},  # 600
        'Zoology':   {'5_star': 300, '3_star': 200, '1_star': 150},  # 600
    }

    for subject in subject_names:
        if subject in hardcoded_subjects:
            feedback_data[subject] = hardcoded_subjects[subject]
            # logger.info(f"Hardcoded {subject} feedback: {feedback_data[subject]}")

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


# # ------------------ Upload ------------------
def upload(request):
    if request.method == 'POST':
        batch_code = request.POST.get('batch_code')
        phase = request.POST.get('phase')
        total_students = request.POST.get('total_students')
        total_responsive = request.POST.get('total_responsive')
        omr_sheet = request.FILES.get('omr_sheet')
        subject_names = request.POST.getlist('subject_name[]')
        teacher_names = request.POST.getlist('teacher_name[]')
        date_str = request.POST.get('date')   # ✅ Fetch date from form

        if not (batch_code and phase and total_students and total_responsive and omr_sheet and date_str):
            messages.error(request, "All fields are required.")
            return render(request, 'upload.html')

        total_students = int(total_students)
        total_responsive = int(total_responsive)
        batch_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()  # ✅ Convert to date

        # Save batch
        batch = Batch.objects.create(
            batch_code=batch_code,
            phase=phase,
            total_students=total_students,
            total_responsive=total_responsive,
            date=batch_date   # ✅ Save date
        )

        # Parse OMR PDF
        feedback_data = parse_omr_pdf(omr_sheet, subject_names, total_responsive)
        logger.info(f"Final feedback totals: {feedback_data}")

        QUESTIONS_PER_SUBJECT = 20
        MAX_MARKS_PER_QUESTION = 5
        max_possible_score = total_responsive * QUESTIONS_PER_SUBJECT * MAX_MARKS_PER_QUESTION

        for subject_name, teacher_name in zip(subject_names, teacher_names):
            teacher, _ = Teacher.objects.get_or_create(teacher_name=teacher_name)

            subject_feedback = feedback_data.get(subject_name, {'5_star': 0, '3_star': 0, '1_star': 0})

            weighted_score = (
                (5 * subject_feedback['5_star']) +
                (3 * subject_feedback['3_star']) +
                (1 * subject_feedback['1_star'])
            )

            average_percentage = (weighted_score / max_possible_score) * 100 if max_possible_score else 0
            average_percentage = min(100, round(average_percentage, 2))

            subject = Subject.objects.create(
                batch=batch,
                subject_name=subject_name,
                teacher=teacher,
                five_star=subject_feedback['5_star'],
                three_star=subject_feedback['3_star'],
                one_star=subject_feedback['1_star'],
                average_percentage=average_percentage,
                teacher_remarks=""
            )

            Performance.objects.create(
                batch=batch,
                teacher=teacher,
                subject=subject,
                average_percentage=average_percentage,
                remarks=""
            )

        return redirect('results', batch_id=batch.id)

    return render(request, 'upload.html')


# ------------------ Results ------------------
def results(request, batch_id):
    try:
        batch = Batch.objects.get(id=batch_id)
        subjects = Subject.objects.filter(batch=batch)
        return render(request, "result.html", {
            "batch": batch,
            "subjects": subjects,
            "phase": batch.phase,
            "total_students": batch.total_students,
            "total_responsive": batch.total_responsive,
            "date": batch.date,   # ✅ Pass date to template
        })
    except Batch.DoesNotExist:
        logger.error(f"Batch with ID {batch_id} not found")
        return JsonResponse({"status": "error", "message": "Batch not found"}, status=404)
    except Exception as e:
        logger.error(f"Error in results view for batch_id {batch_id}: {str(e)}")
        return JsonResponse({"status": "error", "message": "Internal server error"}, status=500)


# ------------------ Save Remarks ------------------
@csrf_protect
def save_remarks(request, batch_id):
    if request.method != "POST":
        logger.warning(f"Invalid request method for save_remarks: {request.method}")
        return JsonResponse({"status": "error", "message": "Invalid request method"}, status=405)

    try:
        batch = Batch.objects.get(id=batch_id)
        logger.debug(f"Request body: {request.body.decode('utf-8')}")
        data = json.loads(request.body)  # Expect JSON data with remarks
        for subject_id, remark in data.items():
            try:
                subject = Subject.objects.get(id=subject_id, batch=batch)
                subject.teacher_remarks = remark
                subject.save()

                # Sync remarks to the corresponding Performance model
                performance = Performance.objects.filter(batch=batch, subject=subject).first()
                if performance:
                    performance.remarks = remark
                    performance.save()
                else:
                    logger.warning(f"No performance found for subject {subject_id} in batch {batch_id}")

            except Subject.DoesNotExist:
                logger.error(f"Subject with ID {subject_id} not found for batch {batch_id}")
                return JsonResponse({"status": "error", "message": f"Subject with ID {subject_id} not found"}, status=404)
        return JsonResponse({"status": "success", "message": "Remarks saved successfully"})
    except Batch.DoesNotExist:
        logger.error(f"Batch with ID {batch_id} not found")
        return JsonResponse({"status": "error", "message": "Batch not found"}, status=404)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON data in save_remarks: {str(e)}")
        return JsonResponse({"status": "error", "message": "Invalid JSON data"}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in save_remarks: {str(e)}")
        return JsonResponse({"status": "error", "message": f"Internal server error: {str(e)}"}, status=500)


# ------------------ Report ------------------
def report(request):
    try:
        performances = Performance.objects.all().order_by('-created_at')

        # Fetch filters from GET
        keyword = request.GET.get("keyword", "").strip()
        mode = request.GET.get("mode", "")
        teacher_id = request.GET.get("teacher", "")
        teachers_ids = request.GET.getlist("teachers")
        batch_ids = request.GET.getlist("batch_codes")
        from_date = request.GET.get("from_date", "")
        to_date = request.GET.get("to_date", "")

        # Date range filter
        if from_date:
            performances = performances.filter(
                created_at__gte=timezone.make_aware(
                    timezone.datetime.combine(
                        timezone.datetime.fromisoformat(from_date).date(),
                        timezone.datetime.min.time()
                    )
                )
            )
        if to_date:
            performances = performances.filter(
                created_at__lte=timezone.make_aware(
                    timezone.datetime.combine(
                        timezone.datetime.fromisoformat(to_date).date(),
                        timezone.datetime.max.time()
                    )
                )
            )

        # Keyword filter
        if keyword:
            keywords = [k.strip() for k in keyword.split(",")]
            keyword_query = Q()
            for k in keywords:
                if k:
                    keyword_query |= (
                        Q(remarks__icontains=k) |
                        Q(teacher__teacher_name__icontains=k) |
                        Q(batch__batch_code__icontains=k)
                    )
            performances = performances.filter(keyword_query)

        # Mode filters
        if mode == "individual" and teacher_id:
            performances = performances.filter(teacher_id=teacher_id)
        elif mode == "multiple" and teachers_ids:
            performances = performances.filter(teacher_id__in=teachers_ids)
        elif mode == "batch" and batch_ids:
            performances = performances.filter(batch_id__in=batch_ids)

        # Fetch teachers and batches for dropdowns
        teachers = Teacher.objects.all().order_by("teacher_name")
        batches = Batch.objects.all().order_by("batch_code")

        context = {
            "performances": performances,
            "teachers": teachers,
            "batches": batches,
            "request": request,  # for GET values in template
        }
        return render(request, "report.html", context)

    except Exception as e:
        logger.error(f"Error in report view: {str(e)}", exc_info=True)
        return JsonResponse(
            {"status": "error", "message": "Internal server error"}, status=500
        )