def process(records, convert):
    values, errors = [], {}
    for index, record in enumerate(records):
        try: values.append(convert(record))
        except Exception as exc:
            values.append(None)
            errors[index] = str(exc)
    return values, errors
