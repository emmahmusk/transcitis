import csv
import hashlib
import secrets
from datetime import timedelta
import barcode
from barcode.writer import SVGWriter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import Invitation, ItemCategory, OperationalException, Parcel, ParcelEvent, ReceiptPrint, RolePermission, StaffProfile, Station, Trip
from .permissions import DEFAULT_ROLE_PERMISSIONS, PERMISSION_CATALOG
from .serializers import DriverCreateSerializer, DriverSerializer, ExceptionSerializer, InviteAcceptSerializer, ItemCategorySerializer, ParcelSerializer, RolePermissionUpdateSerializer, StaffInviteSerializer, StaffUpdateSerializer, StationCreateSerializer, StationSerializer, TripSerializer


def staff_role(user):
    if user.is_superuser:
        return StaffProfile.Role.ADMIN, None
    try:
        profile = user.staff_profile
    except StaffProfile.DoesNotExist:
        profile = None
    return (profile.role, profile.station) if profile else (StaffProfile.Role.STAFF, None)


def user_permissions(user):
    if user.is_superuser:
        return ["*"]
    role, _ = staff_role(user)
    configured = RolePermission.objects.filter(role=role).values_list("permissions", flat=True).first()
    return configured if configured is not None else DEFAULT_ROLE_PERMISSIONS.get(role, [])


def permission_denied(user, permission):
    required = {permission} if isinstance(permission, str) else set(permission)
    if user.is_superuser or required.intersection(user_permissions(user)):
        return None
    return Response({"detail": f"Your role does not grant the {' or '.join(sorted(required))} permission."}, status=403)


def staff_station(user):
    try:
        return user.staff_profile.station
    except StaffProfile.DoesNotExist:
        return None


def visible_parcels(user):
    role, station = staff_role(user)
    qs = Parcel.objects.select_related("origin", "destination", "courier").prefetch_related("events__station", "events__actor")
    if user.is_superuser:
        return qs
    if role == StaffProfile.Role.COURIER:
        return qs.filter(courier=user)
    return qs.filter(Q(origin=station) | Q(destination=station)) if station else qs.none()


def can_access_parcel(user, parcel):
    return visible_parcels(user).filter(pk=parcel.pk).exists()


def visible_trips(user):
    qs = Trip.objects.select_related("origin", "destination").prefetch_related("parcels")
    role, station = staff_role(user)
    if user.is_superuser:
        return qs
    if role == StaffProfile.Role.COURIER:
        return qs.filter(driver=user)
    return qs.filter(Q(origin=station) | Q(destination=station)) if station else qs.none()


def add_event(parcel, user, status_value=None, note="", station=None):
    return ParcelEvent.objects.create(parcel=parcel, status=status_value or parcel.status, actor=user, station=station, note=note)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class StaffTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        payload = user_payload(user)
        token["user"] = {**payload, "permissions": user_permissions(user)}
        token["user_id"] = payload["id"]
        token["username"] = payload["username"]
        token["role"] = payload["role"]
        token["role_label"] = payload["role_label"]
        token["station_id"] = payload["station_id"]
        token["station_code"] = payload["station_code"]
        token["roles"] = payload["roles"]
        token["permissions"] = user_permissions(user)
        return token


class StaffTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        old_refresh = RefreshToken(attrs["refresh"])
        user = get_user_model().objects.filter(pk=old_refresh.get(api_settings.USER_ID_CLAIM)).first()
        if user and user.is_active:
            fresh = StaffTokenObtainPairSerializer.get_token(user)
            claims = {key: fresh[key] for key in ("user", "user_id", "username", "role", "role_label", "station_id", "station_code", "roles", "permissions")}
            access = AccessToken(data["access"])
            for key, value in claims.items():
                access[key] = value
            data["access"] = str(access)
            if data.get("refresh"):
                rotated = RefreshToken(data["refresh"])
                for key, value in claims.items():
                    rotated[key] = value
                data["refresh"] = str(rotated)
        return data


def visible_staff(user):
    qs = get_user_model().objects.filter(staff_profile__isnull=False).select_related("staff_profile", "staff_profile__station")
    if user.is_superuser:
        return qs
    station = staff_station(user)
    if not station:
        return qs.none()
    return qs.filter(staff_profile__station=station, is_superuser=False).exclude(staff_profile__role__in=[StaffProfile.Role.ADMIN, StaffProfile.Role.COURIER])


def manageable_staff(user):
    if user.is_superuser:
        return visible_staff(user)
    if "users.manage" not in user_permissions(user):
        return get_user_model().objects.none()
    return visible_staff(user)


def staff_user_data(user):
    profile = user.staff_profile
    try:
        invite = user.invitation
        invite_status = "accepted" if invite.accepted_at else ("expired" if invite.expires_at <= timezone.now() else "pending")
    except Invitation.DoesNotExist:
        invite_status = "active"
    return {"id": user.id, "name": user.get_full_name() or user.username, "username": user.username,
            "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
            "role": profile.role, "role_label": profile.get_role_display(), "station": profile.station.name if profile.station else None,
            "station_id": profile.station_id, "is_active": user.is_active, "invite_status": invite_status}


def issue_staff_tokens(user):
    refresh = StaffTokenObtainPairSerializer.get_token(user)
    return {"access": refresh.access_token, "refresh": refresh}


class ParcelCreateSerializer(serializers.ModelSerializer):
    quantity = serializers.IntegerField(min_value=1, max_value=32767, default=1)
    weight_kg = serializers.DecimalField(max_digits=7, decimal_places=2, min_value=0, default=0)
    declared_value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0)
    charge = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, read_only=True)
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Parcel
        exclude = ["parcel_id", "handover_pin", "status", "courier", "created_by", "receipt_print_count", "first_receipt_printed_at", "last_receipt_printed_at", "last_receipt_printed_by", "created_at", "updated_at"]

    def validate(self, attrs):
        origin, destination = attrs.get("origin"), attrs.get("destination")
        if origin and destination and origin == destination:
            raise serializers.ValidationError({"destination": "Origin and destination must be different stations."})
        if attrs.get("delivery_method") == Parcel.DeliveryMethod.DOOR and not attrs.get("delivery_address", "").strip():
            raise serializers.ValidationError({"delivery_address": "Enter a delivery address for doorstep delivery."})
        category = attrs.get("item_category")
        if not category or not category.is_active or category.charge is None:
            raise serializers.ValidationError({"item_category": "Choose a category with an approved charge."})
        if attrs.get("amount_paid", 0) > category.charge:
            raise serializers.ValidationError({"amount_paid": "Amount paid cannot exceed the mapped charge."})
        return attrs

    def create(self, validated_data):
        validated_data["charge"] = validated_data["item_category"].charge
        validated_data["is_paid"] = validated_data.get("amount_paid", 0) >= validated_data["charge"]
        return Parcel.objects.create(**validated_data)


class ParcelStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Parcel.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=240)


class ScanSerializer(serializers.Serializer):
    parcel_id = serializers.CharField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=240)
    kind = serializers.ChoiceField(choices=OperationalException.Kind.choices, required=False)


class HandoverSerializer(serializers.Serializer):
    pin = serializers.RegexField(r"^\d{6}$")
    recipient_name = serializers.CharField(max_length=120)


class ExceptionCreateSerializer(serializers.Serializer):
    parcel_id = serializers.CharField()
    kind = serializers.ChoiceField(choices=OperationalException.Kind.choices)
    note = serializers.CharField(max_length=240)


class ExceptionResolveSerializer(serializers.Serializer):
    resolution = serializers.CharField(max_length=240)


class CourierAssignSerializer(serializers.Serializer):
    username = serializers.CharField()


@extend_schema(tags=["Authentication"], responses={200: OpenApiTypes.OBJECT})
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def csrf_token(request):
    return Response({"detail": "CSRF cookie set."})


@extend_schema(tags=["Authentication"], summary="Sign in and issue JWT tokens", description="Validates staff credentials and returns an access token containing user, role, station and permission claims plus a rotating refresh token.", request=LoginSerializer, responses={200: OpenApiTypes.OBJECT, 401: OpenApiTypes.OBJECT}, auth=[])
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_login(request):
    serializer = StaffTokenObtainPairSerializer(data=request.data, context={"request": request})
    if not serializer.is_valid():
        return Response({"detail": "Username or password is incorrect."}, status=401)
    return token_response(serializer.user, serializer.validated_data)


def user_payload(user):
    try:
        profile = user.staff_profile
    except StaffProfile.DoesNotExist:
        profile = None
    role = "superadmin" if user.is_superuser else (profile.role if profile else StaffProfile.Role.STAFF)
    return {"id": user.id, "name": user.get_full_name() or user.username, "username": user.username,
            "email": user.email, "role": role, "roles": [role],
            "role_label": "Super Administrator" if user.is_superuser else (profile.get_role_display() if profile else "Station staff"),
            "station": profile.station.name if profile and profile.station else None,
            "station_id": profile.station_id if profile else None,
            "station_code": profile.station.code if profile and profile.station else None,
            "is_superadmin": user.is_superuser, "permissions": user_permissions(user)}


def token_response(user, tokens, status_code=200):
    response = Response({"access": str(tokens["access"]), "refresh": str(tokens["refresh"]), "user": user_payload(user)}, status=status_code)
    secure = not settings.DEBUG
    response.set_cookie("transcitis_access", str(tokens["access"]), max_age=20 * 60, httponly=True, secure=secure, samesite="Lax", path="/")
    response.set_cookie("transcitis_refresh", str(tokens["refresh"]), max_age=24 * 60 * 60, httponly=True, secure=secure, samesite="Lax", path="/api/auth/")
    return response


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False)


@extend_schema(tags=["Authentication"], summary="Revoke a refresh token", description="Blacklists the supplied refresh token and clears the HttpOnly authentication cookies.", request=LogoutSerializer, responses={200: OpenApiTypes.OBJECT})
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_logout(request):
    refresh = request.data.get("refresh") or request.COOKIES.get("transcitis_refresh")
    if refresh:
        try:
            RefreshToken(refresh).blacklist()
        except Exception:
            pass
    response = Response({"detail": "Signed out."})
    response.delete_cookie("transcitis_access", path="/")
    response.delete_cookie("transcitis_refresh", path="/api/auth/")
    return response


@extend_schema(tags=["Authentication"], summary="Refresh JWT access token", description="Issues a new access token and rotates the refresh token with current user, role, station and permission claims.", request=StaffTokenRefreshSerializer, responses={200: OpenApiTypes.OBJECT})
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def auth_refresh(request):
    serializer = StaffTokenRefreshSerializer(data={"refresh": request.data.get("refresh") or request.COOKIES.get("transcitis_refresh")})
    serializer.is_valid(raise_exception=True)
    response = Response(serializer.validated_data)
    secure = not settings.DEBUG
    response.set_cookie("transcitis_access", serializer.validated_data["access"], max_age=20 * 60, httponly=True, secure=secure, samesite="Lax", path="/")
    if "refresh" in serializer.validated_data:
        response.set_cookie("transcitis_refresh", serializer.validated_data["refresh"], max_age=24 * 60 * 60, httponly=True, secure=secure, samesite="Lax", path="/api/auth/")
    return response


@extend_schema(tags=["Authentication"], summary="Retrieve current user claims", description="Returns the authenticated identity, station assignment, role and permissions encoded in the access token.", responses={200: OpenApiTypes.OBJECT})
@api_view(["GET"])
def auth_me(request):
    return Response({"user": user_payload(request.user), "token": {"role": request.auth.get("role"), "roles": request.auth.get("roles", []), "permissions": request.auth.get("permissions", [])}})


@extend_schema(tags=["Authentication"], summary="Accept a staff invitation", description="Uses a one-time invitation token to set the staff password and issue JWT tokens.", request=InviteAcceptSerializer, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT}, auth=[])
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def invitation_accept(request):
    serializer = InviteAcceptSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    digest = hashlib.sha256(serializer.validated_data["token"].encode()).hexdigest()
    invitation = Invitation.objects.select_related("user").filter(token_digest=digest, accepted_at__isnull=True).first()
    if not invitation or invitation.expires_at <= timezone.now() or invitation.user.is_active:
        return Response({"detail": "This invitation has expired or has already been used."}, status=400)
    user = invitation.user
    user.set_password(serializer.validated_data["password"])
    user.is_active = True
    user.save(update_fields=["password", "is_active"])
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
    return token_response(user, issue_staff_tokens(user))


@extend_schema(tags=["User management"], summary="List staff or invite an account", description="Lists accounts within the caller's station scope or creates a station-assigned staff/courier invitation by email.", request=StaffInviteSerializer, responses={200: OpenApiTypes.OBJECT, 201: OpenApiTypes.OBJECT})
@api_view(["GET", "POST"])
def staff_list_create(request):
    if request.method == "GET":
        denied = permission_denied(request.user, "users.view")
        if denied:
            return denied
        qs = visible_staff(request.user)
        role_filter = request.query_params.get("role")
        if role_filter:
            qs = qs.filter(staff_profile__role=role_filter)
        return Response({"users": [staff_user_data(user) for user in qs.order_by("first_name", "last_name", "username")]})
    denied = permission_denied(request.user, "users.invite")
    if denied:
        return denied
    serializer = StaffInviteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    role, station = staff_role(request.user)
    target_role = serializer.validated_data["role"]
    if not request.user.is_superuser:
        if target_role in {StaffProfile.Role.ADMIN, StaffProfile.Role.COURIER}:
            return Response({"role": ["Only a super administrator can create administrators or couriers."]}, status=403)
        if serializer.validated_data.get("station") != station:
            return Response({"station": ["You can only invite staff to your assigned station."]}, status=403)
    invited_station = serializer.validated_data.get("station")
    if not invited_station:
        return Response({"station": ["Assign each staff member to a station."]}, status=400)
    email = serializer.validated_data["email"].lower()
    if get_user_model().objects.filter(email__iexact=email).exists():
        return Response({"email": ["An account already uses this email address."]}, status=400)
    base = email.split("@", 1)[0].lower()
    username = serializer.validated_data.get("username") or "".join(c for c in base if c.isalnum() or c in "._-")[:120] or "staff"
    if get_user_model().objects.filter(username__iexact=username).exists():
        return Response({"username": ["An account already uses this username."]}, status=400)
    candidate, suffix = username, 1
    while get_user_model().objects.filter(username__iexact=candidate).exists():
        suffix += 1
        candidate = f"{username[:110]}{suffix}"
    user = get_user_model().objects.create_user(username=candidate, email=email,
        first_name=serializer.validated_data["first_name"], last_name=serializer.validated_data.get("last_name", ""), is_active=False)
    user.set_unusable_password()
    user.save(update_fields=["password"])
    StaffProfile.objects.create(user=user, station=invited_station, role=target_role)
    raw_token = secrets.token_urlsafe(36)
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = timezone.now() + timedelta(hours=72)
    invitation, _ = Invitation.objects.update_or_create(user=user, defaults={"token_digest": digest, "created_by": request.user, "expires_at": expires_at, "accepted_at": None})
    invite_url = f"{settings.SITE_URL}/invite/accept/?token={raw_token}"
    body = f"Hello {user.first_name},\n\n{request.user.get_full_name() or request.user.username} invited you to Transcitis Courier Operations as {user.staff_profile.get_role_display()} at {invited_station.name}.\n\nAccept your invitation and set a password within 72 hours:\n{invite_url}\n"
    email_sent = True
    try:
        send_mail("Your Transcitis staff invitation", body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
    except Exception:
        email_sent = False
    return Response({"user": staff_user_data(user), "email_sent": email_sent,
                     "invitation_url": invite_url if not email_sent or settings.DEBUG else None,
                     "detail": "Invitation created." if email_sent else "Invitation created, but email delivery failed. Check SMTP settings and resend."}, status=201)


@extend_schema(tags=["User management"], summary="Update role, station or access", description="Updates an account's role, station assignment or active status within the caller's administrative scope.", request=StaffUpdateSerializer, responses={200: OpenApiTypes.OBJECT})
@api_view(["PATCH"])
def staff_update(request, user_id):
    denied = permission_denied(request.user, "users.manage")
    if denied:
        return denied
    target = manageable_staff(request.user).filter(pk=user_id).first()
    if not target:
        return Response({"detail": "Staff account not found or outside your station."}, status=404)
    serializer = StaffUpdateSerializer(data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    role, station = staff_role(request.user)
    changes = serializer.validated_data
    if not request.user.is_superuser:
        if changes.get("station", target.staff_profile.station) != station:
            return Response({"station": ["Staff must remain assigned to your station."]}, status=403)
        if changes.get("role", target.staff_profile.role) in {StaffProfile.Role.ADMIN, StaffProfile.Role.COURIER}:
            return Response({"role": ["Only a super administrator can assign administrator or courier roles."]}, status=403)
    if "role" in changes:
        target.staff_profile.role = changes["role"]
    if "station" in changes:
        if changes["station"] is None:
            return Response({"station": ["Staff must be assigned to a station."]}, status=400)
        target.staff_profile.station = changes["station"]
    if "is_active" in changes:
        target.is_active = changes["is_active"]
    with transaction.atomic():
        target.save(update_fields=["is_active"] if "is_active" in changes else [])
        if "role" in changes or "station" in changes:
            target.staff_profile.save()
    return Response({"user": staff_user_data(target)})


@extend_schema(tags=["User management"], summary="View or configure role permissions", description="Super administrator only. Read the permission catalog and built-in role grants, or replace the grants for one role. Changes are enforced by protected APIs immediately and appear in newly issued JWTs.", request=RolePermissionUpdateSerializer, responses={200: OpenApiTypes.OBJECT})
@api_view(["GET", "PUT"])
def role_permissions(request):
    if not request.user.is_superuser:
        return Response({"detail": "Only the super administrator can manage role permissions."}, status=403)
    if request.method == "GET":
        configured = {item.role: item.permissions for item in RolePermission.objects.all()}
        roles = [{"key": key, "label": label, "permissions": configured.get(key, DEFAULT_ROLE_PERMISSIONS.get(key, []))} for key, label in StaffProfile.Role.choices]
        modules = {}
        for permission in PERMISSION_CATALOG:
            modules.setdefault(permission["module"], []).append(permission)
        return Response({"roles": roles, "modules": modules, "permissions": PERMISSION_CATALOG})
    serializer = RolePermissionUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    role = serializer.validated_data["role"]
    record, _ = RolePermission.objects.update_or_create(role=role, defaults={"permissions": serializer.validated_data["permissions"]})
    return Response({"role": record.role, "label": record.get_role_display(), "permissions": record.permissions, "updated_at": record.updated_at})


@extend_schema(tags=["User management"], summary="List station-scoped drivers", description="Lists active courier accounts. Super administrators can list all drivers; station staff only see drivers assigned to their own station. Use the station query parameter to filter a super administrator directory by station.", responses={200: DriverSerializer(many=True)}, methods=["GET"])
@extend_schema(tags=["User management"], summary="Add a driver", description="Creates an active driver account with phone number, plate number and home station. No email invitation is sent. Super administrator only.", request=DriverCreateSerializer, responses={201: DriverSerializer}, methods=["POST"])
@api_view(["GET", "POST"])
def driver_directory(request):
    if request.method == "POST":
        if not request.user.is_superuser:
            return Response({"detail": "Only the super administrator can create drivers."}, status=403)
        serializer = DriverCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone_number"].strip()
        if StaffProfile.objects.filter(phone_number=phone).exists():
            return Response({"phone_number": ["A driver already uses this phone number."]}, status=400)
        digits = "".join(ch for ch in phone if ch.isdigit())
        base = f"driver-{digits}"[:140] or f"driver-{secrets.token_hex(4)}"
        username, suffix = base, 1
        User = get_user_model()
        while User.objects.filter(username__iexact=username).exists():
            suffix += 1
            username = f"{base[:140]}-{suffix}"
        user = User.objects.create_user(username=username, email="", first_name=serializer.validated_data["first_name"].strip(), last_name=serializer.validated_data.get("last_name", "").strip(), is_active=True)
        user.set_unusable_password()
        user.save(update_fields=["password"])
        profile = StaffProfile.objects.create(user=user, station=serializer.validated_data["station"], role=StaffProfile.Role.COURIER, phone_number=phone, plate_number=serializer.validated_data["plate_number"].strip().upper())
        return Response({"id": user.id, "name": user.get_full_name() or user.username, "username": username, "email": user.email, "phone_number": profile.phone_number, "plate_number": profile.plate_number, "role": profile.role, "station": profile.station.name, "station_id": profile.station_id, "is_active": user.is_active}, status=201)
    if not request.user.is_superuser:
        denied = permission_denied(request.user, "trips.view")
        if denied:
            return denied
    if request.user.is_superuser:
        profiles = StaffProfile.objects.filter(role=StaffProfile.Role.COURIER).select_related("user", "station")
    else:
        station = staff_station(request.user)
        if not station or staff_role(request.user)[0] not in {StaffProfile.Role.ADMIN, StaffProfile.Role.SUPERVISOR, StaffProfile.Role.STAFF}:
            return Response({"detail": "Station operations access is required."}, status=403)
        profiles = StaffProfile.objects.filter(role=StaffProfile.Role.COURIER, user__is_active=True, station=station).select_related("user", "station")
    station_id = request.query_params.get("station")
    if station_id:
        current_station = staff_station(request.user)
        if not request.user.is_superuser and str(current_station.id if current_station else "") != station_id:
            return Response({"detail": "You can only view drivers assigned to your station."}, status=403)
        profiles = profiles.filter(station_id=station_id)
    return Response([{"id": p.user_id, "name": p.user.get_full_name() or p.user.username,
                      "username": p.user.username, "email": p.user.email,
                      "phone_number": p.phone_number, "plate_number": p.plate_number,
                      "role": p.role, "station": p.station.name if p.station else None,
                      "station_id": p.station_id, "is_active": p.user.is_active} for p in profiles])


@extend_schema(tags=["User management"], summary="Export driver directory", description="Downloads driver names, phone numbers, plate numbers, home stations and access status as CSV. Super administrator only.", responses={200: OpenApiTypes.BINARY})
@api_view(["GET"])
def driver_export(request):
    if not request.user.is_superuser:
        return Response({"detail": "Only the super administrator can export the driver directory."}, status=403)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="transcitis-drivers.csv"'
    writer = csv.writer(response)
    writer.writerow(["Driver", "Phone number", "Plate number", "Home station", "Access"])
    profiles = StaffProfile.objects.filter(role=StaffProfile.Role.COURIER).select_related("user", "station").order_by("user__first_name", "user__last_name")
    for profile in profiles:
        values = [profile.user.get_full_name() or profile.user.username, profile.phone_number, profile.plate_number, profile.station.name if profile.station else "", "Active" if profile.user.is_active else "Suspended"]
        writer.writerow([f"'{value}" if str(value).startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
    return response


@extend_schema(tags=["Pricing"], summary="List or create item categories", description="Returns categories with approved charges. Super administrators may request all categories using all=true and may create catalog entries.", request=ItemCategorySerializer, responses={200: ItemCategorySerializer(many=True), 201: ItemCategorySerializer})
@api_view(["GET", "POST"])
def item_category_list(request):
    if request.method == "GET":
        qs = ItemCategory.objects.all() if request.user.is_superuser and request.query_params.get("all") == "true" else ItemCategory.objects.filter(is_active=True, charge__isnull=False)
        return Response(ItemCategorySerializer(qs, many=True).data)
    if not request.user.is_superuser:
        return Response({"detail": "Only the super administrator can change the approved category price list."}, status=403)
    serializer = ItemCategorySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data.get("charge") is None and serializer.validated_data.get("is_active"):
        return Response({"charge": ["Add an approved charge before activating a category."]}, status=400)
    return Response(ItemCategorySerializer(serializer.save()).data, status=201)


@extend_schema(tags=["Pricing"], summary="Update an item category mapping", description="Super administrator only. A category must have a configured charge before it can be activated.", request=ItemCategorySerializer, responses={200: ItemCategorySerializer})
@api_view(["PATCH"])
def item_category_update(request, category_id):
    if not request.user.is_superuser:
        return Response({"detail": "Only the super administrator can change the approved category price list."}, status=403)
    category = ItemCategory.objects.filter(pk=category_id).first()
    if not category:
        return Response({"detail": "Category not found."}, status=404)
    serializer = ItemCategorySerializer(category, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data.get("is_active", category.is_active) and serializer.validated_data.get("charge", category.charge) is None:
        return Response({"charge": ["Add an approved charge before activating a category."]}, status=400)
    return Response(ItemCategorySerializer(serializer.save()).data)


@extend_schema(tags=["Pricing"], responses={200: OpenApiTypes.BINARY})
@api_view(["GET"])
def item_category_export(request):
    qs = ItemCategory.objects.filter(is_active=True, charge__isnull=False)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="transcitis-category-charge-mapping.csv"'
    writer = csv.writer(response)
    writer.writerow(["Item category", "Code", "Description", "Charge (NGN)"])
    for item in qs:
        writer.writerow([item.name, item.code, item.description, item.charge])
    return response


@extend_schema(
    tags=["Stations"],
    summary="List stations or create a station",
    description="Lists active stations for users with station-view access. Only the super administrator can create a station. Station codes are normalized to uppercase and must be unique.",
    request=StationCreateSerializer,
    responses={200: StationSerializer(many=True), 201: StationSerializer, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT},
)
@api_view(["GET", "POST"])
def station_list(request):
    if request.method == "GET":
        denied = permission_denied(request.user, "stations.view")
        if denied:
            return denied
        return Response(StationSerializer(Station.objects.filter(is_active=True), many=True).data)

    if not request.user.is_superuser:
        return Response({"detail": "Only the super administrator can create stations."}, status=403)
    serializer = StationCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    station = serializer.save()
    return Response(StationSerializer(station).data, status=201)


@extend_schema(
    tags=["Stations"],
    summary="Update or delete a station",
    description="Only the super administrator can update or delete a station. Deletion is blocked while the station is referenced by staff, parcels, trips, or parcel history.",
    request=StationCreateSerializer,
    responses={200: StationSerializer, 204: None, 400: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT, 404: OpenApiTypes.OBJECT, 409: OpenApiTypes.OBJECT},
)
@api_view(["PATCH", "DELETE"])
def station_detail(request, station_id):
    if not request.user.is_superuser:
        return Response({"detail": "Only the super administrator can edit or delete stations."}, status=403)
    try:
        station = Station.objects.get(pk=station_id)
    except Station.DoesNotExist:
        return Response({"detail": "Station not found."}, status=404)

    if request.method == "PATCH":
        serializer = StationCreateSerializer(station, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        station = serializer.save()
        return Response(StationSerializer(station).data)

    references = {
        "staff": station.staff.count(),
        "parcels": station.outbound_parcels.count() + station.inbound_parcels.count(),
        "trips": station.departing_trips.count() + station.arriving_trips.count(),
        "parcel history records": station.parcelevent_set.count(),
    }
    used_by = [f"{count} {label}" for label, count in references.items() if count]
    if used_by:
        return Response({"detail": f"This station is in use and cannot be deleted: {', '.join(used_by)}. Reassign or resolve these records first."}, status=409)
    try:
        station.delete()
    except ProtectedError:
        return Response({"detail": "This station is in use and cannot be deleted. Resolve its linked records first."}, status=409)
    return Response(status=204)


@extend_schema(tags=["Overview"], responses={200: OpenApiTypes.OBJECT})
@api_view(["GET"])
def dashboard(request):
    denied = permission_denied(request.user, ["parcels.view", "parcels.view_assigned"])
    if denied:
        return denied
    parcels = visible_parcels(request.user)
    status_counts = {row["status"]: row["count"] for row in parcels.values("status").annotate(count=Count("id"))}
    data = {
        "total": parcels.count(),
        "in_transit": parcels.filter(status=Parcel.Status.ON_TRIP).count(),
        "awaiting_pickup": parcels.filter(status=Parcel.Status.PICKUP).count(),
        "out_for_delivery": parcels.filter(status=Parcel.Status.OUT).count(),
        "exceptions": OperationalException.objects.filter(parcel__in=parcels, is_resolved=False).count(),
        "delivered_today": parcels.filter(status__in=[Parcel.Status.DELIVERED, Parcel.Status.COLLECTED], updated_at__date=timezone.localdate()).count(),
        "status_counts": status_counts,
        "recent_parcels": ParcelSerializer(parcels[:7], many=True).data,
        "stations": StationSerializer(Station.objects.filter(is_active=True), many=True).data,
    }
    return Response(data)


@extend_schema(tags=["Parcels"], parameters=[OpenApiParameter("q", str, description="Parcel ID, sender or receiver phone/name"), OpenApiParameter("status", str, description="Filter by parcel status")], responses={200: ParcelSerializer(many=True)}, methods=["GET"])
@extend_schema(tags=["Parcels"], request=ParcelCreateSerializer, responses={201: ParcelSerializer}, methods=["POST"])
@api_view(["GET", "POST"])
def parcel_list(request):
    if request.method == "GET":
        denied = permission_denied(request.user, ["parcels.view", "parcels.view_assigned"])
        if denied:
            return denied
        qs = visible_parcels(request.user)
        q = request.query_params.get("q", "").strip()
        state = request.query_params.get("status", "").strip()
        if q:
            qs = qs.filter(Q(parcel_id__icontains=q) | Q(sender_name__icontains=q) | Q(receiver_name__icontains=q) | Q(sender_phone__icontains=q) | Q(receiver_phone__icontains=q))
        if state:
            qs = qs.filter(status=state)
        return Response(ParcelSerializer(qs[:100], many=True).data)
    denied = permission_denied(request.user, "parcels.create")
    if denied:
        return denied
    serializer = ParcelCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and serializer.validated_data["origin"] != station:
        return Response({"origin": ["Parcels must be registered at your assigned station."]}, status=403)
    if serializer.validated_data["origin"] == serializer.validated_data["destination"]:
        return Response({"destination": ["Origin and destination must be different stations."]}, status=400)
    parcel = serializer.save(created_by=request.user)
    add_event(parcel, request.user, note="Parcel registered", station=parcel.origin)
    return Response(ParcelSerializer(parcel).data, status=201)


@extend_schema(tags=["Parcels"], responses={200: ParcelSerializer})
@api_view(["GET"])
def parcel_detail(request, parcel_id):
    denied = permission_denied(request.user, ["parcels.view", "parcels.view_assigned"])
    if denied:
        return denied
    parcel = visible_parcels(request.user).filter(parcel_id=parcel_id).first()
    if not parcel:
        return Response({"detail": "Parcel not found."}, status=404)
    return Response(ParcelSerializer(parcel).data)


@extend_schema(tags=["Receipts"], summary="Render and record a parcel receipt", description="Returns printable two-page 80 mm receipt HTML with a Code 128 barcode. Non-superusers may print once; only a superuser may reprint.", request=None, responses={200: OpenApiTypes.OBJECT, 403: OpenApiTypes.OBJECT})
@api_view(["POST"])
def parcel_receipt(request, parcel_id):
    denied = permission_denied(request.user, "parcels.receipt")
    if denied:
        return denied
    with transaction.atomic():
        parcel = visible_parcels(request.user).select_for_update().select_related("origin", "destination", "item_category").filter(parcel_id=parcel_id).first()
        if not parcel:
            return Response({"detail": "Parcel not found."}, status=404)
        if parcel.receipt_print_count > 0 and not request.user.is_superuser:
            return Response({"detail": "This receipt has already been printed. Ask the super administrator to reprint it."}, status=403)
        now = timezone.now()
        reprint = parcel.receipt_print_count > 0
        ReceiptPrint.objects.create(parcel=parcel, printed_by=request.user, is_reprint=reprint)
        parcel.receipt_print_count += 1
        parcel.first_receipt_printed_at = parcel.first_receipt_printed_at or now
        parcel.last_receipt_printed_at = now
        parcel.last_receipt_printed_by = request.user
        parcel.save(update_fields=["receipt_print_count", "first_receipt_printed_at", "last_receipt_printed_at", "last_receipt_printed_by", "updated_at"])
    code = barcode.get("code128", parcel.parcel_id, writer=SVGWriter())
    barcode_svg = code.render({"write_text": False, "module_width": 0.22, "module_height": 13, "quiet_zone": 2.5}).decode("utf-8")
    html = render_to_string("operations/receipt.html", {"parcel": parcel, "barcode_svg": barcode_svg, "printed_by": request.user.get_full_name() or request.user.username, "reprint": reprint})
    return Response({"html": html, "receipt_print_count": parcel.receipt_print_count, "is_reprint": reprint})


@extend_schema(tags=["Parcels"], request=ParcelStatusSerializer, responses={200: ParcelSerializer})
@api_view(["POST"])
def parcel_status(request, parcel_id):
    denied = permission_denied(request.user, "parcels.update")
    if denied:
        return denied
    parcel = visible_parcels(request.user).filter(parcel_id=parcel_id).first()
    if not parcel:
        return Response({"detail": "Parcel not found."}, status=404)
    serializer = ParcelStatusSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    target = serializer.validated_data["status"]
    transitions = {
        Parcel.Status.REGISTERED: {Parcel.Status.READY},
        Parcel.Status.READY: set(),
        Parcel.Status.ON_TRIP: set(),
        Parcel.Status.RECEIVED: set(),
        Parcel.Status.PICKUP: set(),
        Parcel.Status.OUT: set(),
        Parcel.Status.COLLECTED: set(),
        Parcel.Status.DELIVERED: set(),
    }
    if target not in transitions.get(parcel.status, set()):
        return Response({"detail": f"Status cannot move from {parcel.get_status_display()} to {dict(Parcel.Status.choices).get(target, target)} through this action."}, status=400)
    parcel.status = target
    parcel.save(update_fields=["status", "updated_at"])
    add_event(parcel, request.user, note=serializer.validated_data.get("note", ""), station=staff_station(request.user))
    return Response(ParcelSerializer(parcel).data)


@extend_schema(tags=["Trips"], responses={200: TripSerializer(many=True)}, methods=["GET"])
@extend_schema(tags=["Trips"], request=TripSerializer, responses={201: TripSerializer}, methods=["POST"])
@api_view(["GET", "POST"])
def trip_list(request):
    if request.method == "GET":
        denied = permission_denied(request.user, "trips.view")
        if denied:
            return denied
        return Response(TripSerializer(visible_trips(request.user)[:100], many=True).data)
    denied = permission_denied(request.user, "trips.manage")
    if denied:
        return denied
    serializer = TripSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and serializer.validated_data["origin"] != station:
        return Response({"detail": "Trips must depart from your assigned station."}, status=403)
    driver = serializer.validated_data.get("driver")
    if driver:
        try:
            profile = driver.staff_profile
        except StaffProfile.DoesNotExist:
            profile = None
        if not profile or profile.role != StaffProfile.Role.COURIER or not driver.is_active:
            return Response({"driver": ["Choose an active user with the Courier role."]}, status=400)
        if profile.station_id and profile.station_id != serializer.validated_data["origin"].id:
            return Response({"driver": ["Assign a courier based at the trip origin station."]}, status=400)
    trip = serializer.save(created_by=request.user)
    return Response(TripSerializer(trip).data, status=201)


@extend_schema(tags=["Trips"], summary="Scan parcel onto a preparing trip", description="Adds an eligible route-matched parcel to the manifest and returns both updated trip and parcel details for immediate scan feedback.", request=ScanSerializer, responses={200: OpenApiTypes.OBJECT})
@api_view(["POST"])
def trip_add_parcel(request, trip_id):
    denied = permission_denied(request.user, "trips.manage")
    if denied:
        return denied
    trip = visible_trips(request.user).filter(trip_id=trip_id).first()
    if not trip:
        return Response({"detail": "Trip not found."}, status=404)
    if trip.status != Trip.Status.PREPARING:
        return Response({"detail": "Parcels can only be added while a trip is preparing."}, status=400)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and station != trip.origin:
        return Response({"detail": "Only staff at the origin station can update this manifest."}, status=403)
    serializer = ScanSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    parcel = Parcel.objects.filter(parcel_id=serializer.validated_data["parcel_id"]).first()
    if not parcel or not can_access_parcel(request.user, parcel):
        return Response({"detail": "Parcel not found."}, status=404)
    if parcel.origin_id != trip.origin_id or parcel.destination_id != trip.destination_id:
        return Response({"detail": "Parcel route does not match this trip."}, status=400)
    if parcel.status not in {Parcel.Status.REGISTERED, Parcel.Status.READY}:
        return Response({"detail": "Parcel is already in the delivery journey."}, status=400)
    if parcel.trips.exclude(pk=trip.pk).filter(status=Trip.Status.PREPARING).exists():
        return Response({"detail": "Parcel is already assigned to another preparing trip."}, status=400)
    trip.parcels.add(parcel)
    parcel.status = Parcel.Status.READY
    parcel.save(update_fields=["status", "updated_at"])
    add_event(parcel, request.user, note=f"Added to manifest {trip.trip_id}", station=trip.origin)
    return Response({"trip": TripSerializer(trip).data, "parcel": ParcelSerializer(parcel).data})


@extend_schema(tags=["Trips"], request=None, responses={200: TripSerializer})
@api_view(["POST"])
def trip_dispatch(request, trip_id):
    denied = permission_denied(request.user, "trips.manage")
    if denied:
        return denied
    trip = visible_trips(request.user).filter(trip_id=trip_id).first()
    if not trip:
        return Response({"detail": "Trip not found."}, status=404)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and station != trip.origin:
        return Response({"detail": "Only staff at the origin station can dispatch this trip."}, status=403)
    if trip.status != Trip.Status.PREPARING or not trip.parcels.exists() or not trip.driver_id:
        if not trip.driver_id:
            return Response({"detail": "Assign a courier before dispatching this trip."}, status=400)
        return Response({"detail": "Add at least one parcel to a preparing trip before dispatch."}, status=400)
    with transaction.atomic():
        trip.status, trip.departed_at = Trip.Status.IN_TRANSIT, timezone.now()
        trip.save(update_fields=["status", "departed_at"])
        for parcel in trip.parcels.all():
            parcel.status = Parcel.Status.ON_TRIP
            parcel.save(update_fields=["status", "updated_at"])
            add_event(parcel, request.user, note=f"Departed on {trip.trip_id}", station=trip.origin)
    return Response(TripSerializer(trip).data)


@extend_schema(tags=["Receiving"], request=ScanSerializer, responses={200: ParcelSerializer})
@api_view(["POST"])
def receive_scan(request):
    denied = permission_denied(request.user, "receiving.scan")
    if denied:
        return denied
    serializer = ScanSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    parcel = Parcel.objects.filter(parcel_id=serializer.validated_data["parcel_id"]).first()
    if not parcel or not can_access_parcel(request.user, parcel):
        return Response({"detail": "Parcel not found."}, status=404)
    if parcel.status != Parcel.Status.ON_TRIP:
        return Response({"detail": "Only parcels on a trip can be received."}, status=400)
    station = staff_station(request.user)
    if station and station.id != parcel.destination_id:
        return Response({"detail": "This parcel is bound for another station."}, status=400)
    kind = serializer.validated_data.get("kind")
    note = serializer.validated_data.get("note", "")
    with transaction.atomic():
        parcel.status = Parcel.Status.RECEIVED
        parcel.save(update_fields=["status", "updated_at"])
        add_event(parcel, request.user, note="Arrival scan complete", station=station or parcel.destination)
        if kind:
            OperationalException.objects.create(parcel=parcel, kind=kind, note=note or "Flagged during receiving", created_by=request.user)
    return Response(ParcelSerializer(parcel).data)


@extend_schema(tags=["Receiving"], request=None, responses={200: TripSerializer})
@api_view(["POST"])
def trip_arrive(request, trip_id):
    denied = permission_denied(request.user, "receiving.scan")
    if denied:
        return denied
    trip = visible_trips(request.user).filter(trip_id=trip_id).first()
    if not trip:
        return Response({"detail": "Trip not found."}, status=404)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and station != trip.destination:
        return Response({"detail": "Only staff at the destination station can mark this trip arrived."}, status=403)
    if trip.status != Trip.Status.IN_TRANSIT:
        return Response({"detail": "Only an in-transit trip can be marked arrived."}, status=400)
    trip.status, trip.arrived_at = Trip.Status.ARRIVED, timezone.now()
    trip.save(update_fields=["status", "arrived_at"])
    return Response(TripSerializer(trip).data)


@extend_schema(tags=["Trips"], summary="Render a printable trip manifest", description="Returns A4 manifest HTML including route, courier, vehicle, parcel-level details and Code 128 barcodes.", request=None, responses={200: OpenApiTypes.OBJECT})
@api_view(["POST"])
def trip_manifest_print(request, trip_id):
    denied = permission_denied(request.user, "trips.view")
    if denied:
        return denied
    trip = visible_trips(request.user).filter(trip_id=trip_id).first()
    if not trip:
        return Response({"detail": "Trip not found."}, status=404)
    parcels = trip.parcels.select_related("origin", "destination", "item_category").order_by("parcel_id")
    barcode_rows = []
    for parcel in parcels:
        code = barcode.get("code128", parcel.parcel_id, writer=SVGWriter())
        svg = code.render({"write_text": False, "module_width": 0.18, "module_height": 9, "quiet_zone": 1.5}).decode("utf-8")
        barcode_rows.append((parcel.parcel_id, svg))
    html = render_to_string("operations/manifest.html", {"trip": trip, "parcels": parcels, "barcode_rows": barcode_rows, "printed_by": request.user.get_full_name() or request.user.username})
    return Response({"html": html, "trip_id": trip.trip_id, "parcel_count": parcels.count()})


@extend_schema(tags=["Handover"], request=HandoverSerializer, responses={200: ParcelSerializer})
@api_view(["POST"])
def parcel_handover(request, parcel_id):
    denied = permission_denied(request.user, "handover.verify")
    if denied:
        return denied
    parcel = visible_parcels(request.user).filter(parcel_id=parcel_id).first()
    if not parcel:
        return Response({"detail": "Parcel not found."}, status=404)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and station != parcel.destination:
        return Response({"detail": "Final handover must be recorded at the destination station."}, status=403)
    serializer = HandoverSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data["pin"] != parcel.handover_pin:
        return Response({"pin": ["The handover PIN does not match."]}, status=400)
    if parcel.delivery_method == Parcel.DeliveryMethod.PICKUP and parcel.status != Parcel.Status.PICKUP:
        return Response({"detail": "Parcel is not ready for station collection."}, status=400)
    if parcel.delivery_method == Parcel.DeliveryMethod.DOOR and parcel.status != Parcel.Status.OUT:
        return Response({"detail": "Parcel is not ready for courier handover."}, status=400)
    parcel.status = Parcel.Status.COLLECTED if parcel.delivery_method == Parcel.DeliveryMethod.PICKUP else Parcel.Status.DELIVERED
    parcel.save(update_fields=["status", "updated_at"])
    add_event(parcel, request.user, note=f"Verified handover to {serializer.validated_data['recipient_name']}", station=staff_station(request.user))
    return Response(ParcelSerializer(parcel).data)


@extend_schema(tags=["Handover"], request=None, responses={200: ParcelSerializer})
@api_view(["POST"])
def parcel_ready_handover(request, parcel_id):
    denied = permission_denied(request.user, "handover.verify")
    if denied:
        return denied
    parcel = visible_parcels(request.user).filter(parcel_id=parcel_id).first()
    if not parcel:
        return Response({"detail": "Parcel not found."}, status=404)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and station != parcel.destination:
        return Response({"detail": "Final handover must be prepared at the destination station."}, status=403)
    if parcel.delivery_method == Parcel.DeliveryMethod.PICKUP and parcel.status == Parcel.Status.RECEIVED:
        parcel.status = Parcel.Status.PICKUP
    elif parcel.delivery_method == Parcel.DeliveryMethod.DOOR and parcel.status in {Parcel.Status.RECEIVED, Parcel.Status.PICKUP}:
        parcel.status = Parcel.Status.OUT
    else:
        return Response({"detail": "Parcel is not ready to enter final handover."}, status=400)
    parcel.save(update_fields=["status", "updated_at"])
    add_event(parcel, request.user, note="Ready for final handover")
    return Response(ParcelSerializer(parcel).data)


@extend_schema(tags=["Handover"], request=CourierAssignSerializer, responses={200: ParcelSerializer})
@api_view(["POST"])
def parcel_assign_courier(request, parcel_id):
    denied = permission_denied(request.user, "courier.assign")
    if denied:
        return denied
    parcel = visible_parcels(request.user).filter(parcel_id=parcel_id).first()
    if not parcel:
        return Response({"detail": "Parcel not found."}, status=404)
    role, station = staff_role(request.user)
    if not request.user.is_superuser and station != parcel.destination:
        return Response({"detail": "Deliveries must be assigned at the destination station."}, status=403)
    if parcel.delivery_method != Parcel.DeliveryMethod.DOOR or parcel.status not in {Parcel.Status.RECEIVED, Parcel.Status.OUT}:
        return Response({"detail": "Only received doorstep deliveries can be assigned."}, status=400)
    serializer = CourierAssignSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    courier = StaffProfile.objects.select_related("user").filter(user__username=serializer.validated_data["username"], role=StaffProfile.Role.COURIER).first()
    if not courier:
        return Response({"username": ["Choose an existing staff account with the Courier role."]}, status=400)
    if courier.station_id and courier.station_id != parcel.destination_id:
        return Response({"username": ["Courier must be assigned to the parcel destination station."]}, status=400)
    parcel.courier = courier.user
    parcel.status = Parcel.Status.OUT
    parcel.save(update_fields=["courier", "status", "updated_at"])
    add_event(parcel, request.user, note=f"Assigned to courier {courier.user.get_full_name() or courier.user.username}", station=parcel.destination)
    return Response(ParcelSerializer(parcel).data)


@extend_schema(tags=["Exceptions"], responses={200: ExceptionSerializer(many=True)}, methods=["GET"])
@extend_schema(tags=["Exceptions"], request=ExceptionCreateSerializer, responses={201: ExceptionSerializer}, methods=["POST"])
@api_view(["GET", "POST"])
def exception_list(request):
    denied = permission_denied(request.user, "exceptions.view")
    if denied:
        return denied
    qs = OperationalException.objects.select_related("parcel", "created_by")
    role, station = staff_role(request.user)
    if not request.user.is_superuser:
        qs = qs.filter(parcel__in=visible_parcels(request.user))
    if request.method == "GET":
        open_only = request.query_params.get("open", "")
        if open_only.lower() in {"true", "1"}:
            qs = qs.filter(is_resolved=False)
        return Response(ExceptionSerializer(qs[:100], many=True).data)
    serializer = ExceptionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    parcel = visible_parcels(request.user).filter(parcel_id=serializer.validated_data["parcel_id"]).first()
    if not parcel:
        return Response({"detail": "Parcel not found."}, status=404)
    item = OperationalException.objects.create(parcel=parcel, kind=serializer.validated_data["kind"], note=serializer.validated_data["note"], created_by=request.user)
    return Response(ExceptionSerializer(item).data, status=201)


@extend_schema(tags=["Exceptions"], request=ExceptionResolveSerializer, responses={200: ExceptionSerializer})
@api_view(["POST"])
def exception_resolve(request, exception_id):
    denied = permission_denied(request.user, "exceptions.resolve")
    if denied:
        return denied
    item = OperationalException.objects.filter(pk=exception_id).first()
    if not item or not can_access_parcel(request.user, item.parcel):
        return Response({"detail": "Exception not found."}, status=404)
    serializer = ExceptionResolveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item.is_resolved, item.resolution, item.resolved_by, item.resolved_at = True, serializer.validated_data["resolution"], request.user, timezone.now()
    item.save(update_fields=["is_resolved", "resolution", "resolved_by", "resolved_at"])
    return Response(ExceptionSerializer(item).data)


@extend_schema(tags=["Overview"], parameters=[OpenApiParameter("status", str, required=False)], responses={200: OpenApiTypes.BINARY})
@api_view(["GET"])
def parcel_export(request):
    denied = permission_denied(request.user, "reports.export")
    if denied:
        return denied
    qs = visible_parcels(request.user)
    state = request.query_params.get("status", "")
    if state:
        qs = qs.filter(status=state)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="transcitis-parcels.csv"'
    writer = csv.writer(response)
    writer.writerow(["Parcel ID", "Sender", "Receiver", "Origin", "Destination", "Status", "Item category", "Item description", "Weight kg", "Delivery method", "Charge", "Amount paid", "Paid", "Registered"])
    def csv_text(value):
        text = str(value or "")
        return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
    for item in qs.select_related("origin", "destination", "item_category")[:5000]:
        writer.writerow([csv_text(item.parcel_id), csv_text(item.sender_name), csv_text(item.receiver_name), csv_text(item.origin.name), csv_text(item.destination.name), csv_text(item.get_status_display()), csv_text(item.item_category.name), csv_text(item.description), item.weight_kg, csv_text(item.get_delivery_method_display()), item.charge, item.amount_paid, "Yes" if item.is_paid else "No", item.created_at.isoformat()])
    return response
