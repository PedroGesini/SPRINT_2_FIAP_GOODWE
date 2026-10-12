import enum


class Role(str, enum.Enum):
    PLATFORM_ADMIN = "platform_admin"
    SYNDIC = "syndic"
    RESIDENT = "resident"


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    REJECTED = "rejected"


class ChargerStatus(str, enum.Enum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"


class SessionStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SessionSource(str, enum.Enum):
    SIMULATION = "simulation"
    MANUAL = "manual"
    INTEGRATION = "integration"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PENDING = "pending"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class InvoiceItemKind(str, enum.Enum):
    ENERGY = "energy"
    FIXED_FEE = "fixed_fee"
    SHARED_COST = "shared_cost"
    ADJUSTMENT = "adjustment"
