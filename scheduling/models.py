"""Models for the scheduling application."""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import User

from .services import slot_windows

doctor_code_validator = RegexValidator(
    regex=r"^D\d{1,3}$",
    message="Enter a doctor code that starts with D followed by a number, for example D2.",
)


class Doctor(models.Model):
    """A doctor who sees patients at the clinic.

    Supports SCH-01 (doctor profiles). The code is used in queue tokens such
    as D2-014 (BR-14). A doctor is deactivated and never deleted, so that past
    appointments keep their history.

    Attributes:
        user: The login account of this doctor. It must have the doctor role.
        code: Short unique code such as D2, shown on tokens and the display.
        specialty: Area of medicine, used when patients search (BKG-01).
        room: Consulting room, shown on the waiting-room display.
        default_slot_minutes: Length of one appointment slot (default 15).
        is_active: False when the doctor no longer takes appointments.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doctor",
        limit_choices_to={"role": User.Role.DOCTOR},
    )
    code = models.CharField(
        max_length=4,
        unique=True,
        validators=[doctor_code_validator],
        error_messages={
            "unique": (
                "This doctor code is already used by another doctor. "
                "Each doctor needs a different code, for example D2 or D3."
            )
        },
    )
    specialty = models.CharField(max_length=100)
    room = models.CharField(max_length=20)
    default_slot_minutes = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(5)]
    )
    is_active = models.BooleanField(default=True)

    def clean(self):
        """Check that the linked account has the doctor role (SEC-01)."""
        if self.user_id and self.user.role != User.Role.DOCTOR:
            raise ValidationError(
                {
                    "user": (
                        "This account does not have the doctor role. "
                        "Change the account's role to Doctor first, "
                        "or choose a different account."
                    )
                }
            )

    def __str__(self):
        """Return the name, code and specialty, which is how staff pick a doctor."""
        name = self.user.get_full_name() or self.user.username
        return f"Dr. {name} ({self.code}, {self.specialty})"


class ScheduleRule(models.Model):
    """One weekly working session of a doctor, for example Monday 17:00 to 21:00.

    Supports SCH-02. A doctor may have several sessions on one weekday, for
    example a morning and an evening session, as long as they do not overlap.
    The bookable slots are worked out from the session (see services.py), so
    no slot rows are stored.

    Attributes:
        doctor: The doctor who works this session.
        weekday: Day of the week (Python numbering: Monday is 0).
        start_time: When the session starts.
        end_time: When the session ends.
        slot_minutes: Length of one appointment slot in this session.
    """

    class Weekday(models.IntegerChoices):
        """Days of the week, listed from Saturday as in Bangladesh."""

        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="schedule_rules")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(5), MaxValueValidator(120)]
    )

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                check=Q(end_time__gt=F("start_time")),
                name="session_ends_after_it_starts",
                violation_error_message=(
                    "The session must end after it starts. "
                    "Check the start and end times and try again."
                ),
            )
        ]

    def clean(self):
        """Check the times make sense and do not overlap another session."""
        if self.start_time is None or self.end_time is None:
            return
        if self.end_time <= self.start_time:
            raise ValidationError(
                "The end time must be after the start time. Check both times and try again."
            )
        if self.slot_minutes:
            length = (self.end_time.hour * 60 + self.end_time.minute) - (
                self.start_time.hour * 60 + self.start_time.minute
            )
            if length < self.slot_minutes:
                raise ValidationError(
                    f"This session is only {length} minutes long, which is shorter than "
                    f"one {self.slot_minutes}-minute slot. Make the session longer or "
                    "choose a shorter slot length."
                )
        if self.doctor_id is None or self.weekday is None:
            return
        others = ScheduleRule.objects.filter(doctor_id=self.doctor_id, weekday=self.weekday)
        for other in others.exclude(pk=self.pk):
            if self.start_time < other.end_time and self.end_time > other.start_time:
                raise ValidationError(
                    f"This session overlaps your {other.get_weekday_display()} session from "
                    f"{other.start_time:%H:%M} to {other.end_time:%H:%M}. "
                    "Change the times, or delete the other session first."
                )

    @property
    def slot_count(self):
        """Return how many bookable slots this session offers every week."""
        return len(slot_windows(self))

    def __str__(self):
        """Return the day and times, for example Monday 17:00-21:00."""
        return f"{self.get_weekday_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M}"


class ScheduleBreak(models.Model):
    """A break inside a weekly session, for example 19:00 to 19:30 (SCH-02).

    Slots that overlap a break are not offered to patients.

    Attributes:
        rule: The session this break belongs to.
        start_time: When the break starts.
        end_time: When the break ends.
    """

    rule = models.ForeignKey(ScheduleRule, on_delete=models.CASCADE, related_name="breaks")
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ["start_time"]

    def clean(self):
        """Check the break ends after it starts and sits inside its session."""
        if self.start_time is None or self.end_time is None:
            return
        if self.end_time <= self.start_time:
            raise ValidationError(
                "The break must end after it starts. Check both times and try again."
            )
        if self.rule_id is None:
            return
        if self.start_time < self.rule.start_time or self.end_time > self.rule.end_time:
            raise ValidationError(
                f"The break must be inside the session, which runs from "
                f"{self.rule.start_time:%H:%M} to {self.rule.end_time:%H:%M}. "
                "Change the break times and try again."
            )

    def __str__(self):
        """Return the break times, for example 19:00-19:30."""
        return f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"


class DoctorLeave(models.Model):
    """Days or hours when a doctor is away (SCH-03, BR-13).

    Without times, the leave covers whole days from the start date to the end
    date. With times, it covers part of one day, for example 17:00 to 19:00.
    No slots are offered during a leave, and appointments that fall inside it
    must be moved (see leave.py).

    Attributes:
        doctor: The doctor who is away.
        start_date: The first day of the leave.
        end_date: The last day of the leave.
        start_time: When the leave starts, for leave of a few hours only.
        end_time: When the leave ends, for leave of a few hours only.
        reason: Optional note for the clinic.
    """

    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE, related_name="leaves")
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_date", "start_time"]
        constraints = [
            models.CheckConstraint(
                check=Q(end_date__gte=F("start_date")),
                name="leave_ends_on_or_after_it_starts",
                violation_error_message=(
                    "The last day of the leave cannot be before the first day. "
                    "Check both dates and try again."
                ),
            )
        ]

    @property
    def starts_at(self):
        """Return the moment the leave starts, as a Dhaka-time datetime."""
        return timezone.make_aware(datetime.combine(self.start_date, self.start_time or time.min))

    @property
    def ends_at(self):
        """Return the moment the leave ends, as a Dhaka-time datetime."""
        if self.end_time:
            return timezone.make_aware(datetime.combine(self.end_date, self.end_time))
        return timezone.make_aware(datetime.combine(self.end_date + timedelta(days=1), time.min))

    def __str__(self):
        """Return the period in words, for example 16 Nov 2026 to 18 Nov 2026."""
        if self.start_time:
            return f"{self.start_date:%d %b %Y} {self.start_time:%H:%M} to {self.end_time:%H:%M}"
        if self.start_date == self.end_date:
            return f"{self.start_date:%d %b %Y}"
        return f"{self.start_date:%d %b %Y} to {self.end_date:%d %b %Y}"
