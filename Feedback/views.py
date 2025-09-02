import logging
import re
import json
from django.http import JsonResponse
from .utils import parse_omr_pdf_with_subject_blocks
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django import forms
from .models import Batch, Subject, Teacher, Performance
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from Feedback import utils


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

def upload(request):
    if request.method == "POST":
        logger.info("Received POST request for upload")

        batch_code = request.POST.get("batch_code")
        phase = request.POST.get("phase")
        total_students = request.POST.get("total_students")
        total_responsive = int(request.POST.get("total_responsive", 0))
        date = request.POST.get("date")

        subject_names = request.POST.getlist("subject_name[]")
        teacher_names = request.POST.getlist("teacher_name[]")
        omr_file = request.FILES.get("omr_sheet")

        if not omr_file:
            messages.error(request, "No OMR file uploaded. Please select a PDF.")
            return render(request, "upload.html")

        if not batch_code or not phase or not total_students or not subject_names:
            messages.error(request, "All fields are required.")
            return render(request, "upload.html")

        # Create Batch up-front
        batch = Batch.objects.create(
            batch_code=batch_code,
            phase=phase,
            total_students=total_students,
            total_responsive=total_responsive,
            date=date,
        )

        # Parse PDF → counts
        feedback = parse_omr_pdf_with_subject_blocks(omr_file, debug_dir="bubble_debug_images")
        aggregated = feedback.get("aggregated", {})
        per_form_results = feedback.get("per_form", [])

        # Save subjects (only for those the user listed)
        for subject_name, teacher_name in zip(subject_names, teacher_names):
            counts = aggregated.get(
                subject_name, {"5_star": 0, "3_star": 0, "1_star": 0}
            )
            five_star = int(counts.get("5_star", 0))
            three_star = int(counts.get("3_star", 0))
            one_star = int(counts.get("1_star", 0))

            total_responses = five_star + three_star + one_star
            if total_responses > 0:
                score = five_star * 5 + three_star * 3 + one_star * 1
                average_percentage = (score / (total_responses * 5.0)) * 100.0
            else:
                average_percentage = 0.0

            teacher_obj, _ = Teacher.objects.get_or_create(
                teacher_name=teacher_name.strip()
            )

            Subject.objects.create(
                batch=batch,
                subject_name=subject_name.strip(),
                teacher=teacher_obj,
                five_star=five_star,
                three_star=three_star,
                one_star=one_star,
                average_percentage=average_percentage,
            )

        # Stash per-form results (optional use in template)
        request.session["per_form_results"] = per_form_results
        messages.success(request, "Feedback uploaded successfully!")
        return redirect("results", batch_id=batch.id)

    return render(request, "upload.html")

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