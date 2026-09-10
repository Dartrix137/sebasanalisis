# CLAUDE.md — Sebasanálisis

Este archivo guía a Claude Code en este repositorio. Léelo completo antes de escribir código, y vuelve a él ante cualquier duda de alcance o de lenguaje del producto.

## Qué es este proyecto

Plataforma fullstack por suscripción que da a los usuarios **análisis estadístico descriptivo** sobre juegos de casino, empezando por ruleta europea/americana, con arquitectura preparada para agregar más juegos (dados, etc.) desde un panel de administración sin escribir código nuevo por cada juego.

**Documento de referencia obligatorio**: `docs/ARQUITECTURA_Y_ESTADISTICA.md`. Contiene las fórmulas exactas del motor estadístico, el modelo de datos completo, los endpoints, y la definición cerrada del alcance del MVP. Si algo en este CLAUDE.md y ese documento parecen contradecirse, gana el documento de arquitectura — pídele al usuario que lo aclare antes de asumir.

**Documentos fuente en `docs/reference/`** (no modificar, son insumo):

- `ESTRATEGIA_DE_RULETA_CORREGIDA_Y_VERIFICADA.txt` — fuente de verdad matemática validada por un analista.
- `explicacion_analisis_estadistico_ruleta.md` — boceto previo; se toman sus técnicas estadísticas (shrinkage, χ², recencia, EV).

## Regla de producto no negociable: lenguaje no-predictivo

Este es el requisito más importante del proyecto, por encima de conveniencia de código o velocidad de desarrollo:

- Nunca uses "predicción", "predice", "va a salir", ni nada que implique que el sistema anticipa el resultado futuro de un giro independiente.
- Usa "sugerencia estadística", "señal", "desviación observada", "fuerza de la señal" (FUERTE/MEDIA/DÉBIL).
- Si al escribir un commit, componente de UI, string de copy, o nombre de variable/tabla dudas si suena predictivo, revísalo contra la tabla de terminología en `docs/ARQUITECTURA_Y_ESTADISTICA.md` §0 antes de continuar.
- Esto aplica a nombres de tablas y campos también (ej: `statistical_suggestions`, no `predictions`).

## Stack técnico

- **Backend**: FastAPI (Python 3.11+), SQLAlchemy, Alembic, PostgreSQL, Pydantic v2.
- **Frontend**: Next.js (React + TypeScript), Tailwind CSS.
- **Sin IA**: el proyecto no integra modelos de visión ni de lenguaje. Los números los ingresa siempre el usuario, a mano. Esto es una decisión de producto deliberada — ver "Ingreso de números" más abajo.
- **Auth**: JWT (access + refresh), hash de contraseñas con bcrypt o argon2.
- **Motor estadístico**: vive en `backend/app/engine/`, debe ser Python puro (sin FastAPI, sin SQLAlchemy, sin llamadas de red) para poder testear con pytest sin infraestructura. Usa `numpy`/`scipy` donde corresponda (chi-cuadrado, distribución binomial).

## Estructura de carpetas esperada

Sigue exactamente la estructura definida en `docs/ARQUITECTURA_Y_ESTADISTICA.md` §3.1. No la reinventes ni la aplanes por conveniencia.

## Orden de construcción (no saltar pasos)

1. Schema de base de datos (Alembic) + seed (usuario admin, ruleta europea y americana precargadas con su `categories_json`).
2. Auth (registro/login/refresh/me).
3. Admin: CRUD de juegos/variantes con formulario simple (sin builder visual todavía).
4. Menú principal / selector de juegos.
5. Flujo de ruleta con ingreso manual de números giro a giro — esto ya debe ser una demo jugable end-to-end.
6. Motor estadístico núcleo: frecuencia+shrinkage, recencia, χ², racha, EV, ranking top-3, auto-evaluación.
7. Motor de bankroll: martingala, d'Alembert, Fibonacci, flat, y modo dos-sectores.
8. Carga inicial de números al abrir una sesión: el usuario pega o escribe los números que ya observó en la mesa, y quedan registrados como historial de la sesión antes del primer giro nuevo.

No avances a un paso sin que el anterior tenga al menos un test o una verificación manual funcionando. Si vas a saltarte este orden por alguna razón, dilo explícitamente y pide confirmación.

## Ingreso de números

Todos los números de una sesión los ingresa el usuario. Hay dos momentos, y ambos son manuales:

- **Carga inicial (al abrir la sesión)**: el usuario escribe o pega los números que ya vio en la pantalla de la mesa antes de sentarse a registrar. Quedan como historial de la sesión, con `source = 'initial_batch'`.
- **Giro a giro (durante la sesión)**: cada número nuevo se ingresa en el momento, con `source = 'manual'`.

Reglas que no se negocian:

- **El orden importa y hay que preguntarlo, nunca adivinarlo.** El motor pondera por recencia (§2.3): si el orden se invierte, la ponderación queda al revés y el análisis sale mal sin que nada falle visiblemente. La carga inicial debe pedir explícitamente si la lista viene del más antiguo al más reciente o al revés, y el backend normaliza siempre a orden cronológico ascendente (`spin_index` creciente = más antiguo → más reciente).
- **Validar contra `possible_outcomes` de la variante.** Un valor que no pertenece a la variante se rechaza; no se descarta en silencio ni se "corrige".
- **Sin IA, sin OCR, sin lectura de imágenes.** Se evaluó un pipeline de pantallazos con un modelo de visión y se descartó: introduce errores de extracción que el usuario tendría que revisar igual, y un costo por uso que no se justifica frente a escribir los números.

## Motor estadístico: reglas de implementación

- El motor (`engine/`) opera únicamente sobre la estructura genérica `possible_outcomes` + `categories` (ver §3.2 del doc de arquitectura). **Nunca** hardcodees lógica específica de ruleta (docenas, colores) dentro del motor — eso vive solo en los datos de `game_variants.categories_json`. Esto es lo que permite agregar dados después sin tocar `engine/`.
- Cada función del motor debe ser pura: recibe datos, devuelve resultado, sin efectos secundarios ni acceso a DB.
- Toda sugerencia estadística debe traer siempre junto: `theoretical_probability` y `observed_frequency_shrunk` — nunca mostrar solo uno de los dos (ver §2 del doc de arquitectura, es una regla anti-falacia del jugador).
- El χ² requiere mínimo 200 giros y p<0.05 para activarse — no lo actives con menos datos aunque el cálculo "funcione" matemáticamente con menos. Ese mínimo es un **piso de ruido, no un umbral de detección de sesgo**: detectar un sesgo explotable pediría del orden de 30.000 giros (ver §2.4 del doc de arquitectura). No describas esa señal como si detectara mesas sesgadas.
- El p<0.05 del χ² se evalúa sobre el p-valor **ya corregido por comparaciones múltiples** (Benjamini-Hochberg), nunca sobre el crudo: la prueba corre sobre las 5 categorías a la vez, y sin corregir una de cada cuatro sesiones mostraría una señal FUERTE espuria.
- Toda frecuencia observada viaja con su intervalo de Wilson (§2.2). No derives de él un veredicto por opción del tipo "esta desviación se distingue del azar" — serían 13 pruebas simultáneas y marcarían algo en un tercio de las mesas justas. El intervalo describe incertidumbre; afirmar es trabajo de `strength`, que sí está corregida.
- La auto-evaluación (línea base ingenua vs. motor) es un requisito del MVP, no un nice-to-have — impleméntala desde el principio del motor, no la dejes para el final.

## Convenciones de código

- Python: type hints en todo, Pydantic para validación de I/O, nombres de funciones y variables en español o inglés de forma consistente dentro de cada módulo (no mezclar en el mismo archivo).
- Nombres de tablas/campos en `snake_case`, en español donde ya están definidos en el doc de arquitectura (ej. `bankroll_current`), no los traduzcas.
- Tests: cada módulo de `engine/` necesita tests unitarios con pytest antes de conectarse a un endpoint. Usa casos conocidos del documento de estrategia verificado (ej. la tabla de martingala $100→$102.300 en 10 pérdidas) como test de regresión.
- Frontend: componentes tipados, sin `any`. Usa el contrato de `schemas/` (Pydantic) como referencia para los tipos TypeScript del cliente API — mantenlos sincronizados manualmente por ahora (no hay generador automático en el MVP).

## Diseños de referencia

`docs/design/` contendrá mockups (login/registro, vista de ruleta). Impleméntalos fielmente en layout y jerarquía de información. Si hay conflicto entre el mockup y una regla de este documento (ej. el mockup no muestra el disclaimer fijo), **gana la regla de este documento** — agrega el disclaimer aunque no esté en el mockup, y avisa al usuario de la discrepancia.

## Qué NO hacer

- No implementes pagos/Wompi todavía — solo deja los campos de DB ya definidos en el schema, sin lógica.
- No construyas el builder visual de categorías del admin en el MVP — usa un formulario estructurado simple.
- No implementes las señales avanzadas (transición condicional, k-gramas, ciclo, señales de pleno) sin que el usuario lo pida explícitamente — están fuera del scope del MVP (ver §2.9 del doc de arquitectura).
- No uses SQLite ni Prisma (eso era del boceto de referencia) — este proyecto usa PostgreSQL + SQLAlchemy/Alembic.
- No agregues reconocimiento de imágenes, OCR, ni ninguna llamada a un modelo de visión o de lenguaje para leer los números de un pantallazo. Se evaluó y se descartó: el usuario los ingresa a mano.

## Cuando algo no esté claro

Si una decisión de producto no está cubierta en `docs/ARQUITECTURA_Y_ESTADISTICA.md` ni aquí, no la inventes en silencio: implementa la interpretación más simple y conservadora (menos alcance, más honestidad estadística), y déjalo señalado en tu respuesta para que el usuario lo confirme.
