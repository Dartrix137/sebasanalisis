"""Base comun de los schemas de la API."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

# Toda accion de administrador sobre acceso o dinero lleva su motivo: es lo
# que se lee en la bitacora. Los espacios de los extremos se quitan antes de
# contar: un motivo de solo espacios no pasa (auditoria del 2026-11-12).
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ApiModel(BaseModel):
    """Base de todo schema que entra o sale por la API.

    `json_schema_serialization_defaults_required` hace que el OpenAPI describa
    las respuestas como de verdad salen: un campo `X | None = None` siempre
    viaja (con `null` si no hay valor), asi que se publica como obligatorio y
    no como opcional. Sin esto, los tipos generados del frontend
    (`npm run gen:types`) dirian que el campo puede faltar, y cada pantalla
    tendria que defenderse de un `undefined` que nunca llega.

    Solo afecta al schema de salida. En las peticiones un campo con valor por
    defecto sigue siendo opcional.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
