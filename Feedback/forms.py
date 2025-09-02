from django import forms
from .models import Teacher, Batch, Performance

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
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.all(),
        required=False,
        empty_label="Select a teacher"
    )
    teachers = forms.ModelMultipleChoiceField(
        queryset=Teacher.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )
    batch_codes = forms.ModelMultipleChoiceField(
        queryset=Batch.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )