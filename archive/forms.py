from django import forms
from django.utils import timezone


class MediaBackupForm(forms.Form):
    cutoff_date = forms.DateField(
        label="Include media up to and including",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Media attached to messages on or before this date will be backed up.",
    )
    delete_originals = forms.BooleanField(
        required=False,
        label="Delete original files after the ZIP is created successfully",
        help_text="The message records remain in the database, but their local media links are cleared.",
    )

    def clean_cutoff_date(self):
        cutoff_date = self.cleaned_data["cutoff_date"]
        if cutoff_date > timezone.localdate():
            raise forms.ValidationError("The cutoff date cannot be in the future.")
        return cutoff_date
