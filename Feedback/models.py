from django.db import models

class Batch(models.Model):
    batch_code = models.CharField(max_length=50)
    phase = models.CharField(max_length=50)
    total_students = models.IntegerField()
    total_responsive = models.IntegerField()
    date = models.DateField(null=True, blank=True)   # ✅ Add this line
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.batch_code


class Teacher(models.Model):
    teacher_name = models.CharField(max_length=100)

    def __str__(self):
        return self.teacher_name


class Subject(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE)
    subject_name = models.CharField(max_length=100)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    five_star = models.IntegerField(default=0)
    three_star = models.IntegerField(default=0)
    one_star = models.IntegerField(default=0)
    average_percentage = models.FloatField(default=0.0)
    teacher_remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.subject_name} ({self.teacher.teacher_name})"


class Performance(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    average_percentage = models.FloatField(default=0.0)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.teacher.teacher_name} - {self.subject.subject_name}"