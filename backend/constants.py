"""
Application-wide constants and enumerations
"""

# ===========================================
# API Response Status Constants
# ===========================================

# Success status
STATUS_SUCCESS = "success"

# Error status
STATUS_ERROR = "error"

# No data available
STATUS_NO_DATA = "no_data"

# Pending/processing
STATUS_PENDING = "pending"


# ===========================================
# NDVI Status Classifications
# ===========================================

NDVI_STATUS_OPTIMAL = "optimal"           # > 0.6
NDVI_STATUS_HIGH = "high"                 # 0.3 - 0.6
NDVI_STATUS_LOW = "low"                   # 0.1 - 0.3
NDVI_STATUS_CRITICAL_LOW = "critical_low" # < 0.1
NDVI_STATUS_WATER = "water"               # NDVI < 0 near water
NDVI_STATUS_BARE_SOIL = "bare_soil"       # NDVI < 0 on land
NDVI_STATUS_DEFAULT = "default"


# ===========================================
# BIOPAR Status Classifications
# ===========================================

BIOPAR_STATUS_OPTIMAL = "optimal"
BIOPAR_STATUS_GOOD = "good"
BIOPAR_STATUS_MODERATE = "moderate"
BIOPAR_STATUS_LOW = "low"
BIOPAR_STATUS_CRITICAL = "critical"
BIOPAR_STATUS_UNKNOWN = "unknown"


# ===========================================
# HTTP Error Messages
# ===========================================

ERROR_NO_DATA = "No data available"
ERROR_INVALID_PARAMETERS = "Invalid parameters"
ERROR_PROCESSING_FAILED = "Processing failed"
ERROR_UNAUTHORIZED = "Unauthorized"
ERROR_NOT_FOUND = "Not found"


# ===========================================
# NDVI Value Thresholds
# ===========================================

NDVI_THRESHOLD_OPTIMAL = 0.6
NDVI_THRESHOLD_HIGH = 0.3
NDVI_THRESHOLD_LOW = 0.1
NDVI_THRESHOLD_CRITICAL = 0.0


# ===========================================
# Date Format Constants
# ===========================================

DATE_FORMAT_ISO = "%Y-%m-%d"
DATE_FORMAT_DISPLAY = "%d.%m.%Y"
DATETIME_FORMAT_ISO = "%Y-%m-%dT%H:%M:%S"


# ===========================================
# Supported BIOPAR Types
# ===========================================

BIOPAR_TYPE_FAPAR = "FAPAR"
BIOPAR_TYPE_LAI = "LAI"
BIOPAR_TYPE_FCOVER = "FCOVER"
BIOPAR_TYPE_CCC = "CCC"
BIOPAR_TYPE_CWC = "CWC"

BIOPAR_TYPES = {
    BIOPAR_TYPE_FAPAR,
    BIOPAR_TYPE_LAI,
    BIOPAR_TYPE_FCOVER,
    BIOPAR_TYPE_CCC,
    BIOPAR_TYPE_CWC
}
