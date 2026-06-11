from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None

    return mapping.get(key)

@register.filter
def percent_1(value):
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"
