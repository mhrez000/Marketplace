"""DRF serializers — the shared data contract for the Android + iOS apps."""
from rest_framework import serializers

from apps.bookings.models import Booking
from apps.enquiries.models import Enquiry, Quote
from apps.galleries.models import Asset, Gallery
from apps.messaging.models import Message, Thread
from apps.profiles.models import CreativeProfile, Package
from apps.reviews.models import Review


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role_type = serializers.CharField()
    is_creative = serializers.SerializerMethodField()
    workspace = serializers.SerializerMethodField()

    def get_is_creative(self, obj):
        from apps.core.selectors import get_active_workspace
        return get_active_workspace(obj) is not None

    def get_workspace(self, obj):
        from apps.core.selectors import get_active_workspace
        ws = get_active_workspace(obj)
        return {"slug": ws.slug, "business_name": ws.business_name} if ws else None


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
        # PUBLIC output (served on the unauthenticated creative profile). NEVER fall
        # back to the client's email — that lets anonymous users harvest reviewer
        # emails. Show first name + last initial, or a neutral label.
        first = (obj.client.first_name or "").strip()
        last = (obj.client.last_name or "").strip()
        if first and last:
            return f"{first} {last[:1]}."
        return first or "Verified client"


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
    is_favourited = serializers.SerializerMethodField()

    class Meta(CreativeListSerializer.Meta):
        fields = CreativeListSerializer.Meta.fields + [
            "bio", "equipment", "languages", "service_radius_km",
            "styles", "packages", "reviews", "response_hours", "is_favourited"]

    def get_is_favourited(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        from apps.marketplace.models import Favourite
        return Favourite.objects.filter(client=request.user, workspace=obj.workspace).exists()

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
    client_name = serializers.SerializerMethodField()
    event_type_display = serializers.CharField(source="get_event_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    quotes = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = ["id", "workspace_name", "client_name", "event_type", "event_type_display",
                  "event_date", "location", "budget_band", "message", "status",
                  "status_display", "created_at", "quotes"]
        read_only_fields = ["id", "status", "created_at"]

    def get_client_name(self, obj):
        return obj.client.get_full_name() or obj.client.email

    def get_quotes(self, obj):
        return QuoteSerializer(obj.quotes.all().order_by("-created_at"), many=True).data


class QuoteSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quote
        fields = ["id", "title", "total", "deposit_amount", "status", "status_display",
                  "expires_at", "is_expired"]


class GallerySummarySerializer(serializers.ModelSerializer):
    is_link_delivery = serializers.BooleanField(read_only=True)
    provider = serializers.SerializerMethodField()
    asset_count = serializers.SerializerMethodField()

    class Meta:
        model = Gallery
        fields = ["id", "title", "gallery_type", "is_link_delivery", "delivery_url",
                  "provider", "delivered_at", "asset_count"]

    def get_provider(self, obj):
        return obj.provider  # {"name": ..., "icon": ...}

    def get_asset_count(self, obj):
        return obj.assets.count()


class AssetSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = ["id", "title", "image_url", "video_url", "asset_type", "accent", "is_favourite"]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.image.url) if request else obj.image.url


class GalleryDetailSerializer(GallerySummarySerializer):
    assets = serializers.SerializerMethodField()

    class Meta(GallerySummarySerializer.Meta):
        fields = GallerySummarySerializer.Meta.fields + ["assets"]

    def get_assets(self, obj):
        return AssetSerializer(obj.assets.all(), many=True, context=self.context).data


class MessageSerializer(serializers.ModelSerializer):
    sender_is_me = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "body", "sender_is_me", "created_at"]

    def get_sender_is_me(self, obj):
        return obj.sender_id == self.context["request"].user.id


class ThreadListSerializer(serializers.ModelSerializer):
    other = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_at = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = ["id", "subject", "other", "last_message", "last_at", "unread"]

    def _user(self):
        return self.context["request"].user

    def get_other(self, obj):
        return obj.other_label(self._user())

    def get_last_message(self, obj):
        m = obj.last_message
        return m.body if m else ""

    def get_last_at(self, obj):
        m = obj.last_message
        return m.created_at if m else None

    def get_unread(self, obj):
        return obj.unread_for(self._user())


class ThreadDetailSerializer(serializers.ModelSerializer):
    other = serializers.SerializerMethodField()
    booking_id = serializers.SerializerMethodField()
    messages = serializers.SerializerMethodField()

    class Meta:
        model = Thread
        fields = ["id", "subject", "other", "booking_id", "messages"]

    def get_other(self, obj):
        return obj.other_label(self.context["request"].user)

    def get_booking_id(self, obj):
        return str(obj.booking_id) if obj.booking_id else None

    def get_messages(self, obj):
        return MessageSerializer(obj.messages.select_related("sender"),
                                 many=True, context=self.context).data


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
