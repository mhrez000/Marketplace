"""DRF serializers — the shared data contract for the Android + iOS apps."""
from rest_framework import serializers

from apps.bookings.models import Booking
from apps.enquiries.models import Enquiry, Quote
from apps.profiles.models import CreativeProfile, Package
from apps.reviews.models import Review


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role_type = serializers.CharField()


class PackageSerializer(serializers.ModelSerializer):
    inclusions = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = ["id", "name", "base_price", "description", "inclusions"]

    def get_inclusions(self, obj):
        return obj.inclusion_list


class ReviewSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "rating", "title", "body", "verified", "client_name", "created_at"]

    def get_client_name(self, obj):
        return obj.client.get_full_name() or obj.client.email


class CreativeListSerializer(serializers.ModelSerializer):
    slug = serializers.CharField(source="workspace.slug")
    business_name = serializers.CharField(source="workspace.business_name")
    is_verified = serializers.BooleanField(source="workspace.is_verified")
    avg_rating = serializers.FloatField(read_only=True)
    review_count = serializers.IntegerField(read_only=True)
    location = serializers.CharField(source="location_label")

    class Meta:
        model = CreativeProfile
        fields = ["slug", "business_name", "headline", "primary_category", "location",
                  "starting_price", "accent", "is_featured", "is_verified",
                  "avg_rating", "review_count"]


class CreativeDetailSerializer(CreativeListSerializer):
    styles = serializers.SerializerMethodField()
    packages = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    response_hours = serializers.SerializerMethodField()

    class Meta(CreativeListSerializer.Meta):
        fields = CreativeListSerializer.Meta.fields + [
            "bio", "equipment", "languages", "service_radius_km",
            "styles", "packages", "reviews", "response_hours"]

    def get_styles(self, obj):
        return obj.style_list

    def get_packages(self, obj):
        pkgs = Package.objects.filter(service__workspace=obj.workspace)
        return PackageSerializer(pkgs, many=True).data

    def get_reviews(self, obj):
        return ReviewSerializer(obj.workspace.reviews.all()[:10], many=True).data

    def get_response_hours(self, obj):
        from apps.profiles.services import avg_response_hours
        return avg_response_hours(obj.workspace)


class EnquirySerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source="workspace.business_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Enquiry
        fields = ["id", "workspace_name", "event_type", "event_date", "location",
                  "budget_band", "message", "status", "status_display", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


class QuoteSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Quote
        fields = ["id", "title", "total", "deposit_amount", "status", "status_display", "expires_at"]


class BookingSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source="workspace.business_name", read_only=True)
    client_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "title", "workspace_name", "client_name", "status", "status_display",
                  "event_date", "location", "total", "deposit_amount", "created_at"]

    def get_client_name(self, obj):
        return obj.client.get_full_name() or obj.client.email
