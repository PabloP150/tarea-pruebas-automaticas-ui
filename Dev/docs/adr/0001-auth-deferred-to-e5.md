# ADR 0001 — Autenticación y autorización diferidas a la Entrega 5

- **Estado:** Aceptada
- **Fecha:** 2026-06-07
- **Decisores:** Equipo TicketResolve (orquestado por `manager`; insumo de `security-auditor` y `code-reviewer`)

## Contexto

Durante la consolidación a "100%" del slice `api-tickets`, la auditoría de seguridad
(`security-auditor`, Fase 0) identificó como hallazgo **crítico** la ausencia total de
autenticación y autorización en los 5 endpoints actuales:

- **F-01** — Sin autenticación: cualquier cliente que conozca la URL puede operar.
- **F-02** — IDOR: `GET`/`PATCH /api/v1/incidents/{id}` y el dashboard no verifican propiedad ni identidad.
- **F-03** — Suplantación: `actor`/`author`/`assignee` son texto libre, sin identidad verificada.

## Problema

Cerrar F-01/F-02/F-03 de forma robusta requiere introducir una identidad del llamante
(p. ej. un header `X-User-Id` provisto por el API Gateway tras validar un JWT del IdP
corporativo) y comprobaciones de propiedad/rol. Eso **cambia el contrato HTTP (§6)**:
nuevo header obligatorio y nuevos códigos `401`/`403`.

A la vez, el diseño del curso de Cloud **difiere explícitamente la seguridad detallada
(IAM por servicio, Secrets Manager, KMS, Security Groups, autenticación) a la Entrega 5**
(ver `cloud/Entrega-3-Red.md` §14). El alcance actual es de diseño/consolidación, no de
exponer el sistema a Internet.

## Alternativas consideradas

1. **Implementar ahora una authz mínima vía `X-User-Id`** (caller = `assignee`/`actor`/`author`,
   con `401`/`403`). Cierra F-01/F-02/F-03, pero cambia el contrato §6 y adelanta trabajo de E5.
2. **Diferir a E5 y documentar el riesgo como aceptado** (esta decisión). Mantiene el contrato
   estable y alinea con el roadmap del curso; corrige en paralelo todo lo que **no** depende de auth.
3. No hacer nada / no documentar. Descartada: deja un riesgo crítico sin trazabilidad.

## Decisión

Se adopta la **alternativa 2**: la autenticación/autorización se **difiere a la Entrega 5**.
El riesgo F-01/F-02/F-03 se **acepta de forma explícita y documentada** para el alcance actual
(sistema no expuesto a producción/Internet). En esta consolidación se corrigen **todos** los
demás hallazgos que no cambian el contrato (CRIT-01..04, validación de longitud, sanitización de
`filename`, `ContentType` + allowlist en presigned, `parse_body`, guardia de estado en `resolve`,
escrituras transaccionales, etc.).

## Consecuencias

- **Positivas:** contrato §6 estable; el frontend y los tipos no cambian; foco en endurecer
  correctitud/robustez de lo existente; alineación con el roadmap del curso.
- **Negativas / riesgo aceptado:** mientras no se implemente E5, los endpoints **no deben
  exponerse a Internet** sin una capa de autenticación delante. IDOR y suplantación siguen
  presentes a nivel de aplicación hasta E5.
- **Trabajo futuro (E5):** identidad del llamante vía API Gateway authorizer (JWT/OIDC),
  comprobación de propiedad en `get_ticket`/`resolve_ticket`, derivar `actor`/`author` del token,
  y reflejar `401`/`403` en el contrato §6. También: WAF/rate limiting, Secrets Manager, KMS.

## Referencias

- Reporte de `security-auditor` (Fase 0): F-01..F-15.
- `cloud/Entrega-3-Red.md` §14 (preguntas abiertas para E4/E5).
- [[ARCHITECTURE.md §6]] — contrato HTTP (sin cambios por esta decisión).
