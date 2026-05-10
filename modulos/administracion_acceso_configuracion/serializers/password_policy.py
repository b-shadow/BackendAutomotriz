from rest_framework import serializers


def validate_strong_password(value: str):
    if len(value) < 8:
        raise serializers.ValidationError("La contraseña debe tener al menos 8 caracteres.")
    if not any(c.isupper() for c in value):
        raise serializers.ValidationError("La contraseña debe incluir al menos 1 letra mayúscula.")
    if not any(c.islower() for c in value):
        raise serializers.ValidationError("La contraseña debe incluir al menos 1 letra minúscula.")
    if not any(c.isdigit() for c in value):
        raise serializers.ValidationError("La contraseña debe incluir al menos 1 número.")
    if value.isalnum():
        raise serializers.ValidationError("La contraseña debe incluir al menos 1 símbolo.")
    return value
