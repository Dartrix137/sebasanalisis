"""Base comun de los schemas de la API."""

from pydantic import BaseModel, ConfigDict


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
