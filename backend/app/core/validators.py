import re


def normalize_cpf(value: str | None) -> str | None:
    """Valida o CPF (dígitos verificadores) e devolve no formato 000.000.000-00."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11 or digits == digits[0] * 11:
        raise ValueError("CPF inválido.")
    for n in (9, 10):
        total = sum(int(digits[i]) * (n + 1 - i) for i in range(n))
        check = (total * 10) % 11 % 10
        if check != int(digits[n]):
            raise ValueError("CPF inválido.")
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def mask_cpf(cpf: str | None) -> str | None:
    return f"***.***.***-{cpf[-2:]}" if cpf else None


def normalize_plate(value: str | None) -> str | None:
    if not value:
        return None
    plate = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}", plate):
        raise ValueError("Placa inválida (use o formato AAA1234 ou AAA1B23).")
    return plate
