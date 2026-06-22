from datetime import datetime
from zoneinfo import ZoneInfo

# Ключ — подстрока из API timeZoneName (часть после UTC offset).
# standard / daylight — аббревиатуры; iana — для определения DST.
TIMEZONE_ABBREVS: dict[str, tuple[str, str | None, str | None]] = {
    "International Date Line West": ("IDLW", None, "Etc/GMT+12"),
    "Coordinated Universal Time-11": ("SST", None, "Pacific/Pago_Pago"),
    "Hawaii": ("HST", None, "Pacific/Honolulu"),
    "Alaska": ("AKST", "AKDT", "America/Anchorage"),
    "Pacific Time (US & Canada)": ("PST", "PDT", "America/Los_Angeles"),
    "Mountain Time (US & Canada)": ("MST", "MDT", "America/Denver"),
    "Central Time (US & Canada)": ("CST", "CDT", "America/Chicago"),
    "Eastern Time (US & Canada)": ("EST", "EDT", "America/New_York"),
    "Atlantic Time (Canada)": ("AST", "ADT", "America/Halifax"),
    "Newfoundland": ("NST", "NDT", "America/St_Johns"),
    "Buenos Aires": ("ART", None, "America/Argentina/Buenos_Aires"),
    "Coordinated Universal Time-02": ("UTC-02", None, "Etc/GMT+2"),
    "Azores": ("AZOT", "AZOST", "Atlantic/Azores"),
    "Dublin, Edinburgh, Lisbon, London": ("GMT", "BST", "Europe/London"),
    "Brussels, Copenhagen, Madrid, Paris": ("CET", "CEST", "Europe/Paris"),
    "Athens, Bucharest, Istanbul": ("EET", "EEST", "Europe/Bucharest"),
    "Moscow, St. Petersburg": ("MSK", None, "Europe/Moscow"),
    "Tehran": ("IRST", "IRDT", "Asia/Tehran"),
    "Abu Dhabi, Muscat": ("GST", None, "Asia/Dubai"),
    "Kabul": ("AFT", None, "Asia/Kabul"),
    "Islamabad, Karachi": ("PKT", None, "Asia/Karachi"),
    "Chennai, Kolkata, Mumbai, New Delhi": ("IST", None, "Asia/Kolkata"),
    "Kathmandu": ("NPT", None, "Asia/Kathmandu"),
    "Almaty, Novosibirsk": ("ALMT", None, "Asia/Almaty"),
    "Yangon (Rangoon)": ("MMT", None, "Asia/Yangon"),
    "Bangkok, Hanoi, Jakarta": ("ICT", None, "Asia/Bangkok"),
    "Beijing, Chongqing, Hong Kong, Urumqi": ("CST", None, "Asia/Shanghai"),
    "Osaka, Sapporo, Tokyo": ("JST", None, "Asia/Tokyo"),
    "Adelaide": ("ACST", "ACDT", "Australia/Adelaide"),
    "Canberra, Melbourne, Sydney": ("AEST", "AEDT", "Australia/Sydney"),
    "Solomon Islands, New Caledonia": ("SBT", None, "Pacific/Guadalcanal"),
    "Auckland, Wellington": ("NZST", "NZDT", "Pacific/Auckland"),
    "Nuku'alofa": ("TOT", None, "Pacific/Tongatapu"),
}

DEFAULT_ABBREV = "EST"


def _is_dst(iana: str, start_time_iso: str) -> bool:
    dt = datetime.fromisoformat(start_time_iso)
    local = dt.replace(tzinfo=ZoneInfo(iana))
    return bool(local.dst())


def tz_abbrev(time_zone_name: str | None, start_time_iso: str) -> str:
    if not time_zone_name:
        return DEFAULT_ABBREV

    for key, (standard, daylight, iana) in TIMEZONE_ABBREVS.items():
        if key not in time_zone_name:
            continue
        if daylight and iana and _is_dst(iana, start_time_iso):
            return daylight
        return standard

    return DEFAULT_ABBREV


def format_time_with_tz(start_time_iso: str, time_zone_name: str | None = None) -> str:
    dt = datetime.fromisoformat(start_time_iso)
    time_part = dt.strftime("%I:%M %p").lower().lstrip("0")
    abbrev = tz_abbrev(time_zone_name, start_time_iso)
    return f"{time_part} {abbrev}"
