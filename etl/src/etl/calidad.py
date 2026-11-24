"""Registro de las reglas de calidad: cada regla deja conteos antes / afectadas / después."""
from dataclasses import dataclass, field


@dataclass
class Regla:
    regla: str
    descripcion: str
    dimension_dq: str
    tratamiento: str
    filas_antes: int
    afectadas: int
    filas_despues: int


@dataclass
class Bitacora:
    reglas: list = field(default_factory=list)

    def registrar(self, regla, descripcion, dimension, tratamiento, antes, afectadas, despues=None):
        if despues is None:
            despues = antes
        self.reglas.append(Regla(regla, descripcion, dimension, tratamiento, int(antes), int(afectadas), int(despues)))
