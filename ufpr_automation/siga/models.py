"""Domain models for SIGA (Sistema Integrado de Gestao Academica) integration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StudentStatus:
    """Academic status of a student retrieved from SIGA."""

    grr: str = ""
    nome: str = ""
    curso: str = ""
    situacao: str = ""  # Regular, Trancada, Cancelada, Integralizada
    periodo_atual: int = 0
    horas_integralizadas: int = 0
    curriculo: str = ""  # 2016 or 2020


@dataclass
class EnrollmentInfo:
    """Enrollment details for the current semester."""

    grr: str = ""
    semestre: str = ""  # e.g. "2026/1"
    carga_horaria_matriculada: int = 0
    disciplinas_matriculadas: int = 0
    reprovacao_por_falta_anterior: bool = False
    estagios_ativos: int = 0
    horas_estagio_semanais: int = 0


@dataclass
class EligibilityResult:
    """Result of internship eligibility check based on SOUL.md section 11 rules.

    ``historico_data`` and ``integralizacao_data`` carry the **raw** payload
    fetched from SIGA (``get_historico`` and ``get_integralizacao`` return
    dicts). They exist so that downstream consumers — notably
    ``_consult_siga_async`` in ``graph/nodes.py`` — can expose checker-friendly
    keys (``matricula_status``, ``curriculo_integralizado``, ``nao_vencidas``,
    ``reprovacoes_total``) without re-fetching from SIGA.
    """

    eligible: bool = False
    reasons: list[str] = field(default_factory=list)  # Blocking reasons
    warnings: list[str] = field(default_factory=list)  # Non-blocking alerts
    student: StudentStatus | None = None
    enrollment: EnrollmentInfo | None = None
    historico_data: dict = field(default_factory=dict)
    integralizacao_data: dict = field(default_factory=dict)
