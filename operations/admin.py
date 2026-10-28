from django.contrib import admin
from .models import Invitation, ItemCategory, OperationalException, Parcel, ParcelEvent, ParcelPricingRule, ParcelPricingSettings, ReceiptPrint, RolePermission, StaffProfile, Station, Trip


@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "charge", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "description")


@admin.register(ParcelPricingRule)
class ParcelPricingRuleAdmin(admin.ModelAdmin):
    list_display = ("origin", "destination", "item_category", "service_type", "base_charge", "is_active", "updated_at")
    list_filter = ("origin", "destination", "item_category", "service_type", "is_active")


@admin.register(ParcelPricingSettings)
class ParcelPricingSettingsAdmin(admin.ModelAdmin):
    list_display = ("auto_charge_enabled", "default_route_charge", "default_additional_kg_charge", "updated_at")
    readonly_fields = ("updated_at", "updated_by")


@admin.register(ReceiptPrint)
class ReceiptPrintAdmin(admin.ModelAdmin):
    list_display = ("parcel", "printed_by", "printed_at", "is_reprint")
    list_filter = ("is_reprint", "printed_at")
    readonly_fields = ("parcel", "printed_by", "printed_at", "is_reprint")


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ("role", "updated_at")
    readonly_fields = ("updated_at",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("user", "created_by", "expires_at", "accepted_at", "created_at")
    readonly_fields = ("user", "token_digest", "created_by", "expires_at", "accepted_at", "created_at")


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "address", "is_active")
    search_fields = ("code", "name")


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "station")
    list_filter = ("role", "station")
    search_fields = ("user__username", "user__first_name", "user__last_name")


class EventInline(admin.TabularInline):
    model = ParcelEvent
    extra = 0
    readonly_fields = ("status", "station", "actor", "note", "created_at")


@admin.register(Parcel)
class ParcelAdmin(admin.ModelAdmin):
    list_display = ("parcel_id", "receiver_name", "origin", "destination", "status", "created_at")
    list_filter = ("status", "delivery_method", "origin", "destination")
    search_fields = ("parcel_id", "sender_name", "receiver_name", "sender_phone", "receiver_phone")
    readonly_fields = ("parcel_id", "handover_pin", "created_at", "updated_at")
    inlines = (EventInline,)


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("trip_id", "origin", "destination", "status", "driver_name", "created_at")
    list_filter = ("status", "origin", "destination")
    filter_horizontal = ("parcels",)


@admin.register(OperationalException)
class ExceptionAdmin(admin.ModelAdmin):
    list_display = ("parcel", "kind", "is_resolved", "created_by", "created_at")
    list_filter = ("kind", "is_resolved")
    search_fields = ("parcel__parcel_id", "note", "resolution")
