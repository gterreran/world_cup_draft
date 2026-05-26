from django import template

register = template.Library()

FIFA_CODE_TO_FLAG = {
    "ARG": "🇦🇷",
    "FRA": "🇫🇷",
    "ESP": "🇪🇸",
    "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "BRA": "🇧🇷",
    "POR": "🇵🇹",
    "NED": "🇳🇱",
    "BEL": "🇧🇪",
    "GER": "🇩🇪",
    "ITA": "🇮🇹",
    "URU": "🇺🇾",
    "CRO": "🇭🇷",
    "MEX": "🇲🇽",
    "USA": "🇺🇸",
    "COL": "🇨🇴",
    "MAR": "🇲🇦",
    "SUI": "🇨🇭",
    "JPN": "🇯🇵",
    "SEN": "🇸🇳",
    "DEN": "🇩🇰",
    "AUT": "🇦🇹",
    "IRN": "🇮🇷",
    "KOR": "🇰🇷",
    "AUS": "🇦🇺",
    "CAN": "🇨🇦",
    "SRB": "🇷🇸",
    "POL": "🇵🇱",
    "ECU": "🇪🇨",
    "TUR": "🇹🇷",
    "UKR": "🇺🇦",
    "PAN": "🇵🇦",
    "EGY": "🇪🇬",
    "ALG": "🇩🇿",
    "NOR": "🇳🇴",
    "SWE": "🇸🇪",
    "WAL": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "CRC": "🇨🇷",
    "JAM": "🇯🇲",
    "NZL": "🇳🇿",
    "RSA": "🇿🇦",
    "QAT": "🇶🇦",
    "KSA": "🇸🇦",
    "IRQ": "🇮🇶",
    "UZB": "🇺🇿",
    "BOL": "🇧🇴",
    "VEN": "🇻🇪",
    "HON": "🇭🇳",
    "GHA": "🇬🇭",
}


@register.filter
def flag_for_team(team):
    if team is None:
        return "🏳️"

    return FIFA_CODE_TO_FLAG.get(team.fifa_code, "🏳️")