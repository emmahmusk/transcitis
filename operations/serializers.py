from django.contrib.auth import get_user_model
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from .models import ItemCategory, OperationalException, Parcel, ParcelEvent, ParcelPricingRule, ParcelPricingSettings, StaffProfile, Station, Trip
from .permissions import PERMISSION_CATALOG


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ["id", "name", "code", "address"]
        read_only_fields = ["id"]


class StationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ["id", "name", "code", "address"]
        read_only_fields = ["id"]

    def validate_code(self, value):
        code = value.strip().upper()
        if not code or not all(ch.isalnum() or ch == "-" for ch in code):
            raise serializers.ValidationError("Use letters, numbers or hyphens in the station code.")
        return code


class StaffSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    username = serializers.CharField()
    role = serializers.CharField()
    station = serializers.CharField(allow_null=True)
    email = serializers.EmailField()
    is_active = serializers.BooleanField()


class DriverSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    phone_number = serializers.CharField(allow_blank=True)
    plate_number = serializers.CharField(allow_blank=True)
    role = serializers.CharField()
    station = serializers.CharField(allow_null=True)
    station_id = serializers.IntegerField(allow_null=True)
    is_active = serializers.BooleanField()


class EventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()
    station = serializers.CharField(source="station.name", allow_null=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ParcelEvent
        fields = ["id", "status", "status_label", "station", "actor", "note", "created_at"]

    @extend_schema_field(serializers.CharField())
    def get_actor(self, obj) -> str:
        return (obj.actor.get_full_name() or obj.actor.username) if obj.actor else "System"


class ParcelSerializer(serializers.ModelSerializer):
    origin_name = serializers.CharField(source="origin.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    events = EventSerializer(many=True, read_only=True)
    courier_name = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="item_category.name", read_only=True)

    class Meta:
        model = Parcel
        fields = ["id", "parcel_id", "sender_name", "sender_phone", "receiver_name", "receiver_phone", "delivery_address", "origin", "origin_name", "destination", "destination_name", "item_category", "category_name", "description", "service_type", "quantity", "weight_kg", "length_cm", "width_cm", "height_cm", "declared_value", "delivery_method", "charge", "amount_paid", "payment_method", "payment_reference", "is_paid", "status", "status_label", "handover_pin", "receipt_print_count", "courier", "courier_name", "created_at", "updated_at", "events"]
        read_only_fields = ["id", "parcel_id", "status", "handover_pin", "receipt_print_count", "charge", "is_paid", "created_at", "updated_at", "events"]

    def validate(self, attrs):
        origin = attrs.get("origin", getattr(self.instance, "origin", None))
        destination = attrs.get("destination", getattr(self.instance, "destination", None))
        if origin and destination and origin == destination:
            raise serializers.ValidationError({"destination": "Origin and destination must be different stations."})
        delivery_method = attrs.get("delivery_method", getattr(self.instance, "delivery_method", None))
        address = attrs.get("delivery_address", getattr(self.instance, "delivery_address", ""))
        if delivery_method == Parcel.DeliveryMethod.DOOR and not address.strip():
            raise serializers.ValidationError({"delivery_address": "Enter a delivery address for doorstep delivery."})
        return attrs

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_courier_name(self, obj) -> str | None:
        return (obj.courier.get_full_name() or obj.courier.username) if obj.courier else None


class TripSerializer(serializers.ModelSerializer):
    origin_name = serializers.CharField(source="origin.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)
    parcel_count = serializers.IntegerField(source="parcels.count", read_only=True)
    driver_name = serializers.SerializerMethodField()
    parcels_details = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = ["id", "trip_id", "origin", "origin_name", "destination", "destination_name", "driver", "driver_name", "vehicle", "status", "parcel_count", "parcels_details", "departed_at", "arrived_at", "created_at"]
        read_only_fields = ["trip_id", "status", "departed_at", "arrived_at"]

    @extend_schema_field(serializers.CharField())
    def get_driver_name(self, obj) -> str:
        return (obj.driver.get_full_name() or obj.driver.username) if obj.driver else obj.driver_name

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_parcels_details(self, obj) -> list[dict]:
        return [{"parcel_id": p.parcel_id, "receiver_name": p.receiver_name, "receiver_phone": p.receiver_phone,
                 "sender_name": p.sender_name, "description": p.description, "category": p.item_category.name,
                 "quantity": p.quantity, "weight_kg": str(p.weight_kg), "status": p.get_status_display()}
                for p in obj.parcels.select_related("item_category").all()]


class ExceptionSerializer(serializers.ModelSerializer):
    parcel_id = serializers.CharField(source="parcel.parcel_id", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = OperationalException
        fields = ["id", "parcel", "parcel_id", "kind", "kind_label", "note", "is_resolved", "resolution", "created_by_name", "created_at", "resolved_at"]
        read_only_fields = ["id", "is_resolved", "resolution", "created_at", "resolved_at"]

    @extend_schema_field(serializers.CharField())
    def get_created_by_name(self, obj) -> str:
        return obj.created_by.get_full_name() or obj.created_by.username


class ItemCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemCategory
        fields = ["id", "name", "code", "description", "charge", "is_active"]


class ParcelPricingRuleSerializer(serializers.ModelSerializer):
    origin_name = serializers.CharField(source="origin.name", read_only=True)
    destination_name = serializers.CharField(source="destination.name", read_only=True)
    category_name = serializers.CharField(source="item_category.name", read_only=True)

    class Meta:
        model = ParcelPricingRule
        fields = ["id", "origin", "origin_name", "destination", "destination_name", "item_category", "category_name", "service_type", "base_charge", "included_weight_kg", "additional_kg_charge", "volumetric_divisor", "declared_value_rate_percent", "doorstep_charge", "extra_unit_charge", "minimum_charge", "is_active", "updated_at"]
        read_only_fields = ["id", "updated_at"]

    def validate(self, attrs):
        origin = attrs.get("origin", getattr(self.instance, "origin", None))
        destination = attrs.get("destination", getattr(self.instance, "destination", None))
        if origin and destination and origin == destination:
            raise serializers.ValidationError({"destination": "Origin and destination must be different stations."})
        category = attrs.get("item_category", getattr(self.instance, "item_category", None))
        if category and not category.is_active:
            raise serializers.ValidationError({"item_category": "Pricing rules can only be assigned to active categories."})
        if attrs.get("volumetric_divisor", getattr(self.instance, "volumetric_divisor", 5000)) <= 0:
            raise serializers.ValidationError({"volumetric_divisor": "Must be greater than zero."})
        for name in ("base_charge", "included_weight_kg", "additional_kg_charge", "declared_value_rate_percent", "doorstep_charge", "extra_unit_charge", "minimum_charge"):
            value = attrs.get(name, getattr(self.instance, name, 0) if self.instance else 0)
            if value < 0:
                raise serializers.ValidationError({name: "This value cannot be negative."})
        if origin and destination and category:
            service = attrs.get("service_type", getattr(self.instance, "service_type", ParcelPricingRule.ServiceType.STANDARD))
            duplicates = ParcelPricingRule.objects.filter(origin=origin, destination=destination, item_category=category, service_type=service)
            if self.instance:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError("A tariff already exists for this route, category and service level.")
        return attrs


class ParcelPricingSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParcelPricingSettings
        fields = ["auto_charge_enabled", "default_route_charge", "default_included_weight_kg", "default_additional_kg_charge", "default_volumetric_divisor", "default_declared_value_rate_percent", "default_doorstep_charge", "default_extra_unit_charge", "default_minimum_charge", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate(self, attrs):
        for name in ("default_route_charge", "default_included_weight_kg", "default_additional_kg_charge", "default_declared_value_rate_percent", "default_doorstep_charge", "default_extra_unit_charge", "default_minimum_charge"):
            value = attrs.get(name, getattr(self.instance, name, 0) if self.instance else 0)
            if value < 0:
                raise serializers.ValidationError({name: "This value cannot be negative."})
        if attrs.get("default_volumetric_divisor", getattr(self.instance, "default_volumetric_divisor", 5000)) <= 0:
            raise serializers.ValidationError({"default_volumetric_divisor": "Must be greater than zero."})
        return attrs


class ParcelPriceEstimateSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=180)
    item_category = serializers.PrimaryKeyRelatedField(queryset=ItemCategory.objects.filter(is_active=True))
    origin = serializers.PrimaryKeyRelatedField(queryset=Station.objects.filter(is_active=True))
    destination = serializers.PrimaryKeyRelatedField(queryset=Station.objects.filter(is_active=True))
    service_type = serializers.ChoiceField(choices=Parcel.ServiceType.choices, default=Parcel.ServiceType.STANDARD)
    delivery_method = serializers.ChoiceField(choices=Parcel.DeliveryMethod.choices, default=Parcel.DeliveryMethod.PICKUP)
    weight_kg = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0, default=0)
    length_cm = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True)
    width_cm = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True)
    height_cm = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, max_value=32767, default=1)
    declared_value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, default=0)
    lookup_market_value = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if attrs["origin"] == attrs["destination"]:
            raise serializers.ValidationError({"destination": "Origin and destination must be different stations."})
        dimensions = [attrs.get("length_cm"), attrs.get("width_cm"), attrs.get("height_cm")]
        if any(value is not None for value in dimensions) and not all(value is not None for value in dimensions):
            raise serializers.ValidationError("Enter all three parcel dimensions to use volumetric weight.")
        return attrs


class StaffInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.RegexField(r"^[\w.@+-]+$", max_length=150, required=False)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=StaffProfile.Role.choices)
    station = serializers.PrimaryKeyRelatedField(queryset=StaffProfile._meta.get_field("station").remote_field.model.objects.all(), required=False, allow_null=True)


class DriverCreateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=24)
    plate_number = serializers.CharField(max_length=24)
    station = serializers.PrimaryKeyRelatedField(queryset=StaffProfile._meta.get_field("station").remote_field.model.objects.all())


class StaffUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=StaffProfile.Role.choices, required=False)
    station = serializers.PrimaryKeyRelatedField(queryset=StaffProfile._meta.get_field("station").remote_field.model.objects.all(), required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)


class RolePermissionUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=StaffProfile.Role.choices)
    permissions = serializers.ListField(child=serializers.ChoiceField(choices=[(p["key"], p["label"]) for p in PERMISSION_CATALOG]), allow_empty=True)

    def validate_permissions(self, values):
        return list(dict.fromkeys(values))


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(min_length=10, write_only=True)
    password_confirm = serializers.CharField(min_length=10, write_only=True)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs
