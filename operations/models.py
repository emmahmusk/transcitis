import secrets
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Station(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=12, unique=True)
    address = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class StaffProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        SUPERVISOR = "supervisor", "Supervisor"
        STAFF = "staff", "Station staff"
        COURIER = "courier", "Courier"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile")
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL, related_name="staff")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)
    phone_number = models.CharField(max_length=24, blank=True)
    plate_number = models.CharField(max_length=24, blank=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} · {self.get_role_display()}"


class RolePermission(models.Model):
    """Configurable permission grants for each built-in staff role."""

    role = models.CharField(max_length=16, choices=StaffProfile.Role.choices, unique=True)
    permissions = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role"]
        verbose_name = "role permission set"
        verbose_name_plural = "role permission sets"

    def __str__(self):
        return self.get_role_display()


class Parcel(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Registered"
        READY = "ready", "Ready for dispatch"
        ON_TRIP = "on_trip", "On a trip"
        RECEIVED = "received", "Received at destination"
        PICKUP = "pickup", "Ready for pickup"
        OUT = "out_for_delivery", "Out for delivery"
        COLLECTED = "collected", "Collected"
        DELIVERED = "delivered", "Delivered"

    class DeliveryMethod(models.TextChoices):
        PICKUP = "pickup", "Station pickup"
        DOOR = "door", "Doorstep delivery"

    class ServiceType(models.TextChoices):
        STANDARD = "standard", "Standard"
        EXPRESS = "express", "Express"

    parcel_id = models.CharField(max_length=20, unique=True, editable=False)
    sender_name = models.CharField(max_length=120)
    sender_phone = models.CharField(max_length=24)
    receiver_name = models.CharField(max_length=120)
    receiver_phone = models.CharField(max_length=24)
    delivery_address = models.CharField(max_length=240, blank=True)
    origin = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="outbound_parcels")
    destination = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="inbound_parcels")
    description = models.CharField(max_length=180)
    item_category = models.ForeignKey("ItemCategory", on_delete=models.PROTECT, related_name="parcels")
    service_type = models.CharField(max_length=16, choices=ServiceType.choices, default=ServiceType.STANDARD)
    quantity = models.PositiveSmallIntegerField(default=1)
    weight_kg = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    declared_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_method = models.CharField(max_length=12, choices=DeliveryMethod.choices, default=DeliveryMethod.PICKUP)
    charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=24, default="cash")
    payment_reference = models.CharField(max_length=80, blank=True)
    is_paid = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REGISTERED)
    handover_pin = models.CharField(max_length=6, default="000000")
    receipt_print_count = models.PositiveSmallIntegerField(default=0)
    first_receipt_printed_at = models.DateTimeField(null=True, blank=True)
    last_receipt_printed_at = models.DateTimeField(null=True, blank=True)
    last_receipt_printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="last_receipt_prints")
    courier = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_parcels")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registered_parcels")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"]), models.Index(fields=["receiver_phone"])]

    def save(self, *args, **kwargs):
        if not self.parcel_id:
            self.parcel_id = f"TC{secrets.token_hex(4).upper()}"
        if not self.handover_pin or self.handover_pin == "000000":
            self.handover_pin = f"{secrets.randbelow(1000000):06d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.parcel_id


class Trip(models.Model):
    class Status(models.TextChoices):
        PREPARING = "preparing", "Preparing"
        IN_TRANSIT = "in_transit", "In transit"
        ARRIVED = "arrived", "Arrived"

    trip_id = models.CharField(max_length=20, unique=True, editable=False)
    origin = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="departing_trips")
    destination = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="arriving_trips")
    driver_name = models.CharField(max_length=120, blank=True)
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="courier_trips")
    vehicle = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREPARING)
    parcels = models.ManyToManyField(Parcel, blank=True, related_name="trips")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    departed_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.trip_id:
            self.trip_id = f"TR{secrets.token_hex(3).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.trip_id


class ParcelEvent(models.Model):
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=32, choices=Parcel.Status.choices)
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class OperationalException(models.Model):
    class Kind(models.TextChoices):
        DAMAGED = "damaged", "Damaged"
        MISSING = "missing", "Missing from trip"
        MISMATCH = "mismatch", "Mismatched parcel"
        DELIVERY = "delivery_attempt", "Delivery attempted"
        OTHER = "other", "Other"

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="exceptions")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    note = models.CharField(max_length=240)
    is_resolved = models.BooleanField(default=False)
    resolution = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opened_exceptions")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_exceptions")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)


class ItemCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.SlugField(max_length=40, unique=True)
    description = models.CharField(max_length=240, blank=True)
    charge = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "item categories"

    def __str__(self):
        return self.name

    def clean(self):
        if self.is_active and self.charge is None:
            raise ValidationError({"charge": "Set an approved charge before activating this category."})


class ReceiptPrint(models.Model):
    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="receipt_prints")
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    printed_at = models.DateTimeField(auto_now_add=True)
    is_reprint = models.BooleanField(default=False)

    class Meta:
        ordering = ["printed_at"]


class Invitation(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invitation")
    token_digest = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="staff_invitations_sent")
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
