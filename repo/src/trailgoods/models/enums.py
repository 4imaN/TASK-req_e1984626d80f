import enum


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    CHALLENGE_REQUIRED = "CHALLENGE_REQUIRED"


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    FORCED_LOGGED_OUT = "FORCED_LOGGED_OUT"


class BindingType(str, enum.Enum):
    STAFF_ID = "STAFF_ID"
    STUDENT_ID = "STUDENT_ID"


class BindingStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class VerificationProfileType(str, enum.Enum):
    PERSONAL = "PERSONAL"
    ENTERPRISE = "ENTERPRISE"


class VerificationStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ItemType(str, enum.Enum):
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"
    LIVE_PET = "LIVE_PET"


class ItemStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    ARCHIVED = "ARCHIVED"


class SKUStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PriceBookStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PriceTargetType(str, enum.Enum):
    ITEM = "ITEM"
    SKU = "SKU"


class WarehouseStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LotStatus(str, enum.Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class MovementType(str, enum.Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"
    ADJUSTMENT_POSITIVE = "ADJUSTMENT_POSITIVE"
    ADJUSTMENT_NEGATIVE = "ADJUSTMENT_NEGATIVE"
    ROLLBACK = "ROLLBACK"


class InboundDocStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CANCELED = "CANCELED"


class InboundSourceType(str, enum.Enum):
    PURCHASE = "PURCHASE"
    RETURN = "RETURN"
    TRANSFER_IN = "TRANSFER_IN"
    ROLLBACK = "ROLLBACK"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class OutboundDocStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CANCELED = "CANCELED"


class OutboundSourceType(str, enum.Enum):
    SALE = "SALE"
    TRANSFER_OUT = "TRANSFER_OUT"
    DAMAGE = "DAMAGE"
    WRITE_OFF = "WRITE_OFF"
    ORDER_DEDUCTION = "ORDER_DEDUCTION"


class StocktakeStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    COUNTING = "COUNTING"
    RECONCILED = "RECONCILED"
    POSTED = "POSTED"
    CANCELED = "CANCELED"


class VarianceReason(str, enum.Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"
    FOUND = "FOUND"
    EXPIRED = "EXPIRED"
    THEFT = "THEFT"
    COUNTING_ERROR = "COUNTING_ERROR"
    OTHER = "OTHER"


class ReservationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    RESERVED = "RESERVED"
    DEDUCTED = "DEDUCTED"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"


class AssetKind(str, enum.Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    ATTACHMENT = "ATTACHMENT"
    VERIFICATION_ID = "VERIFICATION_ID"
    THUMBNAIL = "THUMBNAIL"


class AssetStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SOFT_DELETED = "SOFT_DELETED"
    QUARANTINED = "QUARANTINED"


class AssetPurpose(str, enum.Enum):
    CATALOG = "CATALOG"
    VERIFICATION = "VERIFICATION"
    REVIEW_ATTACHMENT = "REVIEW_ATTACHMENT"
    GENERAL = "GENERAL"


class WatermarkPolicy(str, enum.Enum):
    NONE = "NONE"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"


class ShareLinkStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"
    EXHAUSTED = "EXHAUSTED"


class UploadSessionStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ReviewStatus(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"
    REMOVED = "REMOVED"


class ReportTargetType(str, enum.Enum):
    REVIEW = "REVIEW"
    ITEM = "ITEM"
    ASSET = "ASSET"
    USER = "USER"


class ReportStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ACTIONED = "ACTIONED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class AppealStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECIDED = "DECIDED"
    CLOSED = "CLOSED"


class AuditResult(str, enum.Enum):
    SUCCESS = "SUCCESS"
    DENIED = "DENIED"
    FAILED = "FAILED"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CANCELED = "CANCELED"


class ItemAttributeScope(str, enum.Enum):
    ITEM = "ITEM"
    SPU = "SPU"
    SKU = "SKU"
