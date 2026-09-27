def int_or_str(value):
    try:
        return int(value)
    except ValueError:
        return value
